"""Central logging setup.

Logs go to stdout so they surface in ``docker logs``. We deliberately never log
secrets — the Plex token, admin password, session cookies, or the app secret.
Helpers here format the *safe* facts the brief asks us to record.
"""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger("movie_channel")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers = [handler]
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"movie_channel.{name}")
