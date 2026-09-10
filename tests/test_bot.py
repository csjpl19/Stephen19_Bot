import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import bot
from core import UserError


class BotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot.ACTIVE_USERS.clear()
        bot.ALLOWED_USERS.clear()
        self.status = SimpleNamespace(edit_text=AsyncMock())
        self.message = SimpleNamespace(
            text="https://youtu.be/abcdefghijk",
            reply_text=AsyncMock(return_value=self.status), reply_audio=AsyncMock(), reply_video=AsyncMock())
        self.update = SimpleNamespace(effective_message=self.message, effective_user=SimpleNamespace(id=42))
        self.context = SimpleNamespace(args=[])

    async def test_success_sends_file_then_cleans_up(self):
        folders = []

        async def fake_worker(url, folder):
            folders.append(folder)
            (folder / "audio.mp3").write_bytes(b"fake mp3 for transport mock")
            return {"title": "Test", "performer": "Test", "duration": 10, "source_url": url}

        with patch.object(bot, "run_worker", side_effect=fake_worker):
            await bot.request_audio(self.update, self.context)
        self.message.reply_audio.assert_awaited_once()
        self.assertEqual(self.message.reply_audio.call_args.kwargs["filename"], "Test.mp3")
        self.assertIsNone(self.message.reply_audio.call_args.kwargs["thumbnail"])
        self.assertFalse(folders[0].exists())
        self.assertFalse(bot.ACTIVE_USERS)

    async def test_sends_thumbnail_while_files_are_open(self):
        async def fake_worker(url, folder):
            (folder / "audio.mp3").write_bytes(b"mp3")
            (folder / "thumbnail.jpg").write_bytes(b"jpeg")
            return {"title": "Été / Live", "performer": "Artiste", "duration": 10,
                    "source_url": url, "cover_embedded": True}

        async def receive(**kwargs):
            self.assertEqual(kwargs["filename"], "Été Live.mp3")
            self.assertEqual(kwargs["audio"].read(), b"mp3")
            self.assertEqual(kwargs["thumbnail"].read(), b"jpeg")

        self.message.reply_audio.side_effect = receive
        with patch.object(bot, "run_worker", side_effect=fake_worker):
            await bot.request_audio(self.update, self.context)
        sent = self.message.reply_audio.call_args.kwargs
        self.assertTrue(sent["audio"].closed)
        self.assertTrue(sent["thumbnail"].closed)

    async def test_missing_cover_still_sends_audio_and_informs_user(self):
        async def fake_worker(url, folder):
            (folder / "audio.mp3").write_bytes(b"mp3")
            return {"title": "Test", "performer": "Artiste", "duration": 10,
                    "source_url": url, "cover_embedded": False}

        with patch.object(bot, "run_worker", side_effect=fake_worker):
            await bot.request_audio(self.update, self.context)
        self.message.reply_audio.assert_awaited_once()
        self.assertIn("pochette indisponible", self.status.edit_text.call_args.args[0])

    async def test_failure_releases_slot_and_cleans_up(self):
        folders = []

        async def fail(url, folder):
            folders.append(folder)
            (folder / "partial").write_bytes(b"partial")
            raise UserError("Indisponible")

        with patch.object(bot, "run_worker", side_effect=fail):
            await bot.request_audio(self.update, self.context)
        self.assertFalse(folders[0].exists())
        self.assertFalse(bot.ACTIVE_USERS)
        self.message.reply_audio.assert_not_awaited()
        self.status.edit_text.assert_awaited_with("Indisponible")

    async def test_capacity_prevents_download(self):
        bot.ACTIVE_USERS.update({1, 2})
        with patch.object(bot, "run_worker", new_callable=AsyncMock) as worker:
            await bot.request_audio(self.update, self.context)
            worker.assert_not_awaited()

    async def test_access_control_prevents_download(self):
        bot.ALLOWED_USERS.add(99)
        with patch.object(bot, "run_worker", new_callable=AsyncMock) as worker:
            await bot.request_audio(self.update, self.context)
            worker.assert_not_awaited()

    async def test_title_is_passed_to_worker(self):
        self.message.text = "Titre de chanson Artiste"
        with patch.object(bot, "run_worker", new_callable=AsyncMock,
                          side_effect=UserError("Aucun résultat")) as worker:
            await bot.request_audio(self.update, self.context)
        self.assertEqual(worker.call_args.args[0], "Titre de chanson Artiste")

    async def test_social_link_sends_video_without_platform_preview(self):
        self.message.text = "https://www.instagram.com/reel/ABC/"
        folders = []

        async def fake_worker(url, folder):
            folders.append(folder)
            (folder / "video.mp4").write_bytes(b"video")
            return {"kind": "video", "title": "Reel / été", "duration": 5, "width": 360, "height": 640}

        async def receive(**kwargs):
            self.assertEqual(kwargs["video"].read(), b"video")
            self.assertEqual(kwargs["filename"], "Reel été.mp4")
            self.assertTrue(kwargs["supports_streaming"])
            self.assertFalse(kwargs["do_quote"])
            self.assertNotIn("caption", kwargs)

        self.message.reply_video.side_effect = receive
        with patch.object(bot, "run_worker", side_effect=fake_worker):
            await bot.request_media(self.update, self.context)
        self.message.reply_video.assert_awaited_once()
        self.message.reply_audio.assert_not_awaited()
        self.status.edit_text.assert_awaited_with("Vidéo envoyée ✓")
        self.assertFalse(folders[0].exists())
        self.assertFalse(bot.ACTIVE_USERS)

    async def test_video_command_and_worker_error_cleanup(self):
        self.message.text = "/video https://www.facebook.com/reel/123/"
        self.context.args = ["https://www.facebook.com/reel/123/"]
        with patch.object(bot, "run_worker", new_callable=AsyncMock, side_effect=UserError("Vidéo inaccessible")) as worker:
            await bot.request_video(self.update, self.context)
        self.assertEqual(worker.call_args.args[0], self.context.args[0])
        self.status.edit_text.assert_awaited_with("Vidéo inaccessible")
        self.assertFalse(bot.ACTIVE_USERS)
        self.message.reply_video.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
