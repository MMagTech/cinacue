"""Tests for the critical no-upscaling resolution rule.

Covers every example from the project brief plus edge cases: aspect-ratio
preservation, even dimensions, portrait sources, and the "original" ceiling.
"""
from __future__ import annotations

import math

import pytest

from app.config import MaxResolution
from app.encoding import calculate_output_dimensions


def _aspect(w: int, h: int) -> float:
    return w / h


# --- Brief examples --------------------------------------------------------
def test_4k_source_1080p_max_downscales_to_1080p():
    d = calculate_output_dimensions(3840, 2160, MaxResolution.p1080)
    assert (d.output_width, d.output_height) == (1920, 1080)
    assert not d.upscaled_blocked


def test_1080p_source_1080p_max_stays_1080p():
    d = calculate_output_dimensions(1920, 1080, MaxResolution.p1080)
    assert (d.output_width, d.output_height) == (1920, 1080)


def test_720p_source_1080p_max_stays_720p():
    d = calculate_output_dimensions(1280, 720, MaxResolution.p1080)
    assert (d.output_width, d.output_height) == (1280, 720)
    assert d.upscaled_blocked


def test_480p_source_720p_max_stays_480p():
    d = calculate_output_dimensions(720, 480, MaxResolution.p720)
    assert (d.output_width, d.output_height) == (720, 480)
    assert d.upscaled_blocked


def test_cinemascope_source_preserves_aspect_without_cropping():
    # 1920x800 (2.4:1) into a 1280x720 ceiling. Width binds; height shrinks
    # proportionally. Aspect ratio must be preserved, no cropping.
    d = calculate_output_dimensions(1920, 800, MaxResolution.p720)
    assert d.output_width == 1280
    # 800 * (1280/1920) = 533.3 -> round 533 -> 532 (even)
    assert d.output_height == 532
    assert math.isclose(_aspect(d.output_width, d.output_height), 2.4, rel_tol=0.01)


# --- General guarantees ----------------------------------------------------
@pytest.mark.parametrize(
    "w,h,maximum",
    [
        (3840, 2160, MaxResolution.p1080),
        (3840, 2160, MaxResolution.p720),
        (3840, 2160, MaxResolution.p480),
        (1920, 1080, MaxResolution.p720),
        (1280, 720, MaxResolution.p1080),
        (720, 480, MaxResolution.p1080),
        (1080, 1920, MaxResolution.p1080),  # portrait
        (1234, 567, MaxResolution.p720),  # odd dims
    ],
)
def test_output_never_exceeds_source(w, h, maximum):
    d = calculate_output_dimensions(w, h, maximum)
    assert d.output_width <= w
    assert d.output_height <= h


@pytest.mark.parametrize(
    "w,h,maximum",
    [
        (3841, 2161, MaxResolution.p1080),
        (1235, 569, MaxResolution.p720),
        (999, 501, MaxResolution.p480),
        (1920, 800, MaxResolution.p720),
        (720, 481, MaxResolution.original),
    ],
)
def test_output_dimensions_are_even(w, h, maximum):
    d = calculate_output_dimensions(w, h, maximum)
    assert d.output_width % 2 == 0
    assert d.output_height % 2 == 0


def test_original_max_keeps_source_but_forces_even():
    d = calculate_output_dimensions(1921, 1081, MaxResolution.original)
    assert d.output_width == 1920
    assert d.output_height == 1080


def test_portrait_source_capped_by_height():
    # 1080x1920 portrait into 1080p (1920x1080) ceiling. Height (1920) binds.
    d = calculate_output_dimensions(1080, 1920, MaxResolution.p1080)
    assert d.output_height == 1080
    # 1080 * (1080/1920) = 607.5 -> round 608 (even)
    assert d.output_width == 608


def test_aspect_ratio_preserved_within_tolerance():
    d = calculate_output_dimensions(3840, 2160, MaxResolution.p720)
    src = _aspect(3840, 2160)
    out = _aspect(d.output_width, d.output_height)
    assert math.isclose(src, out, rel_tol=0.01)


def test_invalid_dimensions_raise():
    with pytest.raises(ValueError):
        calculate_output_dimensions(0, 1080, MaxResolution.p1080)
    with pytest.raises(ValueError):
        calculate_output_dimensions(1920, -1, MaxResolution.p1080)
