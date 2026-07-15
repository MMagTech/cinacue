"""API tests for the daily-lineup schedule with a mocked Plex client.

Covers add / edit-time / delete, overlap rejection (409), CSRF enforcement,
the no-runtime guard, and the per-weekday active-days switch.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app import plex_service
from app.database import engine, get_settings_row
from app.main import app
from app.models import ScheduledMovie
from app.plex_client import PlexMovie


def _fake_movie(rating_key: str) -> PlexMovie:
    # rating_key "noruntime" yields a zero-runtime movie for the guard test.
    runtime = 0 if rating_key == "noruntime" else 116 * 60_000
    return PlexMovie(
        rating_key=rating_key,
        title=f"Movie {rating_key}",
        year=2000,
        summary="",
        thumb_key=f"/library/metadata/{rating_key}/thumb/1",
        runtime_ms=runtime,
        source_path="/movies/Movie/movie.mkv",
        width=1920,
        height=1080,
        video_codec="h264",
        audio_codec="aac",
        container="mkv",
    )


class _FakeClient:
    def get_movie(self, rating_key: str) -> PlexMovie:
        return _fake_movie(rating_key)


@pytest.fixture(autouse=True)
def _clean_and_mock(monkeypatch):
    # Fresh lineup and all-days-on for every test in this module.
    with Session(engine) as s:
        s.exec(delete(ScheduledMovie))
        row = get_settings_row(s)
        row.active_days_mask = 127
        s.add(row)
        s.commit()
    monkeypatch.setattr(plex_service, "plex_configured", lambda: True)
    monkeypatch.setattr(plex_service, "make_client", lambda row: _FakeClient())
    yield


def _min(h: int, m: int = 0) -> int:
    return h * 60 + m


def _auth_client() -> tuple[TestClient, str]:
    c = TestClient(app)
    r = c.post("/api/admin/login", json={"password": "test-admin-password"})
    return c, r.json()["csrf_token"]


def _add(c, csrf, rating_key, start_minute):
    return c.post(
        "/api/admin/schedule",
        json={"plex_rating_key": rating_key, "start_minute": start_minute},
        headers={"X-CSRF-Token": csrf},
    )


# --- Add -------------------------------------------------------------------
def test_add_movie_sets_slot():
    c, csrf = _auth_client()
    r = _add(c, csrf, "1", _min(19))
    assert r.status_code == 201
    assert r.json()["start_minute"] == _min(19)


def test_add_requires_csrf():
    c, _ = _auth_client()
    r = c.post(
        "/api/admin/schedule",
        json={"plex_rating_key": "1", "start_minute": _min(19)},
    )
    assert r.status_code == 403


def test_add_requires_auth():
    c = TestClient(app)
    r = c.post(
        "/api/admin/schedule",
        json={"plex_rating_key": "1", "start_minute": _min(19)},
    )
    assert r.status_code == 401


def test_add_zero_runtime_rejected():
    c, csrf = _auth_client()
    assert _add(c, csrf, "noruntime", _min(19)).status_code == 422


# --- Overlap ---------------------------------------------------------------
def test_overlap_rejected():
    c, csrf = _auth_client()
    assert _add(c, csrf, "1", _min(19)).status_code == 201  # 19:00-20:56
    assert _add(c, csrf, "2", _min(20)).status_code == 409  # 20:00 inside


def test_adjacent_allowed():
    c, csrf = _auth_client()
    assert _add(c, csrf, "1", _min(19)).status_code == 201  # ends 20:56
    assert _add(c, csrf, "2", _min(21)).status_code == 201


# --- Edit ------------------------------------------------------------------
def test_edit_time_updates_slot():
    c, csrf = _auth_client()
    mid = _add(c, csrf, "1", _min(19)).json()["id"]
    r = c.patch(
        f"/api/admin/schedule/{mid}",
        json={"start_minute": _min(21)},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200
    assert r.json()["start_minute"] == _min(21)


def test_edit_into_overlap_rejected():
    c, csrf = _auth_client()
    _add(c, csrf, "1", _min(19))  # 19:00-20:56
    mid2 = _add(c, csrf, "2", _min(21)).json()["id"]  # 21:00-22:56
    r = c.patch(
        f"/api/admin/schedule/{mid2}",
        json={"start_minute": _min(20)},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 409


def test_patch_requires_csrf():
    c, csrf = _auth_client()
    mid = _add(c, csrf, "1", _min(19)).json()["id"]
    r = c.patch(f"/api/admin/schedule/{mid}", json={"start_minute": _min(21)})
    assert r.status_code == 403


# --- Delete ----------------------------------------------------------------
def test_delete_removes_movie():
    c, csrf = _auth_client()
    mid = _add(c, csrf, "1", _min(19)).json()["id"]
    assert c.delete(
        f"/api/admin/schedule/{mid}", headers={"X-CSRF-Token": csrf}
    ).status_code == 200
    lineup = c.get("/api/admin/schedule").json()
    assert all(m["id"] != mid for m in lineup["movies"])


def test_delete_requires_csrf():
    c, csrf = _auth_client()
    mid = _add(c, csrf, "1", _min(19)).json()["id"]
    assert c.delete(f"/api/admin/schedule/{mid}").status_code == 403


def test_delete_missing_returns_404():
    c, csrf = _auth_client()
    r = c.delete("/api/admin/schedule/99999", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 404


# --- Active days -----------------------------------------------------------
def test_set_active_days():
    c, csrf = _auth_client()
    r = c.put(
        "/api/admin/schedule/active-days",
        json={"active_days": [0, 1, 2, 3, 4]},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200
    assert r.json()["active_days"] == [0, 1, 2, 3, 4]


def test_active_days_requires_csrf():
    c, _ = _auth_client()
    r = c.put(
        "/api/admin/schedule/active-days",
        json={"active_days": [0, 1, 2]},
    )
    assert r.status_code == 403
