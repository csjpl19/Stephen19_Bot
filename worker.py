"""Un processus isolé par demande ; résultat dans result.json."""
import json
import subprocess
import sys
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from core import MAX_AUDIO_BYTES, MAX_SOURCE_BYTES, UserError, check_info, parse_media_request, parse_request, youtube_url


class QuietLogger:
    def debug(self, message):
        pass

    info = warning = error = debug


def resolve_video(request: str) -> str:
    value = parse_request(request)
    if value.startswith("https://www.youtube.com/watch?v="):
        return value
    # Une recherche limitée à un résultat ; aucune URL fournie par un résultat
    # n'est suivie : seule son identité YouTube est utilisée.
    with YoutubeDL({"quiet": True, "no_warnings": True, "logger": QuietLogger(),
                    "extract_flat": True, "socket_timeout": 20, "retries": 2,
                    "js_runtimes": {"deno": {}, "node": {}}}) as search:
        results = search.extract_info(f"ytsearch1:{value}", download=False)
    entries = list((results or {}).get("entries") or [])
    if not entries or not entries[0]:
        raise UserError("Aucun résultat trouvé. Essaie avec le titre et le nom de l'artiste.")
    return youtube_url(f"https://www.youtube.com/watch?v={entries[0].get('id', '')}")


def run_ffmpeg(arguments: list[str], timeout: int = 60) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *arguments],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout)


def make_jpeg(source: Path, destination: Path, size: int) -> bool:
    """Normalise aussi les miniatures WebP en JPEG lisible par les lecteurs MP3."""
    try:
        run_ffmpeg([
            "-i", str(source), "-map", "0:v:0", "-frames:v", "1",
            "-vf", f"scale={size}:{size}:force_original_aspect_ratio=decrease,setsar=1",
            "-c:v", "mjpeg", "-pix_fmt", "yuvj420p", "-q:v", "3", str(destination)])
        if destination.is_file() and destination.stat().st_size > 0:
            return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    destination.unlink(missing_ok=True)
    return False


def add_metadata(audio: Path, info: dict, title: str, performer: str) -> bool:
    """Intègre les tags et la pochette au MP3, sans réencoder l'audio."""
    folder = audio.parent
    cover = folder / "cover.jpg"
    has_cover = False
    for thumbnail in reversed(info.get("thumbnails") or []):
        path = thumbnail.get("filepath")
        if path and Path(path).is_file() and make_jpeg(Path(path), cover, 640):
            has_cover = True
            break
    if has_cover:
        preview = folder / "thumbnail.jpg"
        if make_jpeg(cover, preview, 320) and preview.stat().st_size >= 200_000:
            preview.unlink()

    tagged = folder / "tagged.mp3"
    arguments = ["-i", str(audio)]
    if has_cover:
        arguments += ["-i", str(cover)]
    arguments += ["-map", "0:a:0", "-map_metadata", "-1", "-c:a", "copy",
                  "-id3v2_version", "3", "-metadata", f"title={title}",
                  "-metadata", f"artist={performer}"]
    if info.get("album"):
        arguments += ["-metadata", f"album={info['album']}"]
    if has_cover:
        arguments += ["-map", "1:v:0", "-c:v", "copy", "-disposition:v:0", "attached_pic",
                      "-metadata:s:v:0", "title=Album cover",
                      "-metadata:s:v:0", "comment=Cover (front)"]
    run_ffmpeg([*arguments, str(tagged)])
    tagged.replace(audio)
    return has_cover


def download(request: str, folder: Path) -> dict:
    url = resolve_video(request)
    def limit_progress(data):
        if data.get("downloaded_bytes", 0) > MAX_SOURCE_BYTES:
            raise UserError("Le fichier source est trop volumineux.")

    def limit_video(info, *, incomplete=False):
        if not incomplete:
            check_info(info)
        return None

    options = {
        "format": "bestaudio[filesize<80000000]/bestaudio",
        "outtmpl": str(folder / "audio.%(ext)s"),
        "noplaylist": True,
        "writethumbnail": True,
        "quiet": True,
        "no_warnings": True,
        "logger": QuietLogger(),
        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 2,
        "concurrent_fragment_downloads": 1,
        "max_filesize": MAX_SOURCE_BYTES,
        "progress_hooks": [limit_progress],
        "match_filter": limit_video,
        "js_runtimes": {"deno": {}, "node": {}},
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(youtube_url(url), download=True)
    if not info:
        raise UserError("Cette vidéo n'a pas pu être téléchargée.")
    check_info(info)
    audio = folder / "audio.mp3"
    if not audio.is_file() or audio.stat().st_size == 0:
        raise UserError("Aucun audio obtenu : vidéo inaccessible ou fichier source trop volumineux.")
    title = str(info.get("track") or info.get("title") or "Audio YouTube")[:200]
    performer = str(info.get("artist") or info.get("uploader") or "YouTube")[:200]
    has_cover = add_metadata(audio, info, title, performer)
    if audio.stat().st_size > MAX_AUDIO_BYTES:
        raise UserError("Le MP3 dépasse la limite du bot : 49 Mo.")
    return {"ok": True, "source_url": url, "title": title, "performer": performer,
            "duration": int(info["duration"]), "cover_embedded": has_cover}


def main():
    folder = Path(sys.argv[2]).resolve()
    kind = "audio"
    try:
        kind, request = parse_media_request(sys.argv[1])
        if kind == "video":
            from reels import download_reel
            result = download_reel(request, folder)
        else:
            result = download(request, folder)
    except UserError as exc:
        result = {"ok": False, "error": str(exc)}
    except DownloadError:
        result = {"ok": False, "error": (
            "La plateforme refuse le téléchargement ou cette vidéo est inaccessible. Utilise un lien public direct. Les contenus privés, supprimés ou nécessitant une connexion ne sont pas pris en charge."
            if kind == "video" else
            "YouTube refuse le téléchargement ou la vidéo est inaccessible. Essaie un autre lien. Si cela arrive pour tous les liens, mets yt-dlp à jour et vérifie Deno et FFmpeg.")}
    except Exception as exc:
        result = {"ok": False, "error": "Échec du traitement du fichier. Vérifie FFmpeg et les dépendances.", "error_type": type(exc).__name__}
    (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
