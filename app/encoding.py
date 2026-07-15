"""Output-resolution calculation, FFmpeg argument construction, NVENC checks.

The single most important rule of this application: **never upscale**. The
configured channel resolution is a *maximum*, not a target. Aspect ratio is
always preserved, never cropped or stretched, and final dimensions are always
even (required by H.264/yuv420p).

:func:`calculate_output_dimensions` is pure and heavily unit-tested. FFmpeg
argument building takes arguments as a list (never a shell string) to prevent
command injection.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .config import EncoderPreset, MaxResolution

_RESOLUTION_CAPS: dict[MaxResolution, Optional[tuple[int, int]]] = {
    MaxResolution.original: None,
    MaxResolution.p1080: (1920, 1080),
    MaxResolution.p720: (1280, 720),
    MaxResolution.p480: (854, 480),
}

_NVENC_PRESET_MAP: dict[EncoderPreset, str] = {
    EncoderPreset.fast: "p2",
    EncoderPreset.balanced: "p4",
    EncoderPreset.quality: "p6",
}


def _make_even(value: int) -> int:
    """Round *down* to the nearest even number, floor of 2.

    Rounding down guarantees we never exceed the computed (already-capped)
    dimension, so we can never accidentally upscale by rounding up.
    """
    even = value - (value % 2)
    return max(2, even)


@dataclass(frozen=True)
class OutputDimensions:
    source_width: int
    source_height: int
    output_width: int
    output_height: int

    @property
    def upscaled_blocked(self) -> bool:
        return (
            self.output_width == self.source_width
            and self.output_height == self.source_height
        )


def calculate_output_dimensions(
    source_width: int,
    source_height: int,
    maximum: MaxResolution,
) -> OutputDimensions:
    """Compute final output dimensions honouring the no-upscale rule."""
    if source_width <= 0 or source_height <= 0:
        raise ValueError("source dimensions must be positive")

    cap = _RESOLUTION_CAPS[maximum]

    if cap is None:
        w = _make_even(source_width)
        h = _make_even(source_height)
        return OutputDimensions(source_width, source_height, w, h)

    max_w, max_h = cap
    scale = min(max_w / source_width, max_h / source_height, 1.0)

    if scale >= 1.0:
        return OutputDimensions(
            source_width,
            source_height,
            _make_even(source_width),
            _make_even(source_height),
        )

    out_w = _make_even(round(source_width * scale))
    out_h = _make_even(round(source_height * scale))
    return OutputDimensions(source_width, source_height, out_w, out_h)


def nvenc_preset(preset: EncoderPreset) -> str:
    return _NVENC_PRESET_MAP[preset]


def _is_hardware_encoder(encoder: str) -> bool:
    return encoder.endswith("nvenc")


def build_ffmpeg_args(
    *,
    source_path: str,
    output_playlist: str,
    dims: OutputDimensions,
    video_bitrate_kbps: int,
    audio_bitrate_kbps: int,
    encoder: str = "h264_nvenc",
    preset: EncoderPreset = EncoderPreset.balanced,
    start_offset_seconds: float = 0.0,
    segment_pattern: Optional[str] = None,
    hls_segment_seconds: int = 4,
    is_hdr: bool = False,
    subtitle_path: Optional[str] = None,
    ffmpeg_bin: str = "ffmpeg",
) -> List[str]:
    """Build the FFmpeg argument list for a live HLS stream.

    Returned as a list so it can be passed straight to ``subprocess`` without a
    shell, preventing command injection. Hardware decode is only requested for
    NVENC encoders; software encoders (used in tests) omit it.

    When ``subtitle_path`` is given (an external SRT sidecar), it is muxed in as
    a WebVTT subtitle rendition and the output becomes a multivariant (master)
    playlist so players can toggle captions per-viewer. Without it, the output
    is the original single media playlist, byte-for-byte unchanged.
    """
    seg_pattern = segment_pattern or "segment-%06d.ts"
    # Fallback GOP cap. The authoritative keyframe placement is -force_key_frames
    # below, which lands an IDR exactly on every segment boundary regardless of
    # the source frame rate (films are ~23.976 fps, not 30) so HLS segments stay
    # keyframe-aligned and players don't stutter at segment edges.
    gop = hls_segment_seconds * 30
    hardware = _is_hardware_encoder(encoder)

    # HDR only matters when the GPU encoder is in play (tonemap runs on the card).
    hdr = hardware and is_hdr
    subtitles = bool(subtitle_path)

    args: List[str] = [ffmpeg_bin, "-hide_banner", "-y"]

    if hardware:
        args += ["-hwaccel", "cuda"]
        if hdr:
            # Keep decoded frames in GPU memory so tonemap + scale run on the
            # card (no CPU download/round-trip).
            args += ["-hwaccel_output_format", "cuda"]

    # Read the input at its native frame rate so the HLS output is produced in
    # real time. Without -re, ffmpeg encodes as fast as the GPU allows, the
    # sliding-window playlist races ahead of the player, and segments are
    # deleted before they can be played -> the stream constantly skips forward.
    args += ["-re"]

    if start_offset_seconds > 0:
        args += ["-ss", f"{start_offset_seconds:.3f}"]

    args += ["-i", source_path]

    if subtitles:
        # External subtitle as a second input. Input-seek it by the same offset
        # as the video so its cue timing stays aligned: an input seek restarts
        # both streams' timestamps at zero, so seeking only the video would
        # leave the captions running ahead by ``start_offset_seconds``.
        if start_offset_seconds > 0:
            args += ["-ss", f"{start_offset_seconds:.3f}"]
        args += ["-i", subtitle_path]
        # With a second input, ffmpeg's default stream selection is ambiguous;
        # map the video + audio from the movie and the subtitle from the sidecar
        # explicitly (this also skips any embedded subtitle tracks in the movie).
        args += ["-map", "0:v:0", "-map", "0:a:0", "-map", "1:s:0"]

    if hdr:
        # HDR -> SDR entirely on the GPU: tonemap first (in high bit depth,
        # tonemap_cuda's defaults target BT.709 SDR), then resize and downconvert
        # to 8-bit nv12 for the H.264 encoder. Frames stay on the GPU, so no
        # -pix_fmt (that would force a CPU format).
        vf = (
            f"tonemap_cuda=tonemap=bt2390,"
            f"scale_cuda={dims.output_width}:{dims.output_height}:format=nv12"
        )
        pix_fmt_args: List[str] = []
    else:
        vf = f"scale={dims.output_width}:{dims.output_height}"
        pix_fmt_args = ["-pix_fmt", "yuv420p"]

    preset_value = nvenc_preset(preset) if hardware else "veryfast"
    args += [
        "-vf",
        vf,
        "-c:v",
        encoder,
        "-preset",
        preset_value,
        "-b:v",
        f"{video_bitrate_kbps}k",
        "-maxrate",
        f"{video_bitrate_kbps}k",
        "-bufsize",
        f"{video_bitrate_kbps * 2}k",
        "-g",
        str(gop),
        "-force_key_frames",
        f"expr:gte(t,n_forced*{hls_segment_seconds})",
    ] + pix_fmt_args

    args += ["-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k", "-ac", "2"]

    if subtitles:
        args += ["-c:s", "webvtt"]

    args += [
        "-f",
        "hls",
        "-hls_time",
        str(hls_segment_seconds),
        "-hls_list_size",
        "6",
        "-hls_flags",
        "delete_segments+independent_segments+append_list",
    ]

    if subtitles:
        # Multivariant playlist: the master keeps the original playlist name so
        # the player URL never changes, and the video/audio + subtitle variants
        # live beside it (v0.m3u8 / v0_vtt.m3u8, segments v0*.ts / v0*.vtt).
        sep = output_playlist.rfind("/")
        master_name = output_playlist[sep + 1 :] if sep >= 0 else output_playlist
        stream_dir = output_playlist[:sep] if sep >= 0 else "."
        args += [
            "-master_pl_name",
            master_name,
            "-var_stream_map",
            "v:0,a:0,s:0,sgroup:subs",
            f"{stream_dir}/v%v.m3u8",
        ]
    else:
        args += ["-hls_segment_filename", seg_pattern, output_playlist]

    return args


# ---------------------------------------------------------------------------
# NVENC availability
# ---------------------------------------------------------------------------
def nvenc_listed(ffmpeg_bin: str = "ffmpeg", timeout: float = 10.0) -> bool:
    """True if the ffmpeg build lists the h264_nvenc encoder.

    Listing is necessary but NOT sufficient — see :func:`verify_nvenc`.
    """
    try:
        proc = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    return "h264_nvenc" in proc.stdout


def verify_nvenc(ffmpeg_bin: str = "ffmpeg", timeout: float = 30.0) -> Tuple[bool, str]:
    """Attempt a tiny real NVENC encode to confirm the GPU actually works.

    Returns ``(ok, detail)``. This is the authoritative check: it encodes a
    short synthetic clip with ``h264_nvenc`` to the null muxer. If the GPU or
    driver is unavailable the encode fails and we report it — the application
    never silently falls back to CPU encoding.
    """
    if not nvenc_listed(ffmpeg_bin, timeout=timeout):
        return False, "h264_nvenc encoder is not listed by ffmpeg"
    args = [
        ffmpeg_bin,
        "-hide_banner",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=256x144:rate=15:duration=0.2",
        "-c:v",
        "h264_nvenc",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return False, "ffmpeg is not installed"
    except subprocess.TimeoutExpired:
        return False, "NVENC test encode timed out"
    if proc.returncode == 0:
        return True, "NVENC hardware encode succeeded"
    tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
    return False, f"NVENC test encode failed: {tail[0]}"
