"""Process-wide singletons for the stream manager and channel controller.

Isolated in its own module so both the API layer and the app lifespan can share
the same instances without import cycles.
"""
from __future__ import annotations

import time

from .config import settings
from .stream_manager import StreamManager
from .stream_scheduler import ChannelController

# Wall-clock start of the process, for the dashboard uptime readout.
app_started_at = time.time()

manager = StreamManager(
    settings.stream_dir,
    ffmpeg_bin="ffmpeg",
    ffprobe_bin="ffprobe",
)
controller = ChannelController(manager)
