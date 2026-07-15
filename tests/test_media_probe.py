"""Tests for ffprobe JSON parsing (pure) and end-time calc."""
from __future__ import annotations

from app.media_probe import parse_ffprobe

FFPROBE_JSON = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "hevc",
            "width": 3840,
            "height": 2160,
        },
        {"codec_type": "audio", "codec_name": "eac3"},
    ],
    "format": {"format_name": "matroska,webm", "duration": "6960.5"},
}


def test_parse_ffprobe_video_and_audio():
    r = parse_ffprobe(FFPROBE_JSON)
    assert r.width == 3840
    assert r.height == 2160
    assert r.video_codec == "hevc"
    assert r.audio_codec == "eac3"
    assert r.container == "matroska,webm"
    assert abs(r.duration_seconds - 6960.5) < 0.001


def test_parse_ffprobe_missing_audio():
    data = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720}], "format": {}}
    r = parse_ffprobe(data)
    assert r.width == 1280
    assert r.audio_codec is None


def test_parse_ffprobe_no_video_stream():
    r = parse_ffprobe({"streams": [{"codec_type": "audio", "codec_name": "aac"}], "format": {}})
    assert r.width is None
    assert r.height is None


def test_parse_ffprobe_detects_hdr_pq():
    data = {
        "streams": [{"codec_type": "video", "codec_name": "hevc", "width": 3840, "height": 2160, "color_transfer": "smpte2084"}],
        "format": {},
    }
    r = parse_ffprobe(data)
    assert r.color_transfer == "smpte2084"
    assert r.is_hdr is True


def test_parse_ffprobe_detects_hdr_hlg():
    data = {
        "streams": [{"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080, "color_transfer": "arib-std-b67"}],
        "format": {},
    }
    assert parse_ffprobe(data).is_hdr is True


def test_parse_ffprobe_sdr_is_not_hdr():
    data = {
        "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "color_transfer": "bt709"}],
        "format": {},
    }
    r = parse_ffprobe(data)
    assert r.is_hdr is False
    # No color_transfer at all is also treated as SDR.
    assert parse_ffprobe(FFPROBE_JSON).is_hdr is False
