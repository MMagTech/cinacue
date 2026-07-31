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
        self.started_at = None
        self.stopped = 0

    def is_process_alive(self):
        return self.current_movie_id is not None

    def reset_retry(self):
        self.retry_count = 0

    def notice_exit(self):
        pass

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
    monkeypatch.setattr(
        ss.sched, "active_or_imminent_movie", lambda s, preroll=0: active
    )
    monkeypatch.setattr(
        ss.sched, "playback_offset_seconds", lambda m, tz, mask: 123
    )
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


# --- Self-healing source paths ----------------------------------------------
class _FakePlexClient:
    def get_movie(self, rating_key):
        return object()


def test_missing_source_reresolved_from_plex(monkeypatch, tmp_path):
    """The stored path is gone (Radarr upgrade); launch uses Plex's current one."""
    mv = FakeMovie(1)  # source_path points at a file that does not exist
    _patch(monkeypatch, mv)
    fresh = tmp_path / "upgraded.mkv"
    fresh.write_text("x")
    monkeypatch.setattr(ss.plex_service, "plex_configured", lambda: True)
    monkeypatch.setattr(ss.plex_service, "make_client", lambda row: _FakePlexClient())
    monkeypatch.setattr(ss.plex_service, "local_source_path", lambda m, row: str(fresh))
    fm = FakeManager()
    ctrl = ss.ChannelController(fm)
    ctrl.enable()
    assert fm.started["source_path"] == str(fresh)
    assert mv.source_path == str(fresh)


def test_existing_source_skips_plex(monkeypatch, tmp_path):
    """A healthy stored path launches directly — no Plex round-trip."""
    existing = tmp_path / "1.mkv"
    existing.write_text("x")
    mv = FakeMovie(1)
    mv.source_path = str(existing)
    _patch(monkeypatch, mv)
    calls: list[int] = []
    monkeypatch.setattr(
        ss.plex_service, "plex_configured", lambda: calls.append(1) or True
    )
    fm = FakeManager()
    ctrl = ss.ChannelController(fm)
    ctrl.enable()
    assert fm.started["source_path"] == str(existing)
    assert calls == []


def test_plex_error_falls_back_to_stored_path(monkeypatch):
    """Plex unreachable: launch with the stored path so retry/backoff applies."""
    mv = FakeMovie(1)
    _patch(monkeypatch, mv)
    monkeypatch.setattr(ss.plex_service, "plex_configured", lambda: True)

    def _boom(row):
        raise RuntimeError("plex down")

    monkeypatch.setattr(ss.plex_service, "make_client", _boom)
    fm = FakeManager()
    ctrl = ss.ChannelController(fm)
    ctrl.enable()
    assert fm.started["source_path"] == mv.source_path
