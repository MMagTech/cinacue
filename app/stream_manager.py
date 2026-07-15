"""FFmpeg process manager for the live HLS channel.

Owns exactly one FFmpeg child process at a time and tracks its state. It never
constructs a shell command (arguments are passed as a list) and it cleans up
stale HLS artefacts whenever a movie starts, the stream restarts, or the
channel stops. Restart-on-failure policy lives in the channel controller; this
class provides the mechanism and bookkeeping.

State machine: offline -> starting -> streaming -> stopping -> offline, with
error as a terminal-until-restarted state.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Deque, List, Optional, Tuple

from . import encoding
from .config import EncoderPreset, MaxResolution
from .logging_config import get_logger
from .media_probe import ProbeError, find_sidecar_subtitle, probe_source

log = get_logger("stream")

PLAYLIST_NAME = "channel.m3u8"
SEGMENT_PATTERN = "segment-%06d.ts"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class StreamState(str, Enum):
    offline = "offline"
    starting = "starting"
    streaming = "streaming"
    stopping = "stopping"
    error = "error"


class StreamManager:
    def __init__(
        self,
        stream_dir,
        *,
        ffmpeg_bin: str = "ffmpeg",
        ffprobe_bin: str = "ffprobe",
        max_retries: int = 3,
    ) -> None:
        self.stream_dir = Path(stream_dir)
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        self.max_retries = max_retries

        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen] = None
        self._log_thread: Optional[threading.Thread] = None
        self._logs: Deque[str] = deque(maxlen=300)

        self.state: StreamState = StreamState.offline
        self.error: Optional[str] = None
        self.current_movie_id: Optional[int] = None
        self.current_title: Optional[str] = None
        self.current_rating_key: Optional[str] = None
        self.source_dims: Optional[Tuple[int, int]] = None
        self.source_codec: Optional[str] = None
        self.output_dims: Optional[Tuple[int, int]] = None
        self.video_bitrate_kbps: Optional[int] = None
        self.encoder: Optional[str] = None
        self.subtitles_available: bool = False
        self.started_at: Optional[datetime] = None
        self.start_offset_seconds: float = 0.0
        self.retry_count: int = 0
        self.last_exit_code: Optional[int] = None

    # --- paths --------------------------------------------------------------
    @property
    def playlist_path(self) -> Path:
        return self.stream_dir / PLAYLIST_NAME

    @property
    def segment_pattern(self) -> Path:
        return self.stream_dir / SEGMENT_PATTERN

    # --- logging ------------------------------------------------------------
    def _log(self, msg: str) -> None:
        ts = _utcnow().strftime("%H:%M:%S")
        self._logs.append(f"{ts} {msg}")

    def recent_logs(self, n: int = 60) -> List[str]:
        return list(self._logs)[-n:]

    # --- housekeeping -------------------------------------------------------
    def clean_stream_dir(self) -> None:
        self.stream_dir.mkdir(parents=True, exist_ok=True)
        for pattern in ("*.ts", "*.m3u8", "*.vtt"):
            for f in self.stream_dir.glob(pattern):
                try:
                    f.unlink()
                except OSError:
                    pass

    def kill_orphans(self) -> None:
        """Best-effort: kill leftover ffmpeg processes writing to our playlist.

        Scans /proc for ffmpeg command lines that reference our stream dir,
        excluding our own child. Safe no-op on non-Linux hosts.
        """
        our_pid = self._proc.pid if self._proc else -1
        target = str(self.stream_dir)
        proc_root = Path("/proc")
        if not proc_root.exists():
            return
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid == our_pid or pid == os.getpid():
                continue
            try:
                cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode(
                    "utf-8", "ignore"
                )
            except OSError:
                continue
            if "ffmpeg" in cmdline and target in cmdline:
                try:
                    os.kill(pid, 15)
                    self._log(f"killed orphan ffmpeg pid={pid}")
                except OSError:
                    pass

    # --- process ------------------------------------------------------------
    def is_process_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def ffmpeg_pid(self) -> Optional[int]:
        return self._proc.pid if self.is_process_alive() else None

    def _start_log_thread(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return

        def reader() -> None:
            try:
                for line in proc.stdout:  # type: ignore[union-attr]
                    self._logs.append(line.rstrip())
            except Exception:  # pragma: no cover - stream closed
                pass

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        self._log_thread = t

    def _terminate_process(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            except Exception:  # pragma: no cover
                pass
        self._proc = None

    def reset_retry(self) -> None:
        self.retry_count = 0

    def _fail(self, msg: str) -> None:
        self.error = msg
        self.state = StreamState.error
        self._log(f"ERROR: {msg}")
        log.error("stream error: %s", msg)
        self._terminate_process()

    def _reset_current(self) -> None:
        self.current_movie_id = None
        self.current_title = None
        self.current_rating_key = None
        self.source_dims = None
        self.source_codec = None
        self.output_dims = None
        self.video_bitrate_kbps = None
        self.encoder = None
        self.subtitles_available = False
        self.started_at = None
        self.start_offset_seconds = 0.0

    # --- public control -----------------------------------------------------
    def start(
        self,
        *,
        movie_id: int,
        title: str,
        rating_key: Optional[str],
        source_path: str,
        offset_seconds: float,
        maximum_resolution: MaxResolution,
        video_bitrate_kbps: int,
        audio_bitrate_kbps: int,
        encoder: str,
        preset: EncoderPreset,
    ) -> bool:
        """Probe the source, enforce no-upscale, and launch FFmpeg.

        Returns True on success. On failure the manager enters the ``error``
        state with a message and no process running.
        """
        with self._lock:
            self._terminate_process()
            self.state = StreamState.starting
            self.error = None
            self._log(f"starting '{title}' at offset {int(offset_seconds)}s")

            try:
                probe = probe_source(source_path, ffprobe_bin=self.ffprobe_bin)
            except ProbeError as exc:
                self._fail(f"probe failed for '{title}': {exc}")
                return False

            dims = encoding.calculate_output_dimensions(
                probe.width, probe.height, maximum_resolution
            )
            subtitle_path = find_sidecar_subtitle(source_path)
            self._log(
                f"source {probe.width}x{probe.height} {probe.video_codec} -> "
                f"output {dims.output_width}x{dims.output_height} "
                f"({'no upscale' if dims.upscaled_blocked else 'scaled'})"
                + (f" [HDR {probe.color_transfer} -> SDR tonemap]" if probe.is_hdr else "")
                + (" [subtitles]" if subtitle_path else "")
            )

            self.clean_stream_dir()
            args = encoding.build_ffmpeg_args(
                source_path=source_path,
                output_playlist=str(self.playlist_path),
                dims=dims,
                video_bitrate_kbps=video_bitrate_kbps,
                audio_bitrate_kbps=audio_bitrate_kbps,
                encoder=encoder,
                preset=preset,
                start_offset_seconds=offset_seconds,
                segment_pattern=str(self.segment_pattern),
                is_hdr=probe.is_hdr,
                subtitle_path=subtitle_path,
                ffmpeg_bin=self.ffmpeg_bin,
            )

            try:
                self._proc = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except Exception as exc:  # pragma: no cover - spawn failure
                self._fail(f"failed to launch ffmpeg: {exc}")
                return False

            self._start_log_thread()

            self.state = StreamState.streaming
            self.current_movie_id = movie_id
            self.current_title = title
            self.current_rating_key = rating_key
            self.source_dims = (probe.width, probe.height)
            self.source_codec = probe.video_codec
            self.output_dims = (dims.output_width, dims.output_height)
            self.video_bitrate_kbps = video_bitrate_kbps
            self.encoder = encoder
            self.subtitles_available = subtitle_path is not None
            self.started_at = _utcnow()
            self.start_offset_seconds = offset_seconds
            self._log(f"ffmpeg pid={self._proc.pid} running")
            log.info("stream start '%s' %sx%s->%sx%s pid=%s offset=%ss enc=%s",
                     title, probe.width, probe.height, dims.output_width,
                     dims.output_height, self._proc.pid, int(offset_seconds), encoder)
            return True

    def notice_exit(self) -> None:
        """Record that the ffmpeg process exited (called by the controller)."""
        code = self._proc.poll() if self._proc else None
        self.last_exit_code = code
        self._log(f"ffmpeg exited (code={code})")
        log.warning("ffmpeg exited code=%s", code)

    def stop(self) -> None:
        with self._lock:
            if self.state == StreamState.offline and not self.is_process_alive():
                return
            self.state = StreamState.stopping
            self._terminate_process()
            self.clean_stream_dir()
            self._reset_current()
            self.retry_count = 0
            self.state = StreamState.offline
            self._log("stopped")
            log.info("stream stopped")

    # --- introspection ------------------------------------------------------
    def status(self) -> dict:
        return {
            "state": self.state.value,
            "error": self.error,
            "current_movie_id": self.current_movie_id,
            "current_title": self.current_title,
            "source_resolution": (
                f"{self.source_dims[0]}x{self.source_dims[1]}"
                if self.source_dims
                else None
            ),
            "source_codec": self.source_codec,
            "output_resolution": (
                f"{self.output_dims[0]}x{self.output_dims[1]}"
                if self.output_dims
                else None
            ),
            "video_bitrate_kbps": self.video_bitrate_kbps,
            "encoder": self.encoder,
            "subtitles_available": self.subtitles_available,
            "ffmpeg_pid": self.ffmpeg_pid,
            "ffmpeg_alive": self.is_process_alive(),
            "start_offset_seconds": int(self.start_offset_seconds),
            "started_at": self.started_at.isoformat() + "Z" if self.started_at else None,
            "retry_count": self.retry_count,
            "recent_logs": self.recent_logs(40),
        }
