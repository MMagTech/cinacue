"""Security-focused tests: headers, session cookie flags, and no data leaks."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# Fields that must never appear in any public response body.
FORBIDDEN = [
    "plex_token",
    "plex_url",
    "plex_path_prefix",
    "local_path_prefix",
    "source_path",
    "admin_password",
    "app_secret",
    "csrf",
    "password_hash",
]


def _assert_clean(text: str):
    low = text.lower()
    for f in FORBIDDEN:
        assert f not in low, f"leaked '{f}' in public response: {text[:200]}"


def test_security_headers_present():
    r = client.get("/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert r.headers.get("Referrer-Policy") == "no-referrer"


def test_public_routes_do_not_leak():
    for path in (
        "/api/public/status",
        "/api/public/now-playing",
        "/api/public/upcoming",
        "/api/public/channel-config",
    ):
        r = client.get(path)
        assert r.status_code == 200
        _assert_clean(r.text)


def test_session_cookie_is_httponly_and_samesite():
    c = TestClient(app)
    r = c.post("/api/admin/login", json={"password": "test-admin-password"})
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "mc_session=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()


def test_admin_status_requires_auth():
    # Channel status is admin-only; unauthenticated must be rejected.
    assert client.get("/api/admin/channel/status").status_code == 401
    assert client.get("/api/admin/diagnostics").status_code == 401


def test_openapi_has_no_public_write_routes():
    # The public API is read-only, with one intentional exception: submitting
    # the shared viewer access code. It mutates no server state — it only
    # rate-limits and sets an auth cookie — so it is allowed to be a POST.
    allowed_writes = {"/api/public/access"}
    spec = client.get("/openapi.json").json()
    for path, methods in spec["paths"].items():
        if path.startswith("/api/public/") and path not in allowed_writes:
            for verb in methods:
                assert verb.lower() in ("get", "head", "options"), (
                    f"public path {path} exposes write verb {verb}"
                )
