"""Stream manager tests.

Unit tests for state handling plus a real integration test that runs a genuine
(software) FFmpeg HLS encode to prove the process management and HLS output
mechanics — NVENC is the production encoder but cannot be exercised here.
"""
from __future__ import annotations

import shutil
import subprocess
import time

import pytest

from app.config import EncoderPreset, MaxResolution
from app.stream_manager import StreamManager, StreamState

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


# --- Unit -----------------------------------------------------------------
def test_missing_source_sets_error(tmp_path):
    mgr = StreamManager(tmp_path / "stream")
    ok = mgr.start(
        movie_id=1,
        title="Ghost",
        rating_key="1",
        source_path=str(tmp_path / "nope.mkv"),
        offset_seconds=0,
        maximum_resolution=MaxResolution.p1080,
        video_bitrate_kbps=4000,
        audio_bitrate_kbps=128,
        encoder="libx264",
        preset=EncoderPreset.fast,
    )
    assert ok is False
    assert mgr.state == StreamState.error
    assert mgr.error and "probe failed" in mgr.error


def test_stop_from_offline_is_noop(tmp_path):
    mgr = StreamManager(tmp_path / "stream")
    mgr.stop()
    assert mgr.state == StreamState.offline


def test_status_shape(tmp_path):
    mgr = StreamManager(tmp_path / "stream")
    st = mgr.status()
    for key in (
        "state",
        "current_title",
        "output_resolution",
        "ffmpeg_pid",
        "ffmpeg_alive",
        "recent_logs",
    ):
        assert key in st
    assert st["state"] == "offline"


def test_kill_orphans_no_crash(tmp_path):
    # Should be a safe no-op when nothing matches.
    StreamManager(tmp_path / "stream").kill_orphans()


# --- Integration (real ffmpeg, software encoder) --------------------------
@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")
def test_real_hls_encode_and_stop(tmp_path):
    # Make a tiny 2-second 320x240 test clip.
    src = tmp_path / "clip.mkv"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src),
        ],
        check=True,
        capture_output=True,
    )

    mgr = StreamManager(tmp_path / "stream")
    ok = mgr.start(
        movie_id=1,
        title="Test Clip",
        rating_key="1",
        source_path=str(src),
        offset_seconds=0,
        maximum_resolution=MaxResolution.p720,  # 320x240 stays 320x240 (no upscale)
        video_bitrate_kbps=1500,
        audio_bitrate_kbps=128,
        encoder="libx264",
        preset=EncoderPreset.fast,
    )
    assert ok is True
    assert mgr.state == StreamState.streaming
    # No upscaling: 320x240 source under a 720p cap stays 320x240.
    assert mgr.output_dims == (320, 240)

    # Wait for the playlist and at least one segment to appear.
    playlist = mgr.playlist_path
    deadline = time.time() + 12
    seg_found = False
    while time.time() < deadline:
        if playlist.exists() and list((tmp_path / "stream").glob("*.ts")):
            seg_found = True
            break
        time.sleep(0.3)
    assert playlist.exists(), "HLS playlist was not created"
    assert seg_found, "no HLS segments were produced"

    mgr.stop()
    assert mgr.state == StreamState.offline
    # Cleanup removed playlist + segments.
    assert not playlist.exists()
    assert not list((tmp_path / "stream").glob("*.ts"))
