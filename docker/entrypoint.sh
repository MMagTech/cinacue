#!/usr/bin/env bash
# Container entrypoint: prepare runtime dirs, report NVENC availability, exec.
set -euo pipefail

CONFIG_DIR="${CONFIG_DIR:-/config}"
STREAM_DIR="${STREAM_DIR:-/stream}"

mkdir -p "$CONFIG_DIR" "$STREAM_DIR"

echo "[entrypoint] Movie Channel starting"
echo "[entrypoint] CONFIG_DIR=$CONFIG_DIR STREAM_DIR=$STREAM_DIR TZ=${TZ:-unset}"

# The bind-mounted /config (Unraid appdata) and /stream (RAM disk) can be owned
# by any uid on the host. When started as root, take ownership so the
# unprivileged appuser can write, then re-exec the app as appuser via gosu.
APP_USER="appuser"
if [ "$(id -u)" = "0" ]; then
  chown "$APP_USER:$APP_USER" "$CONFIG_DIR" "$STREAM_DIR" 2>/dev/null || true
fi

# Report — do not fail. NVENC verification is surfaced to the admin via the
# diagnostics endpoint; the app must not silently fall back to CPU encoding.
# Capture the encoder list into a variable and match with `case` rather than
# piping into `grep -q`: under `set -o pipefail`, grep -q closes the pipe as
# soon as it matches, ffmpeg dies with SIGPIPE, and the pipeline reports
# failure — which produced a false "not listed" warning even though it works.
if command -v ffmpeg >/dev/null 2>&1; then
  encoders="$(ffmpeg -hide_banner -encoders 2>/dev/null || true)"
  case "$encoders" in
    *h264_nvenc*)
      echo "[entrypoint] ffmpeg present; h264_nvenc encoder listed." ;;
    *)
      echo "[entrypoint] WARNING: ffmpeg present but h264_nvenc not listed." ;;
  esac
else
  echo "[entrypoint] WARNING: ffmpeg not found on PATH."
fi

# Clean any stale HLS segments left from a previous run.
rm -f "$STREAM_DIR"/*.ts "$STREAM_DIR"/*.m3u8 2>/dev/null || true

# Drop privileges to appuser when we started as root; otherwise exec directly
# (e.g. when the container is already run with a non-root `user:`).
if [ "$(id -u)" = "0" ]; then
  exec gosu "$APP_USER" "$@"
fi
exec "$@"
