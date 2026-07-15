"""API tests: health, public read-only surface, and admin authorization."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# --- Health ----------------------------------------------------------------
def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


# --- Public surface --------------------------------------------------------
def test_public_status_ok_when_empty():
    r = client.get("/api/public/status")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] in ("on_air", "off_air")
    assert "timezone" in body


def test_public_channel_config_hides_secrets():
    r = client.get("/api/public/channel-config")
    assert r.status_code == 200
    body = r.json()
    # No sensitive fields should ever appear publicly.
    for forbidden in ("plex_token", "plex_url", "plex_path_prefix", "local_path_prefix"):
        assert forbidden not in body


def test_public_upcoming_is_list():
    r = client.get("/api/public/upcoming")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/public/status"),
        ("put", "/api/public/now-playing"),
        ("delete", "/api/public/upcoming"),
    ],
)
def test_public_routes_have_no_write_methods(method, path):
    # Public API must not expose write verbs.
    r = getattr(client, method)(path)
    assert r.status_code in (404, 405)


# --- Admin authorization ---------------------------------------------------
def test_admin_endpoints_require_auth():
    assert client.get("/api/admin/encoding").status_code == 401
    assert client.get("/api/admin/schedule").status_code == 401


def test_admin_write_requires_auth():
    r = client.patch("/api/admin/encoding", json={"video_bitrate_kbps": 6000})
    assert r.status_code == 401


def test_login_and_authorized_flow():
    c = TestClient(app)
    # Wrong password rejected.
    assert c.post("/api/admin/login", json={"password": "nope"}).status_code == 401

    # Correct password (seeded from ADMIN_PASSWORD in conftest).
    r = c.post("/api/admin/login", json={"password": "test-admin-password"})
    assert r.status_code == 200
    csrf = r.json()["csrf_token"]

    # Session now authorizes reads.
    assert c.get("/api/admin/encoding").status_code == 200
    assert c.get("/api/admin/schedule").status_code == 200

    # Write without CSRF header is rejected.
    assert c.patch(
        "/api/admin/encoding", json={"video_bitrate_kbps": 6000}
    ).status_code == 403

    # Write with CSRF header succeeds.
    ok = c.patch(
        "/api/admin/encoding",
        json={"video_bitrate_kbps": 6000},
        headers={"X-CSRF-Token": csrf},
    )
    assert ok.status_code == 200
    assert ok.json()["video_bitrate_kbps"] == 6000


def test_schedule_returns_lineup_and_active_days():
    c = TestClient(app)
    c.post("/api/admin/login", json={"password": "test-admin-password"})
    r = c.get("/api/admin/schedule")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["movies"], list)
    assert isinstance(body["active_days"], list)
    assert "timezone" in body
