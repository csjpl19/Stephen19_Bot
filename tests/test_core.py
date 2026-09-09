import unittest
from core import UserError, audio_filename, check_info, parse_request, youtube_url


class ValidationTests(unittest.TestCase):
    def test_audio_filename_is_portable_and_keeps_accents(self):
        self.assertEqual(audio_filename('Beyoncé / Halo: "Live"?'), "Beyoncé Halo Live.mp3")
        self.assertEqual(audio_filename("../../Titre\\test"), "Titre test.mp3")
        self.assertEqual(audio_filename("CON"), "_CON.mp3")
        self.assertEqual(audio_filename("nul.demo"), "_nul.demo.mp3")
        self.assertEqual(audio_filename(" ... "), "Audio YouTube.mp3")
        self.assertLessEqual(len(audio_filename("🎵é" * 200).encode("utf-8")), 184)

    def test_title_and_artist_are_accepted(self):
        self.assertEqual(parse_request("  Une chanson — Un artiste  "), "Une chanson — Un artiste")
        self.assertEqual(parse_request("youtu.be/abcdefghijk"), "https://www.youtube.com/watch?v=abcdefghijk")

    def test_invalid_requests_are_rejected(self):
        for text in ["", "  ", "x" * 201, "file:///tmp/test", "title\nother", "https://evil.example/song"]:
            with self.subTest(text=text), self.assertRaises(UserError):
                parse_request(text)

    def test_supported_links_become_one_canonical_url(self):
        for url in [
            "https://youtu.be/abcdefghijk?si=tracking",
            "https://www.youtube.com/watch?v=abcdefghijk&list=ignored",
            "https://music.youtube.com/watch?v=abcdefghijk",
            "https://m.youtube.com/shorts/abcdefghijk",
            "https://youtube.com/embed/abcdefghijk",
        ]:
            with self.subTest(url=url):
                self.assertEqual(youtube_url(url), "https://www.youtube.com/watch?v=abcdefghijk")

    def test_rejects_arbitrary_hosts_and_malformed_urls(self):
        for url in [
            "http://127.0.0.1/a", "file:///etc/passwd",
            "https://youtube.com.evil.example/watch?v=abcdefghijk",
            "https://youtube.com@evil.example/watch?v=abcdefghijk",
            "https://user:pass@youtube.com/watch?v=abcdefghijk",
            "https://youtube.com:443/watch?v=abcdefghijk",
            "https://youtube.com/playlist?list=abc",
            "https://youtu.be/short", "bonjour", "https://[invalid",
            "https://youtu.be/abcdefghijk extra",
        ]:
            with self.subTest(url=url), self.assertRaises(UserError):
                youtube_url(url)

    def test_duration_boundary_and_restrictions(self):
        check_info({"duration": 1200})
        for info in [
            {"duration": 1201}, {"duration": None}, {"duration": -1},
            {"duration": float("nan")}, {"duration": 10, "is_live": True},
            {"duration": 10, "live_status": "is_upcoming"},
            {"duration": 10, "_type": "playlist"},
        ]:
            with self.subTest(info=info), self.assertRaises(UserError):
                check_info(info)


if __name__ == "__main__":
    unittest.main()
