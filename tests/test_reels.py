import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from urllib.request import Request

from yt_dlp import YoutubeDL
from yt_dlp.extractor.common import InfoExtractor

from core import UserError, parse_media_request, social_url
from reels import (SocialRedirectHandler, check_reel_info, download_reel, prepare_video,
                   probe_media, resolve_social_url, without_watermarked_formats)
from worker import run_ffmpeg


class SocialLinkTests(unittest.TestCase):
    def test_platform_links_and_short_links(self):
        cases = [
            ("instagram.com/reel/ABC_123/?igsh=tracking", "Instagram", False),
            ("https://www.instagram.com/user/reels/ABC123/", "Instagram", False),
            ("https://www.instagram.com/share/reel/ABC123/", "Instagram", True),
            ("https://www.tiktok.com/@user/video/123456?is_from_webapp=1", "TikTok", False),
            ("https://vm.tiktok.com/ABC123/", "TikTok", True),
            ("https://vt.tiktok.com/ABC123/", "TikTok", True),
            ("https://www.tiktok.com/t/ABC123/", "TikTok", True),
            ("https://m.facebook.com/reel/123456/", "Facebook", False),
            ("https://www.facebook.com/watch/?v=123456", "Facebook", False),
            ("https://www.facebook.com/user/videos/123456/", "Facebook", False),
            ("https://www.facebook.com/share/r/ABC123/", "Facebook", True),
            ("https://www.facebook.com/share/v/ABC123/", "Facebook", True),
            ("https://fb.watch/ABC_123/", "Facebook", True),
        ]
        for value, platform, shortened in cases:
            with self.subTest(value=value):
                url, actual_platform, actual_shortened = social_url(value)
                self.assertEqual((actual_platform, actual_shortened), (platform, shortened))
                self.assertTrue(url.startswith("https://"))
                self.assertEqual(parse_media_request(value), ("video", url))

    def test_rejects_other_hosts_profiles_live_and_malformed_urls(self):
        for url in [
            "https://instagram.com.evil.example/reel/123/", "https://127.0.0.1/reel/123/",
            "https://user:secret@instagram.com/reel/123/", "https://instagram.com:443/reel/123/",
            "https://instagram.com/reel/123/\ntext", "file:///tmp/movie.mp4",
            "https://instagram.com/user/", "https://www.tiktok.com/@user/live",
            "https://www.facebook.com/groups/123/", "https://instagram.com/reels/audio/",
            "https://www.facebook.com/flx/warn/?u=https://evil.example",
            "https://instagram.com\\@evil.example/reel/123/", "https://[invalid",
        ]:
            with self.subTest(url=url), self.assertRaises(UserError):
                social_url(url)

    def test_audio_routing_is_preserved_and_commands_are_explicit(self):
        self.assertEqual(parse_media_request("Un titre Artiste"), ("audio", "Un titre Artiste"))
        self.assertEqual(parse_media_request("https://youtu.be/abcdefghijk")[0], "audio")
        with self.assertRaises(UserError):
            parse_media_request("https://instagram.com/reel/ABC/", "audio")
        with self.assertRaises(UserError):
            parse_media_request("https://youtu.be/abcdefghijk", "video")

    def test_short_link_resolution_and_failed_redirect(self):
        response = MagicMock()
        response.__enter__.return_value.geturl.return_value = "https://www.tiktok.com/@user/video/123"
        with patch("reels.build_opener") as factory:
            factory.return_value.open.return_value = response
            self.assertEqual(resolve_social_url("https://vm.tiktok.com/ABC/"),
                             ("https://www.tiktok.com/@user/video/123", "TikTok"))
            response.__enter__.return_value.geturl.return_value = "https://vm.tiktok.com/ABC/"
            with self.assertRaisesRegex(UserError, "lien direct"):
                resolve_social_url("https://vm.tiktok.com/ABC/")

    def test_redirect_is_checked_before_requesting_target(self):
        handler = SocialRedirectHandler("TikTok")
        original = Request("https://vm.tiktok.com/ABC/")
        for target in ["http://127.0.0.1/", "https://evil.example/", "https://www.facebook.com/reel/123/"]:
            with self.subTest(target=target), self.assertRaises(UserError):
                handler.redirect_request(original, None, 302, "Found", {}, target)
        redirected = handler.redirect_request(
            original, None, 302, "Found", {}, "https://www.tiktok.com/@user/video/123?tracking=1")
        self.assertEqual(redirected.full_url, "https://www.tiktok.com/@user/video/123")

    def test_album_live_and_duration_checks(self):
        check_reel_info({"duration": None})
        for info in [{"_type": "playlist"}, {"_type": "multi_video"}, {"duration": 1201},
                     {"is_live": True}, {"has_drm": True}, {"duration": float("nan")}]:
            with self.subTest(info=info), self.assertRaises(UserError):
                check_reel_info(info)

    def test_formats_exclude_marked_versions_and_keep_sound(self):
        formats = [
            {"format_id": "audio", "ext": "m4a", "vcodec": "none", "acodec": "aac", "url": "https://example.com/a"},
            {"format_id": "clean", "ext": "mp4", "vcodec": "h264", "acodec": "none", "url": "https://example.com/v"},
            {"format_id": "download", "vcodec": "h264", "acodec": "aac", "format_note": "watermarked"},
        ]
        context = without_watermarked_formats({"formats": formats, "incomplete_formats": False})
        with YoutubeDL({"quiet": True}) as ydl:
            selected = list(ydl.build_format_selector("bv*+ba/b/bv")(context))
        self.assertEqual(selected[0]["format_id"], "clean+audio")
        with self.assertRaisesRegex(UserError, "filigrane"):
            without_watermarked_formats({"formats": [formats[0], formats[2]]})

    def test_single_silent_video_is_supported(self):
        context = {"incomplete_formats": True, "formats": [{"format_id": "silent", "vcodec": "h264", "acodec": "none",
                                "url": "https://example.com/v"}]}
        with YoutubeDL({"quiet": True}) as ydl:
            selected = list(ydl.build_format_selector("bv*+ba/b/bv")(without_watermarked_formats(context)))
        self.assertEqual(selected[0]["format_id"], "silent")

    def test_album_is_rejected_before_media_download(self):
        with TemporaryDirectory() as folder, patch("reels.YoutubeDL") as factory:
            ydl = factory.return_value.__enter__.return_value
            ydl.extract_info.return_value = {"_type": "playlist", "entries": []}
            with self.assertRaises(UserError):
                download_reel("https://www.instagram.com/p/ABC/", Path(folder))
            ydl.process_ie_result.assert_not_called()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe requis")
class VideoFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="musicbot-video-test-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_transcodes_portrait_video_with_sound_and_faststart(self):
        source = self.folder / "source.mkv"
        run_ffmpeg(["-f", "lavfi", "-i", "color=c=blue:s=360x640:r=24:d=0.5",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
                    "-c:v", "ffv1", "-c:a", "pcm_s16le", str(source)])
        target = self.folder / "video.mp4"
        result = prepare_video(source, target)
        self.assertLess(result["width"], result["height"])
        streams = probe_media(target)["streams"]
        self.assertEqual([s["codec_name"] for s in streams], ["h264", "aac"])
        self.assertEqual(streams[0]["pix_fmt"], "yuv420p")
        content = target.read_bytes()
        self.assertLess(content.index(b"moov"), content.index(b"mdat"))

    def test_silent_compatible_video_remux_and_download_pipeline(self):
        source = self.folder / "source.mp4"
        run_ffmpeg(["-f", "lavfi", "-i", "color=c=red:s=320x240:r=24:d=0.5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)])
        with patch("reels.YoutubeDL") as factory:
            ydl = factory.return_value.__enter__.return_value
            ydl.extract_info.return_value = {"title": "Vidéo été", "duration": 0.5}
            ydl.process_ie_result.return_value = ydl.extract_info.return_value
            result = download_reel("https://www.facebook.com/reel/123/", self.folder)
        self.assertEqual(result["kind"], "video")
        self.assertEqual((result["width"], result["height"]), (320, 240))
        self.assertNotIn("source_url", result)
        self.assertTrue((self.folder / "thumbnail.jpg").is_file())
        self.assertEqual(len(probe_media(self.folder / "video.mp4")["streams"]), 1)
        # Vérifie les vrais noms d'extracteurs, sans requête réseau.
        with YoutubeDL({"quiet": True, "allowed_extractors": factory.call_args.args[0]["allowed_extractors"]}) as real:
            self.assertEqual(set(real._ies), {"Instagram", "TikTok", "Facebook", "FacebookReel"})

    def test_audio_only_file_is_rejected(self):
        source = self.folder / "source.mp4"
        run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:duration=0.2", "-c:a", "aac", str(source)])
        with self.assertRaisesRegex(UserError, "ne contient pas de vidéo"):
            prepare_video(source, self.folder / "video.mp4")

    def test_real_downloader_pipeline_from_local_fixture(self):
        fixture = self.folder / "fixture.mp4"
        run_ffmpeg(["-f", "lavfi", "-i", "color=c=green:s=320x240:r=24:d=0.5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(fixture)])

        class LocalReelIE(InfoExtractor):
            _VALID_URL = r"https://www\.instagram\.com/reel/(?P<id>[A-Za-z]+)/"

            def _real_extract(self, url):
                return {"id": "ABC", "title": "Local reel", "duration": 0.5,
                        "formats": [{"format_id": "clean", "url": fixture.as_uri(),
                                     "ext": "mp4", "vcodec": "h264", "acodec": "none"}]}

        def create_downloader(options):
            # Seul ce test autorise file:// ; aucune plateforme n'est contactée.
            ydl = YoutubeDL({**options, "allowed_extractors": [], "enable_file_urls": True})
            ydl.add_info_extractor(LocalReelIE())
            return ydl

        with patch("reels.YoutubeDL", side_effect=create_downloader):
            result = download_reel("https://www.instagram.com/reel/ABC/", self.folder)
        self.assertEqual(result["title"], "Local reel")
        self.assertEqual(probe_media(self.folder / "video.mp4")["streams"][0]["codec_name"], "h264")

    def test_oversized_result_is_rejected(self):
        source = self.folder / "source.mp4"
        run_ffmpeg(["-f", "lavfi", "-i", "color=c=red:s=320x240:d=0.2",
                    "-c:v", "libx264", str(source)])
        with patch("reels.MAX_VIDEO_BYTES", 1000), self.assertRaisesRegex(UserError, "49 Mo"):
            prepare_video(source, self.folder / "video.mp4")
