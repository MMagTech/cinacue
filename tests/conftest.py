"""Test configuration.

Point CONFIG_DIR / STREAM_DIR at temp locations and set a known admin password
*before* the app package (and its settings singleton) is imported.
"""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="movie-channel-tests-")
os.environ.setdefault("CONFIG_DIR", os.path.join(_tmp, "config"))
os.environ.setdefault("STREAM_DIR", os.path.join(_tmp, "stream"))
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("TZ", "America/New_York")

# A plain TestClient(app) does not fire the FastAPI lifespan, so tables would
# never be created and the admin account never seeded. Do it explicitly here,
# after the environment above is in place.
from app.database import init_db  # noqa: E402
from app import auth  # noqa: E402

init_db()
auth.seed_admin_from_env()
