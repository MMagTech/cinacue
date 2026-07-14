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

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        ffmpeg \
        tzdata \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Backend source.
COPY app/ ./app/
# Compiled frontend from stage 1.
COPY --from=frontend /app/static ./app/static
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Non-root user. /config and /stream are created and chowned; they are usually
# bind-mounted at runtime (appdata + RAM disk).
RUN useradd --system --create-home --uid 10001 appuser \
    && mkdir -p /config /stream \
    && chown -R appuser:appuser /app /config /stream

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
