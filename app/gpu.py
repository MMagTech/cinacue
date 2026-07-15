"""Best-effort live GPU stats via nvidia-smi (name + encoder utilization).

Cached briefly so status polling never spawns nvidia-smi on every request, and
degrades silently to ``None`` when there's no GPU or nvidia-smi — it must never
raise into the status endpoint.
"""
from __future__ import annotations

import subprocess
import time
from typing import Optional, TypedDict


class GpuStats(TypedDict):
    name: Optional[str]
    encode_percent: Optional[int]


_NONE: GpuStats = {"name": None, "encode_percent": None}
_cache: GpuStats = dict(_NONE)  # type: ignore[assignment]
_cache_at: float = 0.0
_TTL = 4.0


def gpu_stats() -> GpuStats:
    """GPU model name and NVENC encoder utilization (%), cached for a few seconds."""
    global _cache, _cache_at
    now = time.monotonic()
    if now - _cache_at < _TTL:
        return _cache
    _cache_at = now

    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.encoder",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        _cache = dict(_NONE)  # type: ignore[assignment]
        return _cache

    if proc.returncode != 0 or not proc.stdout.strip():
        _cache = dict(_NONE)  # type: ignore[assignment]
        return _cache

    parts = [p.strip() for p in proc.stdout.strip().splitlines()[0].split(",")]
    name = parts[0] if parts and parts[0] else None
    encode: Optional[int] = None
    if len(parts) > 1:
        try:
            encode = int(parts[1])
        except ValueError:
            encode = None
    _cache = {"name": name, "encode_percent": encode}
    return _cache
