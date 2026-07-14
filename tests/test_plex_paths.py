"""Tests for Plex path translation and traversal guarding."""
from __future__ import annotations

from app.plex_client import is_within_local_root, translate_plex_path


def test_brief_example():
    out = translate_plex_path(
        "/movies/Back to the Future (1985)/movie.mkv",
        "/movies",
        "/media/movies",
    )
    assert out == "/media/movies/Back to the Future (1985)/movie.mkv"


def test_trailing_slashes_normalised():
    out = translate_plex_path("/movies/x.mkv", "/movies/", "/media/movies/")
    assert out == "/media/movies/x.mkv"


def test_prefix_only_matches_full_segment():
    # /movies must not match /movies-archive
    out = translate_plex_path("/movies-archive/x.mkv", "/movies", "/media/movies")
    assert out == "/movies-archive/x.mkv"


def test_non_matching_prefix_unchanged():
    out = translate_plex_path("/data/x.mkv", "/movies", "/media/movies")
    assert out == "/data/x.mkv"


def test_exact_prefix():
    assert translate_plex_path("/movies", "/movies", "/media/movies") == "/media/movies"


def test_within_root_true():
    assert is_within_local_root("/media/movies/a/b.mkv", "/media/movies")


def test_traversal_blocked():
    assert not is_within_local_root("/media/movies/../secret.mkv", "/media/movies")
    assert not is_within_local_root("/etc/passwd", "/media/movies")
