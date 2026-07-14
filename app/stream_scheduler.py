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

from sqlmodel import Session

from . import scheduler as sched
from .database import engine, get_settings_row
from .models import ScheduledMovie
from .stream_manager import StreamManager, StreamState


class ChannelController:
    def __init__(self, manager: StreamManager, *, tick_seconds: float = 5.0) -> None:
        self.manager = manager
        self.tick_seconds = tick_seconds
        self._enabled = False
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

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
                return

            if mgr.current_movie_id != active.id:
                mgr.reset_retry()
                self._launch(active, sched.playback_offset_seconds(active), row)
                return

            # Same movie is scheduled — make sure ffmpeg is still alive.
            if mgr.state == StreamState.streaming and not mgr.is_process_alive():
                mgr.notice_exit()
                if mgr.retry_count < mgr.max_retries:
                    mgr.retry_count += 1
                    self._launch(active, sched.playback_offset_seconds(active), row)
                else:
                    mgr._fail("ffmpeg exited repeatedly; giving up")

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
