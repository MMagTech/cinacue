"""Plex integration.

Two concerns live here:

1. **Path translation** — pure helpers that convert a path as Plex reports it
   into the path mounted inside this container.
2. **Plex API client** — connect to the server, locate the movie library,
   search it, and read full metadata for a movie.

Network calls and response *parsing* are kept separate so the parsing is
unit-tested without a live server. The Plex token is only ever used server-side
and is never returned to browser clients.
"""
from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import Any, List, Optional

import httpx


# ---------------------------------------------------------------------------
# Path translation
# ---------------------------------------------------------------------------
def translate_plex_path(plex_path: str, plex_prefix: str, local_prefix: str) -> str:
    """Map a Plex-reported path onto the mounted container path."""
    plex_prefix = plex_prefix.rstrip("/")
    local_prefix = local_prefix.rstrip("/")

    norm = plex_path
    if norm == plex_prefix:
        return local_prefix
    if norm.startswith(plex_prefix + "/"):
        remainder = norm[len(plex_prefix):]
        return local_prefix + remainder
    return plex_path


def is_within_local_root(path: str, local_prefix: str) -> bool:
    """Guard against path traversal: resolved path must stay under the root."""
    root = posixpath.normpath(local_prefix)
    resolved = posixpath.normpath(path)
    return resolved == root or resolved.startswith(root + "/")


# ---------------------------------------------------------------------------
# Parsed metadata
# ---------------------------------------------------------------------------
@dataclass
class PlexMovie:
    rating_key: str
    title: str
    year: Optional[int]
    summary: str
    thumb_key: Optional[str]
    runtime_ms: int
    source_path: Optional[str]
    width: Optional[int]
    height: Optional[int]
    video_codec: Optional[str]
    audio_codec: Optional[str]
    container: Optional[str]


class PlexError(Exception):
    """Raised for connection or protocol failures talking to Plex."""


# ---------------------------------------------------------------------------
# Pure parsers (unit-tested)
# ---------------------------------------------------------------------------
def parse_sections(data: dict) -> List[dict]:
    """Return [{key, title, type}] from a /library/sections response."""
    container = data.get("MediaContainer", {})
    out = []
    for d in container.get("Directory", []) or []:
        out.append(
            {
                "key": str(d.get("key", "")),
                "title": d.get("title", ""),
                "type": d.get("type", ""),
            }
        )
    return out


def find_movie_section_key(data: dict, library_name: str) -> Optional[str]:
    """Find the section key for the named movie library (case-insensitive)."""
    for section in parse_sections(data):
        if (
            section["type"] == "movie"
            and section["title"].lower() == library_name.lower()
        ):
            return section["key"]
    return None


def _first(seq: Any) -> Optional[dict]:
    if isinstance(seq, list) and seq:
        return seq[0]
    return None


def parse_movie_item(item: dict) -> PlexMovie:
    """Parse one Plex ``Metadata`` entry into a :class:`PlexMovie`."""
    media = _first(item.get("Media")) or {}
    part = _first(media.get("Part")) or {}

    width = media.get("width")
    height = media.get("height")

    video_codec = media.get("videoCodec")
    audio_codec = media.get("audioCodec")
    for stream in part.get("Stream", []) or []:
        stype = stream.get("streamType")
        if stype == 1 and not video_codec:
            video_codec = stream.get("codec")
        elif stype == 2 and not audio_codec:
            audio_codec = stream.get("codec")

    year = item.get("year")
    return PlexMovie(
        rating_key=str(item.get("ratingKey", "")),
        title=item.get("title", ""),
        year=int(year) if year is not None else None,
        summary=item.get("summary", "") or "",
        thumb_key=item.get("thumb"),
        runtime_ms=int(item.get("duration", 0) or 0),
        source_path=part.get("file"),
        width=int(width) if width else None,
        height=int(height) if height else None,
        video_codec=video_codec,
        audio_codec=audio_codec,
        container=media.get("container") or part.get("container"),
    )


def parse_metadata_list(data: dict) -> List[PlexMovie]:
    container = data.get("MediaContainer", {})
    return [parse_movie_item(m) for m in container.get("Metadata", []) or []]


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------
class PlexClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        library_name: str,
        *,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.library_name = library_name
        self.timeout = timeout

    def _headers(self) -> dict:
        return {"X-Plex-Token": self.token, "Accept": "application/json"}

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers=self._headers(), params=params or {})
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:  # pragma: no cover - network
            raise PlexError(f"Plex request failed: {exc}") from exc

    def ping(self) -> bool:
        try:
            self._get("/identity")
            return True
        except PlexError:
            return False

    def movie_section_key(self) -> str:
        data = self._get("/library/sections")
        key = find_movie_section_key(data, self.library_name)
        if key is None:
            raise PlexError(
                f"Movie library '{self.library_name}' not found on Plex server."
            )
        return key

    def search_movies(self, query: str, limit: int = 30) -> List[PlexMovie]:
        key = self.movie_section_key()
        data = self._get(
            f"/library/sections/{key}/all",
            params={"type": 1, "title": query, "limit": limit},
        )
        return parse_metadata_list(data)

    def get_movie(self, rating_key: str) -> PlexMovie:
        data = self._get(f"/library/metadata/{rating_key}")
        movies = parse_metadata_list(data)
        if not movies:
            raise PlexError(f"Movie {rating_key} not found.")
        return movies[0]

    def image_url(self, thumb_key: str) -> str:
        sep = "&" if "?" in thumb_key else "?"
        return f"{self.base_url}{thumb_key}{sep}X-Plex-Token={self.token}"

    def fetch_image(self, thumb_key: str) -> httpx.Response:
        url = f"{self.base_url}{thumb_key}"
        try:
            client = httpx.Client(timeout=self.timeout)
            resp = client.get(url, headers=self._headers())
            resp.raise_for_status()
            return resp
        except httpx.HTTPError as exc:  # pragma: no cover - network
            raise PlexError(f"Plex image request failed: {exc}") from exc
