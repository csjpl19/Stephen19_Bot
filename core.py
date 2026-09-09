"""Validation des demandes, sans dépendance réseau."""
import re
from urllib.parse import parse_qs, urlsplit

MAX_DURATION = 20 * 60
MAX_AUDIO_BYTES = 49_000_000
MAX_SOURCE_BYTES = 80_000_000
MAX_JOBS = 2
JOB_TIMEOUT = 300


class UserError(Exception):
    pass


def audio_filename(title: str) -> str:
    """Nom portable, sans chemin, en conservant les accents du titre."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', " ", title)
    name = " ".join(name.split()).strip(" .")
    # Borne aussi les titres Unicode pour les systèmes limitant les noms en octets.
    name = name.encode("utf-8")[:180].decode("utf-8", errors="ignore").rstrip(" .")
    name = name or "Audio YouTube"
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", name.split(".")[0]):
        name = "_" + name
    return name + ".mp3"


def parse_request(text: str) -> str:
    """Accepte un lien YouTube ou une recherche textuelle bornée."""
    value = text.strip()
    if not value:
        raise UserError("Écris le titre et, si possible, l'artiste, ou envoie un lien YouTube.")
    if re.match(r"(?i)^(https?://|www\.|(?:music\.|m\.)?youtube\.com/|youtu\.be/)", value):
        if not re.match(r"(?i)^https?://", value):
            value = "https://" + value
        return youtube_url(value)
    if len(value) > 200 or "://" in value or any(ord(c) < 32 for c in value):
        raise UserError("Écris un titre de 200 caractères maximum sur une seule ligne, ou un lien YouTube.")
    return value


def youtube_url(text: str) -> str:
    """Reconstruit une URL canonique : aucune URL arbitraire n'est transmise."""
    value = text.strip()
    if len(value) > 2048 or any(c.isspace() for c in value):
        raise UserError("Envoie uniquement un lien YouTube, sans texte autour.")
    try:
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or url.username or url.password or url.port:
            raise ValueError
        host = url.hostname
        parts = url.path.strip("/").split("/")
        if host == "youtu.be" and len(parts) == 1:
            video_id = parts[0]
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            if url.path == "/watch":
                video_id = parse_qs(url.query).get("v", [""])[0]
            elif len(parts) == 2 and parts[0] in {"shorts", "embed", "live"}:
                video_id = parts[1]
            else:
                raise ValueError
        else:
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise ValueError
    except ValueError:
        raise UserError("Lien invalide. Envoie le lien d'une vidéo YouTube, pas d'une chaîne ou d'une playlist.") from None
    return f"https://www.youtube.com/watch?v={video_id}"


def check_info(info: dict) -> None:
    if info.get("_type") in {"playlist", "multi_video"}:
        raise UserError("Les playlists ne sont pas prises en charge.")
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
        raise UserError("Les directs et les vidéos à venir ne sont pas pris en charge.")
    duration = info.get("duration")
    if not isinstance(duration, (int, float)) or not 0 < duration <= MAX_DURATION:
        raise UserError("La vidéo doit avoir une durée connue de 20 minutes maximum.")
