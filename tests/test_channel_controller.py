"""Channel controller reconciliation tests (with a fake manager)."""
from __future__ import annotations

import contextlib

from app import stream_scheduler as ss
from app.models import Settings as SettingsRow
from app.stream_manager import StreamState


class FakeManager:
    def __init__(self):
        self.max_retries = 3
        self.retry_count = 0
        self.state = StreamState.offline
        self.current_movie_id = None
        self.started = None
        self.stopped = 0

    def is_process_alive(self):
        return self.current_movie_id is not None

    def reset_retry(self):
        self.retry_count = 0

    def stop(self):
        self.stopped += 1
        self.current_movie_id = None
        self.state = StreamState.offline

    def start(self, **kw):
        self.started = kw
        self.current_movie_id = kw["movie_id"]
        self.state = StreamState.streaming
        return True


class FakeMovie:
    def __init__(self, mid=1):
        self.id = mid
        self.title = f"Movie {mid}"
        self.plex_rating_key = str(mid)
        self.source_path = f"/media/movies/{mid}.mkv"


def _patch(monkeypatch, active):
    @contextlib.contextmanager
    def fake_session(_engine):
        yield object()

    monkeypatch.setattr(ss, "Session", fake_session)
    monkeypatch.setattr(ss, "get_settings_row", lambda s: SettingsRow(id=1))
    monkeypatch.setattr(ss.sched, "active_movie", lambda s: active)
    monkeypatch.setattr(ss.sched, "playback_offset_seconds", lambda m: 123)
    monkeypatch.setattr(ss.sched, "next_movie", lambda s: None)


def test_disabled_does_nothing(monkeypatch):
    _patch(monkeypatch, FakeMovie(1))
    fm = FakeManager()
    ctrl = ss.ChannelController(fm)
    ctrl._tick_once()  # not enabled
    assert fm.started is None


def test_enable_starts_active_movie(monkeypatch):
    _patch(monkeypatch, FakeMovie(7))
    fm = FakeManager()
    ctrl = ss.ChannelController(fm)
    ctrl.enable()
    assert fm.started is not None
    assert fm.started["movie_id"] == 7
    assert fm.started["offset_seconds"] == 123
    assert fm.started["encoder"] == "h264_nvenc"


def test_gap_stops_stream(monkeypatch):
    _patch(monkeypatch, FakeMovie(1))
    fm = FakeManager()
    ctrl = ss.ChannelController(fm)
    ctrl.enable()  # starts movie 1
    assert fm.current_movie_id == 1
    # Now the schedule gap: no active movie.
    _patch(monkeypatch, None)
    ctrl._tick_once()
    assert fm.stopped >= 1
    assert fm.current_movie_id is None


def test_transition_to_new_movie(monkeypatch):
    _patch(monkeypatch, FakeMovie(1))
    fm = FakeManager()
    ctrl = ss.ChannelController(fm)
    ctrl.enable()
    assert fm.current_movie_id == 1
    _patch(monkeypatch, FakeMovie(2))
    ctrl._tick_once()
    assert fm.current_movie_id == 2
    assert fm.started["movie_id"] == 2


def test_disable_stops(monkeypatch):
    _patch(monkeypatch, FakeMovie(1))
    fm = FakeManager()
    ctrl = ss.ChannelController(fm)
    ctrl.enable()
    ctrl.disable()
    assert ctrl.enabled is False
    assert fm.stopped >= 1
