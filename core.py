"""Validation des demandes, sans dépendance réseau."""
import re
from urllib.parse import parse_qs, urlsplit

MAX_DURATION = 20 * 60
MAX_AUDIO_BYTES = 49_000_000
MAX_VIDEO_BYTES = 49_000_000
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


SOCIAL_HOSTS = {
    "instagram.com": "Instagram", "www.instagram.com": "Instagram",
    "tiktok.com": "TikTok", "www.tiktok.com": "TikTok", "m.tiktok.com": "TikTok",
    "vm.tiktok.com": "TikTok", "vt.tiktok.com": "TikTok",
    "facebook.com": "Facebook", "www.facebook.com": "Facebook",
    "m.facebook.com": "Facebook", "web.facebook.com": "Facebook",
    "fb.watch": "Facebook", "www.fb.watch": "Facebook",
}


def social_url(text: str) -> tuple[str, str, bool]:
    """Valide un lien vidéo social et indique s'il faut résoudre un lien de partage."""
    value = text.strip()
    error = "Envoie le lien d'une vidéo Instagram, TikTok ou Facebook, pas d'un profil, d'un album ou d'un direct."
    try:
        if len(value) > 2048 or re.search(r"[\s\x00-\x1f\x7f\\]", value):
            raise ValueError
        if not re.match(r"(?i)^https?://", value):
            value = "https://" + value
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or url.username is not None or url.password is not None or url.port:
            raise ValueError
        platform = SOCIAL_HOSTS.get(url.hostname)
        path = url.path.rstrip("/")
        if platform == "Instagram":
            match = re.fullmatch(r"/(?:(?!share/)[\w.]+/)?(reels?|p|tv)/([A-Za-z0-9_-]+)", path)
            if match and match[2] != "audio":
                return f"https://www.instagram.com/{match[1]}/{match[2]}/", platform, False
            if re.fullmatch(r"/share/(?:reel|[pv])/([A-Za-z0-9_-]+)", path):
                return f"https://www.instagram.com{path}/", platform, True
        elif platform == "TikTok":
            if url.hostname in {"vm.tiktok.com", "vt.tiktok.com"} and re.fullmatch(r"/[A-Za-z0-9]+", path):
                return f"https://{url.hostname}{path}/", platform, True
            if re.fullmatch(r"/t/[A-Za-z0-9]+", path):
                return f"https://www.tiktok.com{path}/", platform, True
            if re.fullmatch(r"/@[\w.-]+/video/[0-9]+", path):
                return f"https://www.tiktok.com{path}", platform, False
        elif platform == "Facebook":
            if url.hostname in {"fb.watch", "www.fb.watch"} and re.fullmatch(r"/[A-Za-z0-9_-]+", path):
                return f"https://fb.watch{path}/", platform, True
            if re.fullmatch(r"/share/[rv]/[A-Za-z0-9]+", path):
                return f"https://www.facebook.com{path}/", platform, True
            match = re.fullmatch(r"/reel/([0-9]+)", path)
            if match:
                return f"https://www.facebook.com/reel/{match[1]}/", platform, False
            match = re.fullmatch(r"/(?:[\w.-]+/)?videos/(?:[^/]+/)?([0-9]+)", path)
            video_id = match[1] if match else parse_qs(url.query).get("v", [""])[0]
            if (match or path in {"/watch", "/video.php"}) and re.fullmatch(r"[0-9]+", video_id):
                return f"https://www.facebook.com/watch/?v={video_id}", platform, False
        raise ValueError
    except ValueError:
        raise UserError(error) from None


def parse_media_request(text: str, mode: str = "auto") -> tuple[str, str]:
    value = text.strip()
    # Seuls les liens de plateformes explicitement prises en charge deviennent des vidéos.
    try:
        candidate = value if "://" in value else "https://" + value
        is_social = urlsplit(candidate).hostname in SOCIAL_HOSTS
    except ValueError:
        is_social = False
    if mode == "video" or is_social:
        url, _, _ = social_url(value)
        if mode == "audio":
            raise UserError("Pour cette vidéo, envoie simplement le lien ou utilise /video. /audio accepte un titre ou un lien YouTube.")
        return "video", url
    return "audio", parse_request(value)


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
