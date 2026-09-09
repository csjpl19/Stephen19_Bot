import unittest
from unittest.mock import MagicMock, patch
from core import UserError
from worker import resolve_video


class SearchTests(unittest.TestCase):
    def test_search_selects_first_video_and_uses_canonical_url(self):
        search = MagicMock()
        search.extract_info.return_value = {"entries": [{"id": "abcdefghijk", "url": "https://untrusted.example"}]}
        with patch("worker.YoutubeDL") as factory:
            factory.return_value.__enter__.return_value = search
            self.assertEqual(resolve_video("Titre Artiste"), "https://www.youtube.com/watch?v=abcdefghijk")
        search.extract_info.assert_called_once_with("ytsearch1:Titre Artiste", download=False)

    def test_empty_search_has_clear_error(self):
        with patch("worker.YoutubeDL") as factory:
            factory.return_value.__enter__.return_value.extract_info.return_value = {"entries": []}
            with self.assertRaisesRegex(UserError, "Aucun résultat"):
                resolve_video("Chanson introuvable")

    def test_direct_link_skips_search(self):
        with patch("worker.YoutubeDL") as factory:
            self.assertEqual(resolve_video("https://youtu.be/abcdefghijk"), "https://www.youtube.com/watch?v=abcdefghijk")
            factory.assert_not_called()
