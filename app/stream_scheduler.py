"""Channel controller: the loop that drives FFmpeg from the schedule.

Runs in a background thread. On each tick it asks the schedule which movie is
active *now* and reconciles the FFmpeg process to match:

* no active movie  -> stop the stream (schedule gap / off air)
* a new active movie -> start it at the correct live offset
* same movie, process died -> restart at the current offset, up to a retry cap

The channel is gated by an ``enabled`` flag toggled by the admin Start/Stop
controls. When disabled the controller keeps the stream stopped.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from sqlmodel import Session

from . import scheduler as sched
from .database import engine, get_settings_row
from .models import ScheduledMovie
from .stream_manager import StreamManager, StreamState, _utcnow


class ChannelController:
    def __init__(
        self,
        manager: StreamManager,
        *,
        tick_seconds: float = 5.0,
        healthy_reset_seconds: float = 60.0,
        backoff_seconds: float = 30.0,
    ) -> None:
        self.manager = manager
        self.tick_seconds = tick_seconds
        # A stream that has run cleanly this long has its crash budget cleared.
        self.healthy_reset_seconds = healthy_reset_seconds
        # After exhausting the retry budget, wait this long before trying again
        # (rather than giving up), so the channel self-heals from transient
        # problems like a briefly-unavailable mount or GPU hiccup.
        self.backoff_seconds = backoff_seconds
        self._enabled = False
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._target_id: Optional[int] = None
        self._cooldown_until: float = 0.0

    @property
    def enabled(self) -> bool:
        return self._enabled

    # --- admin controls -----------------------------------------------------
    def enable(self) -> None:
        self._enabled = True
        # Act immediately rather than waiting for the next tick.
        try:
            self._tick_once()
        except Exception:  # pragma: no cover - defensive
            pass

    def disable(self) -> None:
        self._enabled = False
        self.manager.stop()

    # --- loop lifecycle -----------------------------------------------------
    def start_loop(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop_loop(self) -> None:
        self._stop.set()
        self.manager.stop()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick_once()
            except Exception:  # pragma: no cover - never let the loop die
                pass
            self._stop.wait(self.tick_seconds)

    # --- reconciliation -----------------------------------------------------
    def _tick_once(self) -> None:
        if not self._enabled:
            return
        with Session(engine) as session:
            row = get_settings_row(session)
            active = sched.active_movie(session)
            mgr = self.manager

            if active is None:
                if mgr.state in (StreamState.streaming, StreamState.starting) or mgr.is_process_alive():
                    mgr.stop()
                self._target_id = None
                self._cooldown_until = 0.0
                return

            playing_correct = (
                mgr.current_movie_id == active.id
                and mgr.state == StreamState.streaming
                and mgr.is_process_alive()
            )
            if playing_correct:
                # Clear the crash budget once a stream has run cleanly for a
                # while, so an isolated later crash still recovers instead of
                # counting toward the give-up cap from earlier failures.
                if (
                    mgr.started_at
                    and (_utcnow() - mgr.started_at).total_seconds()
                    >= self.healthy_reset_seconds
                ):
                    mgr.reset_retry()
                    self._cooldown_until = 0.0
                self._target_id = active.id
                return

            # We are not correctly streaming the active movie: (re)start it.
            switching = self._target_id != active.id
            self._target_id = active.id
            if switching:
                # A genuinely new target — fresh budget, no backoff.
                mgr.reset_retry()
                self._cooldown_until = 0.0
            elif mgr.state == StreamState.streaming:
                # Same movie but the process died.
                mgr.notice_exit()

            # Rapid repeated failures on the same target: back off, then reset
            # and keep trying. The channel never permanently gives up.
            if not switching and mgr.retry_count >= mgr.max_retries:
                if time.monotonic() < self._cooldown_until:
                    return
                self._cooldown_until = time.monotonic() + self.backoff_seconds
                mgr.reset_retry()

            mgr.retry_count += 1
            self._launch(active, sched.playback_offset_seconds(active), row)

    def _launch(self, movie: ScheduledMovie, offset: float, row) -> None:
        self.manager.start(
            movie_id=movie.id,
            title=movie.title,
            rating_key=movie.plex_rating_key,
            source_path=movie.source_path,
            offset_seconds=offset,
            maximum_resolution=row.maximum_resolution,
            video_bitrate_kbps=row.video_bitrate_kbps,
            audio_bitrate_kbps=row.audio_bitrate_kbps,
            encoder=row.encoder,
            preset=row.encoder_preset,
        )
