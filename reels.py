"""Téléchargement des vidéos sociales publiques et préparation pour Telegram."""
import json
import math
import re
import subprocess
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener

from yt_dlp import YoutubeDL

from core import MAX_SOURCE_BYTES, MAX_VIDEO_BYTES, UserError, check_info, social_url
from worker import QuietLogger, make_jpeg, run_ffmpeg


class SocialRedirectHandler(HTTPRedirectHandler):
    max_redirections = 5

    def __init__(self, platform):
        self.platform = platform

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target, platform, _ = social_url(urljoin(req.full_url, newurl))
        if platform != self.platform:
            raise UserError("Le lien de partage redirige vers une autre plateforme. Envoie le lien direct de la vidéo.")
        return super().redirect_request(req, fp, code, msg, headers, target)


def resolve_social_url(value: str) -> tuple[str, str]:
    url, platform, shortened = social_url(value)
    if shortened:
        opener = build_opener(SocialRedirectHandler(platform))
        try:
            with opener.open(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as response:
                url, resolved_platform, shortened = social_url(response.geturl())
            if resolved_platform != platform or shortened:
                raise UserError("Ce lien de partage n'a pas pu être résolu. Envoie le lien direct de la vidéo.")
        except (URLError, TimeoutError):
            raise UserError("Impossible d'ouvrir ce lien de partage. Essaie le lien direct de la vidéo.") from None
    return url, platform


def check_reel_info(info: dict, *, incomplete=False):
    if incomplete:
        return None
    # Certaines plateformes ne fournissent la durée qu'après téléchargement.
    check_info({**info, "duration": info.get("duration") if info.get("duration") is not None else 1})
    if info.get("has_drm"):
        raise UserError("Cette vidéo est protégée et ne peut pas être téléchargée.")
    return None


def without_watermarked_formats(context: dict) -> dict:
    formats = []
    for fmt in context.get("formats", []):
        note = str(fmt.get("format_note") or "").lower()
        marked = fmt.get("has_watermark") or re.search(r"\bwatermarked\b", note)
        if not marked:
            formats.append(fmt)
    if not any(f.get("vcodec") != "none" for f in formats):
        raise UserError("Aucune version vidéo sans filigrane signalé n'est disponible pour ce lien.")
    return {**context, "formats": formats}


def probe_media(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        check=True, capture_output=True, encoding="utf-8", timeout=30)
    return json.loads(result.stdout)


def prepare_video(source: Path, destination: Path) -> dict:
    metadata = probe_media(source)
    streams = metadata.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise UserError("Ce lien ne contient pas de vidéo téléchargeable.")
    try:
        duration = float(metadata.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0
    check_info({"duration": duration})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    compatible = (video.get("codec_name") == "h264" and video.get("pix_fmt") == "yuv420p"
                  and (not audio or audio.get("codec_name") == "aac")
                  and source.stat().st_size < MAX_VIDEO_BYTES - 500_000
                  and not video.get("tags", {}).get("rotate")
                  and not any(s.get("rotation") for s in video.get("side_data_list", [])))
    arguments = ["-i", str(source), "-map", f"0:{video['index']}", "-map", "0:a:0?",
                 "-map_metadata", "-1", "-map_chapters", "-1"]
    if compatible:
        arguments += ["-c", "copy"]
    else:
        # Garde une marge pour l'audio, le conteneur et les variations d'encodage.
        bitrate = min(2_500_000, int(MAX_VIDEO_BYTES * 0.92 * 8 / duration) - 128_000)
        if bitrate < 64_000:
            raise UserError("Impossible de préparer cette vidéo sous 49 Mo. Essaie une vidéo plus courte.")
        arguments += ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                      "-vf", "scale='min(iw,1280)':'min(ih,1280)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
                      "-b:v", str(bitrate), "-maxrate", str(bitrate), "-bufsize", str(bitrate * 2),
                      "-c:a", "aac", "-b:a", "128k"]
    # Faststart permet la lecture dans Telegram avant la fin du téléchargement.
    run_ffmpeg([*arguments, "-movflags", "+faststart", str(destination)], timeout=180)
    if not destination.is_file() or not 0 < destination.stat().st_size <= MAX_VIDEO_BYTES:
        raise UserError("La vidéo dépasse 49 Mo après préparation. Essaie une vidéo plus courte.")
    final = probe_media(destination)
    stream = next(s for s in final["streams"] if s["codec_type"] == "video")
    final_duration = float(final["format"]["duration"])
    check_info({"duration": final_duration})
    return {"duration": math.ceil(final_duration), "width": stream["width"], "height": stream["height"]}


def download_reel(request: str, folder: Path) -> dict:
    url, platform = resolve_social_url(request)
    downloaded = {}

    def limit_progress(data):
        key = data.get("filename", "source")
        downloaded[key] = max(downloaded.get(key, 0), data.get("downloaded_bytes", 0))
        if sum(downloaded.values()) > MAX_SOURCE_BYTES:
            raise UserError("La vidéo source dépasse la limite de téléchargement de 80 Mo.")

    # Le sélecteur yt-dlp conserve la gestion des pistes vidéo/audio séparées.
    selector = None

    def select_formats(context):
        yield from selector(without_watermarked_formats(context))

    options = {
        "outtmpl": str(folder / "source.%(ext)s"), "format": select_formats,
        "format_sort": ["res:720", "vcodec:h264", "acodec:aac"],
        "merge_output_format": "mkv", "noplaylist": True,
        "extract_flat": "in_playlist", "playlistend": 2,
        "allowed_extractors": ["instagram$", "TikTok$", "facebook$", "facebook:reel$"],
        "quiet": True, "no_warnings": True, "logger": QuietLogger(),
        "socket_timeout": 20, "retries": 2, "fragment_retries": 2,
        "concurrent_fragment_downloads": 1, "max_filesize": MAX_SOURCE_BYTES,
        "progress_hooks": [limit_progress], "match_filter": check_reel_info,
    }
    with YoutubeDL(options) as ydl:
        selector = ydl.build_format_selector("bv*+ba/b/bv")
        info = ydl.extract_info(url, download=False)
        if not info:
            raise UserError("Cette vidéo n'a pas pu être trouvée.")
        check_reel_info(info)
        # La validation précède tout téléchargement de média, y compris les albums.
        info = ydl.process_ie_result(info, download=True)
    candidates = [p for p in folder.glob("source.*")
                  if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".flv", ".ts"}]
    if len(candidates) != 1:
        raise UserError("Aucune vidéo complète obtenue : contenu inaccessible ou source trop volumineuse.")
    if candidates[0].stat().st_size > MAX_SOURCE_BYTES:
        raise UserError("La vidéo source dépasse la limite de téléchargement de 80 Mo.")
    video = folder / "video.mp4"
    dimensions = prepare_video(candidates[0], video)
    preview = folder / "thumbnail.jpg"
    if make_jpeg(video, preview, 320) and preview.stat().st_size >= 200_000:
        preview.unlink()
    return {"ok": True, "kind": "video", "title": str(info.get("title") or f"Vidéo {platform}")[:200],
            "platform": platform, **dimensions}
