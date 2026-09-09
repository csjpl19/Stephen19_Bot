"""Bot Telegram : titre ou lien YouTube → MP3. Lancer : python bot.py."""
import asyncio
import json
import logging
import os
import signal
import shutil
import sys
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

from dotenv import load_dotenv
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from core import JOB_TIMEOUT, MAX_AUDIO_BYTES, MAX_JOBS, UserError, audio_filename, parse_request

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
ACTIVE_USERS: set[int] = set()
ALLOWED_USERS: set[int] = set()
LOGGER = logging.getLogger("musicbot")
HELP = (
    "Écris le titre d'une chanson, idéalement avec l'artiste : je la cherche sur YouTube et je t'envoie le MP3. Un lien YouTube fonctionne aussi.\n\n"
    "La recherche sélectionne automatiquement le premier résultat YouTube.\n\n"
    "• Une vidéo à la fois, de 20 minutes maximum.\n"
    "• MP3 à 192 kbit/s, limité à 49 Mo.\n"
    "• Pas de playlists ni de directs.\n"
    "• Utilise des contenus dont le téléchargement est autorisé.\n\n"
    "/audio <titre ou lien> : télécharger l'audio\n"
    "/id : afficher ton identifiant Telegram\n"
    "/aide : afficher cette aide"
)


async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP)


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(f"Ton identifiant : {update.effective_user.id}")


async def stop_worker(process):
    if process.returncode is not None:
        return
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/PID", str(process.pid), "/T", "/F",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await killer.wait()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    await process.wait()


async def run_worker(url: str, folder: Path) -> dict:
    # Le processus de téléchargement n'a pas besoin du secret Telegram.
    child_env = dict(os.environ)
    child_env.pop("TELEGRAM_BOT_TOKEN", None)
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(ROOT / "worker.py"), url, str(folder),
        env=child_env, start_new_session=(os.name != "nt"),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.wait_for(process.wait(), timeout=JOB_TIMEOUT)
    finally:
        await stop_worker(process)
    result_file = folder / "result.json"
    if process.returncode != 0 or not result_file.is_file():
        raise UserError("Le traitement a échoué. Vérifie les dépendances du bot.")
    result = json.loads(result_file.read_text(encoding="utf-8"))
    if not result.get("ok"):
        raise UserError(result.get("error", "Échec du téléchargement."))
    return result


async def request_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user_id = update.effective_user.id
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await message.reply_text("Ce bot est réservé aux utilisateurs autorisés.")
        return
    value = " ".join(context.args) if message.text.startswith("/") else message.text
    try:
        request = parse_request(value)
    except UserError as exc:
        await message.reply_text(str(exc))
        return
    # Aucune attente entre le contrôle et l'ajout : réservation atomique dans la boucle asyncio.
    if user_id in ACTIVE_USERS:
        await message.reply_text("Ta demande précédente est encore en cours.")
        return
    if len(ACTIVE_USERS) >= MAX_JOBS:
        await message.reply_text("Le bot traite déjà deux demandes. Réessaie dans quelques instants.")
        return
    ACTIVE_USERS.add(user_id)
    status = None
    try:
        status = await message.reply_text("Recherche, téléchargement et conversion en cours…")
        with TemporaryDirectory(prefix="telegram-audio-") as temp:
            folder = Path(temp)
            info = await run_worker(request, folder)
            audio = folder / "audio.mp3"
            if not audio.is_file() or not 0 < audio.stat().st_size <= MAX_AUDIO_BYTES:
                raise UserError("Le fichier audio est absent, vide ou trop volumineux.")
            await status.edit_text("Envoi du MP3…")
            with ExitStack() as files:
                stream = files.enter_context(audio.open("rb"))
                preview = folder / "thumbnail.jpg"
                thumbnail = files.enter_context(preview.open("rb")) if preview.is_file() else None
                await message.reply_audio(
                    audio=stream, filename=audio_filename(info["title"]), title=info["title"],
                    thumbnail=thumbnail,
                    performer=info["performer"], duration=info["duration"],
                    caption=f"{info['title']}\nSource : {info['source_url']}", write_timeout=180, read_timeout=180,
                    connect_timeout=30)
        await status.edit_text(
            "Audio envoyé ✓ — pochette indisponible pour cette vidéo."
            if info.get("cover_embedded") is False else "Audio envoyé ✓")
    except asyncio.TimeoutError:
        if status:
            await status.edit_text("Le traitement a dépassé 5 minutes. Essaie une vidéo plus courte ou réessaie plus tard.")
    except UserError as exc:
        if status:
            await status.edit_text(str(exc))
    except TelegramError:
        LOGGER.warning("Échec de communication Telegram ; état de livraison à vérifier.")
        if status:
            try:
                await status.edit_text("Problème de connexion à Telegram. Vérifie si le MP3 est arrivé avant de réessayer.")
            except TelegramError:
                pass
    finally:
        ACTIVE_USERS.discard(user_id)


async def on_error(update, context):
    # Évite d'écrire les URL de requêtes contenant le token dans les journaux.
    LOGGER.error("Erreur inattendue : %s", type(context.error).__name__)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("Une erreur interne est survenue. Réessaie dans un instant.")
        except TelegramError:
            pass


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token == "COLLER_ICI_LE_TOKEN_BOTFATHER":
        raise SystemExit("Renseigne TELEGRAM_BOT_TOKEN dans le fichier .env.")
    try:
        ALLOWED_USERS.update(int(x.strip()) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip())
    except ValueError:
        raise SystemExit("ALLOWED_USER_IDS doit contenir des identifiants numériques séparés par des virgules.") from None
    for binary in ("ffmpeg", "ffprobe"):
        if not shutil.which(binary):
            raise SystemExit(f"Installe {binary} et ajoute-le au PATH, puis rouvre le terminal.")
    if not (shutil.which("deno") or shutil.which("node")):
        raise SystemExit("Installe Deno (recommandé) ou Node.js, puis rouvre le terminal.")
    app = Application.builder().token(token).concurrent_updates(8).build()
    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler(["start", "aide", "help"], welcome, filters=private))
    app.add_handler(CommandHandler("id", my_id, filters=private))
    app.add_handler(CommandHandler("audio", request_audio, filters=private))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, request_audio))
    app.add_error_handler(on_error)
    print("Bot démarré. Ouvre sa conversation Telegram. Ctrl+C pour arrêter.")
    app.run_polling(allowed_updates=["message"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
