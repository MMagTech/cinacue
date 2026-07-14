"""Tests for Plex response parsing and the Plex->schema service conversion.

No live server: we feed representative Plex JSON shapes to the pure parsers.
"""
from __future__ import annotations

import os

from app.models import Settings as SettingsRow
from app.plex_client import (
    find_movie_section_key,
    parse_metadata_list,
    parse_movie_item,
    parse_sections,
)
from app.plex_service import movie_to_out

SECTIONS = {
    "MediaContainer": {
        "Directory": [
            {"key": "1", "title": "Movies", "type": "movie"},
            {"key": "2", "title": "TV Shows", "type": "show"},
            {"key": "3", "title": "Home Videos", "type": "movie"},
        ]
    }
}

MOVIE_ITEM = {
    "ratingKey": "12345",
    "title": "Back to the Future",
    "year": 1985,
    "summary": "Marty travels through time.",
    "thumb": "/library/metadata/12345/thumb/1699",
    "duration": 6960000,  # 116 minutes in ms
    "Media": [
        {
            "width": 3840,
            "height": 2160,
            "videoCodec": "hevc",
            "audioCodec": "eac3",
            "container": "mkv",
            "Part": [
                {
                    "file": "/movies/Back to the Future (1985)/movie.mkv",
                    "container": "mkv",
                    "Stream": [
                        {"streamType": 1, "codec": "hevc"},
                        {"streamType": 2, "codec": "eac3"},
                    ],
                }
            ],
        }
    ],
}

SEARCH = {"MediaContainer": {"Metadata": [MOVIE_ITEM]}}


# --- Sections --------------------------------------------------------------
def test_parse_sections():
    sections = parse_sections(SECTIONS)
    assert len(sections) == 3
    assert sections[0] == {"key": "1", "title": "Movies", "type": "movie"}


def test_find_movie_section_matches_by_name_case_insensitive():
    assert find_movie_section_key(SECTIONS, "movies") == "1"
    assert find_movie_section_key(SECTIONS, "Home Videos") == "3"


def test_find_movie_section_ignores_non_movie_types():
    # "TV Shows" is type show; must not match even if named that way.
    assert find_movie_section_key(SECTIONS, "TV Shows") is None


def test_find_movie_section_missing_returns_none():
    assert find_movie_section_key(SECTIONS, "Documentaries") is None


# --- Metadata --------------------------------------------------------------
def test_parse_movie_item_full():
    m = parse_movie_item(MOVIE_ITEM)
    assert m.rating_key == "12345"
    assert m.title == "Back to the Future"
    assert m.year == 1985
    assert m.runtime_ms == 6960000
    assert m.width == 3840 and m.height == 2160
    assert m.video_codec == "hevc"
    assert m.audio_codec == "eac3"
    assert m.container == "mkv"
    assert m.source_path == "/movies/Back to the Future (1985)/movie.mkv"
    assert m.thumb_key == "/library/metadata/12345/thumb/1699"


def test_parse_movie_item_lightweight_without_media():
    light = {"ratingKey": "9", "title": "Untitled", "duration": 0}
    m = parse_movie_item(light)
    assert m.rating_key == "9"
    assert m.source_path is None
    assert m.width is None
    assert m.runtime_ms == 0


def test_parse_metadata_list():
    movies = parse_metadata_list(SEARCH)
    assert len(movies) == 1
    assert movies[0].title == "Back to the Future"


# --- Service conversion ----------------------------------------------------
def _row(local_prefix: str) -> SettingsRow:
    return SettingsRow(
        id=1,
        plex_path_prefix="/movies",
        local_path_prefix=local_prefix,
        plex_library_name="Movies",
    )


def test_movie_to_out_hides_path_and_flags_available(tmp_path):
    # Materialise the translated file so source_available is True.
    local_root = tmp_path / "media"
    film_dir = local_root / "Back to the Future (1985)"
    film_dir.mkdir(parents=True)
    (film_dir / "movie.mkv").write_text("x")

    row = _row(str(local_root))
    out = movie_to_out(parse_movie_item(MOVIE_ITEM), row)

    assert out.title == "Back to the Future"
    assert out.runtime_minutes == 116
    assert out.source_resolution == "3840x2160"
    assert out.video_codec == "hevc"
    assert out.poster_url == "/api/admin/plex/poster/12345"
    assert out.source_available is True

    # The raw filesystem path must not be exposed in the serialized payload.
    dumped = out.model_dump()
    assert "source_path" not in dumped
    for v in dumped.values():
        assert not (isinstance(v, str) and str(local_root) in v)


def test_movie_to_out_source_missing(tmp_path):
    row = _row(str(tmp_path / "does-not-exist"))
    out = movie_to_out(parse_movie_item(MOVIE_ITEM), row)
    assert out.source_available is False
