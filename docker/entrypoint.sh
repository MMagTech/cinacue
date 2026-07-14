#!/usr/bin/env bash
# Container entrypoint: prepare runtime dirs, report NVENC availability, exec.
set -euo pipefail

CONFIG_DIR="${CONFIG_DIR:-/config}"
STREAM_DIR="${STREAM_DIR:-/stream}"

mkdir -p "$CONFIG_DIR" "$STREAM_DIR"

echo "[entrypoint] Movie Channel starting"
echo "[entrypoint] CONFIG_DIR=$CONFIG_DIR STREAM_DIR=$STREAM_DIR TZ=${TZ:-unset}"

# Report — do not fail. NVENC verification is surfaced to the admin via the
# diagnostics endpoint; the app must not silently fall back to CPU encoding.
if command -v ffmpeg >/dev/null 2>&1; then
  if ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_nvenc; then
    echo "[entrypoint] ffmpeg present; h264_nvenc encoder listed."
  else
    echo "[entrypoint] WARNING: ffmpeg present but h264_nvenc not listed."
  fi
else
  echo "[entrypoint] WARNING: ffmpeg not found on PATH."
fi

# Clean any stale HLS segments left from a previous run.
rm -f "$STREAM_DIR"/*.ts "$STREAM_DIR"/*.m3u8 2>/dev/null || true

exec "$@"
