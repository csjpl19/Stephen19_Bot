"""Bot Telegram : musique YouTube et vidéos sociales. Lancer : python bot.py."""
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

from core import JOB_TIMEOUT, MAX_AUDIO_BYTES, MAX_VIDEO_BYTES, MAX_JOBS, UserError, audio_filename, parse_media_request

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
ACTIVE_USERS: set[int] = set()
ALLOWED_USERS: set[int] = set()
LOGGER = logging.getLogger("musicbot")
HELP = (
    "Bienvenue — votre assistant musique et vidéo.\n\n"
    "MUSIQUE\n"
    "Envoyez le titre d'un morceau avec son artiste, ou un lien YouTube. "
    "Vous recevrez un MP3 à 192 kbit/s, nommé d'après le morceau, avec son titre, "
    "son artiste et sa pochette lorsqu'elle est disponible. "
    "Une recherche par titre sélectionne le premier résultat YouTube.\n\n"
    "REELS ET VIDÉOS\n"
    "Envoyez un lien public Instagram, TikTok ou Facebook. "
    "Vous recevrez la vidéo en MP4, lisible et téléchargeable directement dans Telegram, "
    "sans carte de lien de la plateforme dans la réponse. "
    "Les formats signalés avec filigrane sont écartés ; un logo déjà incrusté dans l'image peut rester.\n\n"
    "UTILISATION\n"
    "• Un titre ou un lien suffit : le format est choisi automatiquement.\n"
    "• /audio <titre ou lien YouTube> : recevoir un MP3.\n"
    "• /video <lien Instagram, TikTok ou Facebook> : recevoir une vidéo.\n"
    "• /aide : retrouver ces instructions.\n"
    "• /id : afficher votre identifiant Telegram.\n\n"
    "LIMITES\n"
    "Une demande à la fois par personne, 20 minutes et 49 Mo maximum par fichier. "
    "Les vidéos peuvent être compressées. Les playlists, albums, directs et contenus privés "
    "ne sont pas pris en charge. La disponibilité dépend de chaque plateforme.\n\n"
    "Utilisez ce service pour les contenus dont vous êtes autorisé à télécharger une copie."
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
    await request_media(update, context, mode="audio")


async def request_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await request_media(update, context, mode="video")


async def request_media(update: Update, context: ContextTypes.DEFAULT_TYPE, mode="auto"):
    message = update.effective_message
    user_id = update.effective_user.id
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await message.reply_text("Ce bot est réservé aux utilisateurs autorisés.")
        return
    value = " ".join(context.args) if message.text.startswith("/") else message.text
    try:
        kind, request = parse_media_request(value, mode)
    except UserError as exc:
        await message.reply_text(str(exc))
        return
    # Aucune attente entre le contrôle et l'ajout : réservation atomique dans la boucle asyncio.
    if user_id in ACTIVE_USERS:
        await message.reply_text("Ta demande précédente est encore en cours.")
        return
    if len(ACTIVE_USERS) >= MAX_JOBS:
        await message.reply_text("Le bot a atteint sa capacité de traitement. Réessaie dans quelques instants.")
        return
    ACTIVE_USERS.add(user_id)
    status = None
    try:
        status = await message.reply_text(
            "Téléchargement et préparation de la vidéo en cours…" if kind == "video"
            else "Recherche, téléchargement et conversion en cours…")
        with TemporaryDirectory(prefix="telegram-media-") as temp:
            folder = Path(temp)
            info = await run_worker(request, folder)
            media = folder / ("video.mp4" if kind == "video" else "audio.mp3")
            limit = MAX_VIDEO_BYTES if kind == "video" else MAX_AUDIO_BYTES
            if not media.is_file() or not 0 < media.stat().st_size <= limit:
                raise UserError("Le fichier est absent, vide ou trop volumineux.")
            await status.edit_text("Envoi de la vidéo…" if kind == "video" else "Envoi du MP3…")
            with ExitStack() as files:
                stream = files.enter_context(media.open("rb"))
                preview = folder / "thumbnail.jpg"
                thumbnail = files.enter_context(preview.open("rb")) if preview.is_file() else None
                if kind == "video":
                    await message.reply_video(
                        video=stream, filename=audio_filename(info["title"])[:-4] + ".mp4",
                        thumbnail=thumbnail, duration=info["duration"],
                        width=info["width"], height=info["height"], supports_streaming=True,
                        do_quote=False, write_timeout=180, read_timeout=180, connect_timeout=30)
                else:
                    await message.reply_audio(
                        audio=stream, filename=audio_filename(info["title"]), title=info["title"],
                        thumbnail=thumbnail,
                        performer=info["performer"], duration=info["duration"],
                        caption=f"{info['title']}\nSource : {info['source_url']}", write_timeout=180, read_timeout=180,
                        connect_timeout=30)
        await status.edit_text(
            "Vidéo envoyée ✓" if kind == "video" else
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
                await status.edit_text("Problème de connexion à Telegram. Vérifie si le fichier est arrivé avant de réessayer.")
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
    global MAX_JOBS
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token == "COLLER_ICI_LE_TOKEN_BOTFATHER":
        raise SystemExit("Renseigne TELEGRAM_BOT_TOKEN dans les variables de l'hébergeur ou dans le fichier .env local.")
    try:
        MAX_JOBS = int(os.getenv("MAX_JOBS", "2"))
        if MAX_JOBS not in {1, 2}:
            raise ValueError
    except ValueError:
        raise SystemExit("MAX_JOBS doit valoir 1 ou 2.") from None
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
    app.add_handler(CommandHandler("video", request_video, filters=private))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, request_media))
    app.add_error_handler(on_error)
    print("Bot démarré. Ouvre sa conversation Telegram. Ctrl+C pour arrêter.")
    app.run_polling(allowed_updates=["message"], drop_pending_updates=False, bootstrap_retries=5)


if __name__ == "__main__":
    main()
