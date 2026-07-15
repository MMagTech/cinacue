"""Tests for the shared viewer access code: gating, cookie, and lockout."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import auth
from app.config import settings
from app.main import app


def test_open_when_no_code(monkeypatch):
    monkeypatch.setattr(settings, "public_access_code", "")
    c = TestClient(app)
    assert c.get("/api/public/access-state").json()["required"] is False
    assert c.get("/api/public/status").status_code == 200


def test_gated_blocks_without_code(monkeypatch):
    monkeypatch.setattr(settings, "public_access_code", "letmein")
    auth._access_attempts.clear()
    c = TestClient(app)
    state = c.get("/api/public/access-state").json()
    assert state["required"] is True and state["granted"] is False
    assert c.get("/api/public/status").status_code == 401
    # the raw stream is gated too, not just the API
    assert c.get("/stream/channel.m3u8").status_code == 401


def test_correct_code_grants_access(monkeypatch):
    monkeypatch.setattr(settings, "public_access_code", "letmein")
    auth._access_attempts.clear()
    c = TestClient(app)
    assert c.post("/api/public/access", json={"code": "nope"}).status_code == 401
    assert c.post("/api/public/access", json={"code": "letmein"}).status_code == 200
    # cookie is now held by the client -> viewer is reachable
    assert c.get("/api/public/status").status_code == 200
    assert c.get("/api/public/access-state").json()["granted"] is True


def test_lockout_after_repeated_wrong_codes(monkeypatch):
    monkeypatch.setattr(settings, "public_access_code", "letmein")
    auth._access_attempts.clear()
    c = TestClient(app)
    for _ in range(8):
        c.post("/api/public/access", json={"code": "wrong"})
    # locked out — even the correct code is refused during the cooldown
    assert c.post("/api/public/access", json={"code": "letmein"}).status_code == 429
