# syntax=docker/dockerfile:1
FROM denoland/deno:bin-2.9.6 AS deno

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DENO_NO_UPDATE_CHECK=1 \
    DENO_NO_PROMPT=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 bot

COPY --from=deno /deno /usr/local/bin/deno
WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install -r requirements.txt \
    && python -m pip check \
    && ffmpeg -version \
    && ffprobe -version \
    && deno --version

# Liste explicite : aucun fichier .env ni secret n'entre dans l'image.
COPY bot.py core.py worker.py reels.py ./
COPY tests/ ./tests/
USER bot
RUN python -m unittest discover -s tests -v

# Le bot interroge Telegram : aucun serveur HTTP ni port public requis.
# Tini transmet SIGTERM à Python pour permettre l'arrêt de la boucle Telegram.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-u", "bot.py"]
