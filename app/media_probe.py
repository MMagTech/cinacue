"""Media inspection helpers.

* ``source_file_exists`` / ``calculate_end_time`` — pure, no external tools.
* ``probe_source`` — runs ``ffprobe`` to read the real source dimensions and
  codecs. The JSON parsing is split into a pure function so it is unit-tested
  without a media file present.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


def source_file_exists(path: str) -> bool:
    """True if the translated container path points at a readable file."""
    return bool(path) and os.path.isfile(path)


def calculate_end_time(start: datetime, runtime_ms: int) -> datetime:
    """End time from a start time and a runtime in milliseconds."""
    if runtime_ms < 0:
        raise ValueError("runtime_ms must be non-negative")
    return start + timedelta(milliseconds=runtime_ms)


class ProbeError(Exception):
    """Raised when the source cannot be probed (missing file, ffprobe error)."""


# Video transfer characteristics that mean HDR (need tonemapping to SDR):
#   smpte2084   = PQ / HDR10 / Dolby Vision
#   arib-std-b67 = HLG
_HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}


@dataclass
class ProbeResult:
    width: Optional[int]
    height: Optional[int]
    video_codec: Optional[str]
    audio_codec: Optional[str]
    container: Optional[str]
    duration_seconds: Optional[float]
    color_transfer: Optional[str] = None
    is_hdr: bool = False


def parse_ffprobe(data: dict) -> ProbeResult:
    """Parse an ``ffprobe -show_streams -show_format`` JSON payload."""
    streams = data.get("streams", []) or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {}) or {}

    w = video.get("width")
    h = video.get("height")
    duration = fmt.get("duration") or video.get("duration")
    transfer = video.get("color_transfer")

    return ProbeResult(
        width=int(w) if w else None,
        height=int(h) if h else None,
        video_codec=video.get("codec_name"),
        audio_codec=audio.get("codec_name"),
        container=fmt.get("format_name"),
        duration_seconds=float(duration) if duration else None,
        color_transfer=transfer,
        is_hdr=transfer in _HDR_TRANSFERS,
    )


def probe_source(path: str, *, ffprobe_bin: str = "ffprobe", timeout: float = 20.0) -> ProbeResult:
    """Run ffprobe on ``path`` and return parsed stream/format info.

    Raises ProbeError if the file is missing or ffprobe fails. The result must
    contain real video dimensions or callers cannot enforce the no-upscale rule.
    """
    if not source_file_exists(path):
        raise ProbeError(f"Source file not found: {path}")

    args = [
        ffprobe_bin,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        path,
    ]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except FileNotFoundError as exc:
        raise ProbeError("ffprobe is not installed") from exc
    except subprocess.CalledProcessError as exc:
        raise ProbeError(f"ffprobe failed: {exc.stderr.strip()}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError("ffprobe timed out") from exc

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError("ffprobe returned invalid JSON") from exc

    result = parse_ffprobe(data)
    if not result.width or not result.height:
        raise ProbeError("ffprobe did not report video dimensions")
    return result
