"""Vérifie de vrais MP3 et pochettes avec FFmpeg, sans YouTube ni Telegram."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core import UserError
from worker import add_metadata, download, run_ffmpeg


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe requis")
class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="musicbot-test-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.audio = self.folder / "audio.mp3"
        run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
                    "-c:a", "libmp3lame", "-b:a", "192k", str(self.audio)])

    def probe(self, path):
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            check=True, capture_output=True, encoding="utf-8", timeout=30)
        return json.loads(result.stdout)

    def make_cover(self):
        source = self.folder / "audio.webp"
        run_ffmpeg(["-f", "lavfi", "-i", "color=c=blue:s=1280x720",
                    "-frames:v", "1", str(source)])
        return source

    def audio_hash(self):
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(self.audio), "-map", "0:a:0",
             "-c:a", "copy", "-f", "hash", "-hash", "sha256", "-"],
            check=True, capture_output=True, timeout=30)
        return result.stdout

    def test_embeds_jpeg_front_cover_id3v23_and_preserves_audio(self):
        before = self.audio_hash()
        info = {"thumbnails": [{"filepath": str(self.make_cover())}], "album": "L’été"}
        self.assertTrue(add_metadata(self.audio, info, "Été 🎵", "Beyoncé"))
        self.assertEqual(self.audio.read_bytes()[:4], b"ID3\x03")
        metadata = self.probe(self.audio)
        self.assertEqual(metadata["format"]["tags"]["title"], "Été 🎵")
        self.assertEqual(metadata["format"]["tags"]["artist"], "Beyoncé")
        self.assertEqual(metadata["format"]["tags"]["album"], "L’été")
        picture = next(s for s in metadata["streams"] if s["codec_type"] == "video")
        self.assertEqual(picture["codec_name"], "mjpeg")
        self.assertEqual(picture["disposition"]["attached_pic"], 1)
        self.assertEqual(picture["tags"]["comment"], "Cover (front)")
        self.assertLessEqual(max(picture["width"], picture["height"]), 640)
        self.assertEqual(self.audio_hash(), before)
        preview = self.folder / "thumbnail.jpg"
        self.assertLess(preview.stat().st_size, 200_000)
        stream = self.probe(preview)["streams"][0]
        self.assertEqual(stream["codec_name"], "mjpeg")
        self.assertLessEqual(max(stream["width"], stream["height"]), 320)

    def test_missing_or_corrupt_thumbnail_keeps_playable_tagged_audio(self):
        corrupt = self.folder / "bad.webp"
        corrupt.write_bytes(b"not an image")
        for thumbnails in ([], [{"filepath": str(corrupt)}]):
            with self.subTest(thumbnails=thumbnails):
                self.assertFalse(add_metadata(self.audio, {"thumbnails": thumbnails}, "Titre", "Artiste"))
                metadata = self.probe(self.audio)
                self.assertEqual(metadata["format"]["tags"]["title"], "Titre")
                self.assertEqual([s["codec_type"] for s in metadata["streams"]], ["audio"])
                self.assertFalse((self.folder / "thumbnail.jpg").exists())

    def test_download_tags_file_and_uses_track_title(self):
        info = {"duration": 1, "track": "La chanson", "title": "Titre vidéo",
                "artist": "Artiste", "thumbnails": [{"filepath": str(self.make_cover())}]}
        with patch("worker.YoutubeDL") as factory:
            factory.return_value.__enter__.return_value.extract_info.return_value = info
            result = download("https://youtu.be/abcdefghijk", self.folder)
        self.assertTrue(factory.call_args.args[0]["writethumbnail"])
        self.assertEqual(result["title"], "La chanson")
        self.assertTrue(result["cover_embedded"])
        self.assertEqual(self.probe(self.audio)["format"]["tags"]["title"], result["title"])

    def test_size_limit_includes_embedded_picture(self):
        original_size = self.audio.stat().st_size
        info = {"duration": 1, "title": "Test",
                "thumbnails": [{"filepath": str(self.make_cover())}]}
        with patch("worker.YoutubeDL") as factory, patch("worker.MAX_AUDIO_BYTES", original_size):
            factory.return_value.__enter__.return_value.extract_info.return_value = info
            with self.assertRaisesRegex(UserError, "49 Mo"):
                download("https://youtu.be/abcdefghijk", self.folder)


if __name__ == "__main__":
    unittest.main()
