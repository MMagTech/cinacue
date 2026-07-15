"""Tests for FFmpeg argument generation (no shell, correct encoder/scale)."""
from __future__ import annotations

from app.config import EncoderPreset, MaxResolution
from app.encoding import build_ffmpeg_args, calculate_output_dimensions, nvenc_preset


def _args():
    dims = calculate_output_dimensions(3840, 2160, MaxResolution.p1080)
    return build_ffmpeg_args(
        source_path="/media/movies/Movie (1985)/movie.mkv",
        output_playlist="/stream/channel.m3u8",
        dims=dims,
        video_bitrate_kbps=8000,
        audio_bitrate_kbps=192,
        preset=EncoderPreset.balanced,
        start_offset_seconds=35 * 60,
    )


def test_args_are_a_list():
    assert isinstance(_args(), list)
    assert all(isinstance(a, str) for a in _args())


def test_uses_nvenc_encoder():
    args = _args()
    assert "h264_nvenc" in args
    assert "-c:v" in args


def test_scale_matches_output_dimensions():
    args = _args()
    vf_index = args.index("-vf")
    assert args[vf_index + 1] == "scale=1920:1080"


def test_video_bitrate_and_audio():
    args = _args()
    assert "8000k" in args
    assert "aac" in args
    assert "192k" in args


def test_seek_offset_present():
    args = _args()
    assert "-ss" in args
    ss_index = args.index("-ss")
    assert args[ss_index + 1] == f"{35 * 60:.3f}"


def test_hls_output_and_flags():
    args = _args()
    assert "-f" in args and "hls" in args
    assert args[-1] == "/stream/channel.m3u8"
    flags_index = args.index("-hls_flags")
    assert "delete_segments" in args[flags_index + 1]


def test_preset_mapping():
    assert nvenc_preset(EncoderPreset.fast) == "p2"
    assert nvenc_preset(EncoderPreset.balanced) == "p4"
    assert nvenc_preset(EncoderPreset.quality) == "p6"


def test_no_offset_omits_ss():
    dims = calculate_output_dimensions(1280, 720, MaxResolution.p1080)
    args = build_ffmpeg_args(
        source_path="/x.mkv",
        output_playlist="/stream/channel.m3u8",
        dims=dims,
        video_bitrate_kbps=4000,
        audio_bitrate_kbps=128,
        start_offset_seconds=0,
    )
    assert "-ss" not in args


def _hdr_args():
    dims = calculate_output_dimensions(3840, 2160, MaxResolution.p720)
    return build_ffmpeg_args(
        source_path="/media/movies/HDR (2020)/movie.mkv",
        output_playlist="/stream/channel.m3u8",
        dims=dims,
        video_bitrate_kbps=4000,
        audio_bitrate_kbps=192,
        is_hdr=True,
    )


def test_hdr_uses_gpu_tonemap_pipeline():
    args = _hdr_args()
    assert "-hwaccel_output_format" in args  # frames stay on the GPU
    vf = args[args.index("-vf") + 1]
    assert "tonemap_cuda" in vf
    assert "scale_cuda=1280:720:format=nv12" in vf
    assert "-pix_fmt" not in args  # nv12 is set in the filter, on the GPU


def test_sdr_path_is_unchanged_by_hdr_feature():
    args = _args()  # is_hdr defaults False
    assert args[args.index("-vf") + 1] == "scale=1920:1080"
    assert "-pix_fmt" in args
    assert "-hwaccel_output_format" not in args
    assert "tonemap_cuda" not in " ".join(args)


def test_software_encoder_ignores_hdr():
    # HDR tonemap is GPU-only; a software encoder must never get GPU filters.
    dims = calculate_output_dimensions(1920, 1080, MaxResolution.p720)
    args = build_ffmpeg_args(
        source_path="/x.mkv",
        output_playlist="/stream/channel.m3u8",
        dims=dims,
        video_bitrate_kbps=3000,
        audio_bitrate_kbps=128,
        encoder="libx264",
        is_hdr=True,
    )
    assert "tonemap_cuda" not in " ".join(args)
    assert "-hwaccel_output_format" not in args
    assert "-pix_fmt" in args
