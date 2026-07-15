# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Movie Channel — multi-stage image
#
#   Stage 1: build the React/Vite frontend into app/static
#   Stage 2: runtime on an NVIDIA CUDA base with FFmpeg (NVENC/NVDEC) + Python
# ---------------------------------------------------------------------------

# --- Stage 1: frontend build ----------------------------------------------
FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build
# Output lands in /app/static (outDir "../app/static" relative to /build).


# --- Stage 2: runtime ------------------------------------------------------
# CUDA runtime base so the NVIDIA container toolkit can expose the GPU. FFmpeg
# is installed from the distro; it links against the NVIDIA driver libraries
# injected at runtime by `--gpus` / `runtime: nvidia`.
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CONFIG_DIR=/config \
    STREAM_DIR=/stream

# jellyfin-ffmpeg: a purpose-built ffmpeg for hardware transcoding with full
# GPU HDR tonemapping (tonemap_cuda) wired up — used instead of the distro
# ffmpeg (4.4, no tonemap_cuda). Symlinked so the app's `ffmpeg`/`ffprobe`
# calls resolve to it. Kept on the same CUDA/Ubuntu base (no driver change).
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        tzdata \
        curl \
        gosu \
        gnupg \
        ca-certificates \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://repo.jellyfin.org/jellyfin_team.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/jellyfin.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/jellyfin.gpg] https://repo.jellyfin.org/ubuntu jammy main" \
        > /etc/apt/sources.list.d/jellyfin.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends jellyfin-ffmpeg7 \
    && ln -sf /usr/lib/jellyfin-ffmpeg/ffmpeg /usr/local/bin/ffmpeg \
    && ln -sf /usr/lib/jellyfin-ffmpeg/ffprobe /usr/local/bin/ffprobe \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

# Backend source.
COPY app/ ./app/
# Compiled frontend from stage 1.
COPY --from=frontend /app/static ./app/static
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Non-root user. The entrypoint runs as root only long enough to fix ownership
# of the bind-mounted /config and /stream (Unraid appdata / RAM disk can be
# owned by any uid), then drops to this user via gosu to run the app.
RUN useradd --system --create-home --uid 10001 appuser \
    && mkdir -p /config /stream \
    && chown -R appuser:appuser /app /config /stream

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# --proxy-headers + --forwarded-allow-ips lets uvicorn trust X-Forwarded-For
# from the reverse proxy, so per-IP rate limiting and logs see the real client
# (only the proxy talks to this container on the compose network).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
