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


def _subtitle_args(*, offset: float = 0.0, encoder: str = "h264_nvenc", is_hdr: bool = False):
    dims = calculate_output_dimensions(1920, 1080, MaxResolution.p1080)
    return build_ffmpeg_args(
        source_path="/media/movies/Movie (2020)/movie.mkv",
        output_playlist="/stream/channel.m3u8",
        dims=dims,
        video_bitrate_kbps=4000,
        audio_bitrate_kbps=160,
        encoder=encoder,
        start_offset_seconds=offset,
        segment_pattern="/stream/segment-%06d.ts",
        subtitle_path="/media/movies/Movie (2020)/movie.en.srt",
        is_hdr=is_hdr,
    )


def test_subtitle_adds_webvtt_rendition():
    args = _subtitle_args()
    # The sidecar is a second input.
    assert args.count("-i") == 2
    assert "/media/movies/Movie (2020)/movie.en.srt" in args
    # Explicit maps: movie video + audio, sidecar subtitle (skips embedded subs).
    assert "0:v:0" in args and "0:a:0" in args and "1:s:0" in args
    # Subtitle encoded to WebVTT.
    assert args[args.index("-c:s") + 1] == "webvtt"
    # Multivariant playlist with a subtitle group; master keeps the stable name.
    assert "sgroup:subs" in args[args.index("-var_stream_map") + 1]
    assert args[args.index("-master_pl_name") + 1] == "channel.m3u8"
    # The single-playlist segment flag is not used in multivariant mode.
    assert "-hls_segment_filename" not in args


def test_subtitle_offset_seeks_both_inputs():
    # Both the video and the sidecar are input-seeked by the offset so the
    # captions stay aligned with the video (which restarts its clock at 0).
    args = _subtitle_args(offset=600)
    ss_values = [args[i + 1] for i, a in enumerate(args) if a == "-ss"]
    assert ss_values == ["600.000", "600.000"]


def test_subtitle_with_hdr_keeps_tonemap_and_captions():
    args = _subtitle_args(is_hdr=True)
    assert "tonemap_cuda" in args[args.index("-vf") + 1]
    assert "-var_stream_map" in args
    assert "1:s:0" in args


def test_no_subtitle_keeps_single_media_playlist():
    # Without a sidecar the output is byte-for-byte the original single playlist.
    args = _args()
    assert "-var_stream_map" not in args
    assert "-master_pl_name" not in args
    assert "-c:s" not in args
    assert "-map" not in args
    assert "-hls_segment_filename" in args
    assert args[-1] == "/stream/channel.m3u8"
