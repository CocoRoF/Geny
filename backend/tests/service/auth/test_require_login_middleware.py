"""Tests for the global RequireLoginMiddleware (secure-by-default login gate).

The contract:

* Every HTTP request needs a valid JWT UNLESS its path is public. This holds
  even for an endpoint that has NO ``Depends(require_auth)`` of its own — that
  is the whole point (a forgotten endpoint is protected automatically).
* Public paths (health, the login flow, the OAuth callback, static assets, the
  self-authenticating MCP bridge) pass without a token.
* API docs are NOT public.
* CORS preflight (OPTIONS) passes without a token.
* No-DB back-compat mirrors require_auth: allow when not strict, 503 when
  GENY_AUTH_STRICT is set.
* 401s carry CORS headers (CORS is the outer layer), so a cross-origin frontend
  can read them.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import service.auth.auth_middleware as mw  # noqa: E402
from service.auth.auth_middleware import RequireLoginMiddleware  # noqa: E402
from service.auth.auth_service import AuthService  # noqa: E402


@pytest.fixture
def auth_service(monkeypatch):
    svc = AuthService(app_db=None)
    svc._secret_key = "mw-test-secret-key-which-is-long-enough-32chars++"
    monkeypatch.setattr(mw, "get_auth_service", lambda: svc)
    monkeypatch.delenv("GENY_AUTH_STRICT", raising=False)
    return svc


def _build_app() -> FastAPI:
    """App wired exactly like main.py: gate added first (inner), CORS added
    second (outer). Includes a protected endpoint with NO require_auth and a
    couple of public routes so we can exercise the allowlist."""
    app = FastAPI()
    app.add_middleware(RequireLoginMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # A sensitive endpoint that FORGOT to declare require_auth — the gate must
    # still protect it.
    @app.get("/api/secret")
    async def secret():
        return {"ok": True}

    # Public allowlist members that actually exist on this test app.
    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    @app.get("/api/auth/status")
    async def status():
        return {"needs_setup": False}

    @app.get("/static/app.js")
    async def static_asset():
        return {"asset": True}

    # VTuber notification streams — intentionally public (plain EventSource
    # from cookieless overlay/connector display surfaces).
    @app.get("/api/vtuber/models/stream")
    async def vtuber_models_stream():
        return {"stream": "models"}

    @app.get("/api/vtuber/assignments/stream")
    async def vtuber_assignments_stream():
        return {"stream": "assignments"}

    # VTuber DATA endpoint — must stay gated (callers send a Bearer token).
    @app.get("/api/vtuber/models")
    async def vtuber_models():
        return {"models": []}

    return app


@pytest.fixture
def client(auth_service):
    return TestClient(_build_app())


def _token(svc: AuthService) -> str:
    return svc._create_token("admin", "admin")["access_token"]


def _auth_header(svc: AuthService) -> dict:
    return {"Authorization": f"Bearer {_token(svc)}"}


# ── secure-by-default: undeclared endpoint is still protected ─────────


def test_undeclared_endpoint_requires_auth(client):
    r = client.get("/api/secret")
    assert r.status_code == 401
    assert r.json()["detail"] == "Authentication required"


def test_undeclared_endpoint_passes_with_token(client, auth_service):
    r = client.get("/api/secret", headers=_auth_header(auth_service))
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_invalid_token_rejected(client):
    r = client.get("/api/secret", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid token"


def test_cookie_token_accepted(client, auth_service):
    client.cookies.set("geny_auth_token", _token(auth_service))
    r = client.get("/api/secret")
    assert r.status_code == 200


# ── public allowlist passes without a token ──────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/api/auth/status",
        "/static/app.js",
        "/api/vtuber/models/stream",
        "/api/vtuber/assignments/stream",
    ],
)
def test_public_paths_open(client, path):
    r = client.get(path)
    assert r.status_code == 200


def test_vtuber_data_endpoint_stays_gated(client):
    # The notification STREAMS are public, but the DATA endpoint they mirror
    # must still require a token (its callers send Bearer via apiCall).
    r = client.get("/api/vtuber/models")
    assert r.status_code == 401


def test_options_preflight_passes(client):
    # CORS preflight must not be blocked by the gate.
    r = client.options(
        "/api/secret",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code != 401


# ── docs are NOT public ──────────────────────────────────────────────


def test_openapi_is_gated(client):
    r = client.get("/openapi.json")
    assert r.status_code == 401


def test_docs_gated_but_reachable_with_token(client, auth_service):
    r = client.get("/openapi.json", headers=_auth_header(auth_service))
    assert r.status_code == 200


# ── 401 carries CORS headers (gate is inner, CORS is outer) ──────────


def test_401_has_cors_headers_for_cross_origin(client):
    r = client.get("/api/secret", headers={"Origin": "http://example.com"})
    assert r.status_code == 401
    # CORS is the outer layer, so it decorates the gate's 401. With
    # allow_credentials=True the spec forbids "*", so Starlette echoes the
    # request Origin — the header being present at all proves the ordering.
    assert r.headers.get("access-control-allow-origin") == "http://example.com"


# ── no-DB back-compat ────────────────────────────────────────────────


def test_no_db_allows_when_not_strict(monkeypatch):
    monkeypatch.setattr(mw, "get_auth_service", lambda: None)
    monkeypatch.delenv("GENY_AUTH_STRICT", raising=False)
    c = TestClient(_build_app())
    r = c.get("/api/secret")
    assert r.status_code == 200


def test_no_db_refuses_when_strict(monkeypatch):
    monkeypatch.setattr(mw, "get_auth_service", lambda: None)
    monkeypatch.setenv("GENY_AUTH_STRICT", "1")
    c = TestClient(_build_app())
    r = c.get("/api/secret")
    assert r.status_code == 503
