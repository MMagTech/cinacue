"""Public status honesty: when a movie should be airing but the stream is in
error, /api/public/status reports ``stand_by`` (viewer shows the standby card)
instead of claiming ``on_air`` over a dead stream."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app import public_api
from app.database import engine, get_settings_row
from app.main import app
from app.models import ScheduledMovie
from app.stream_manager import StreamState

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_lineup():
    def wipe():
        with Session(engine) as s:
            s.exec(delete(ScheduledMovie))
            row = get_settings_row(s)
            row.active_days_mask = 127
            s.add(row)
            s.commit()

    wipe()
    yield
    wipe()


def _seed_active_movie() -> None:
    """A two-hour movie that started ten minutes ago in the channel tz."""
    with Session(engine) as s:
        row = get_settings_row(s)
        now = datetime.now(ZoneInfo(row.timezone))
        start = (now.hour * 60 + now.minute - 10) % 1440
        s.add(
            ScheduledMovie(
                plex_rating_key="sb1",
                title="Now Showing",
                year=2000,
                poster_url=None,
                runtime_ms=120 * 60_000,
                start_minute=start,
                source_path="/data/movies/now-showing.mkv",
            )
        )
        s.commit()


def test_stream_error_reports_stand_by(monkeypatch):
    _seed_active_movie()
    monkeypatch.setattr(public_api.manager, "state", StreamState.error)
    body = client.get("/api/public/status").json()
    assert body["state"] == "stand_by"
    assert body["now_playing"] is None


def test_streaming_reports_on_air(monkeypatch):
    _seed_active_movie()
    monkeypatch.setattr(public_api.manager, "state", StreamState.streaming)
    body = client.get("/api/public/status").json()
    assert body["state"] == "on_air"
    assert body["now_playing"]["title"] == "Now Showing"


def test_error_without_scheduled_movie_stays_off_air(monkeypatch):
    monkeypatch.setattr(public_api.manager, "state", StreamState.error)
    body = client.get("/api/public/status").json()
    assert body["state"] == "off_air"
