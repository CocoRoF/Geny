"""The accounts API, over real HTTP.

Unit tests cover the service; this covers the wiring — that the routes are
mounted where the clients expect, that auth actually guards them, that the
request shapes the web UI and the connector send are the ones the server
parses, and that a login's events reach a listener as SSE frames.

Every one of those is a failure the service tests cannot see, and each would
show up as an empty page rather than an error.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from controller import llm_accounts_controller as module
from service.auth.auth_middleware import require_auth
from service.llm_accounts.secrets import SecretStore
from service.llm_accounts.service import AccountService
from tests.service.llm_accounts.test_account_service import _FakeDb


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("GENY_LLM_ACCOUNTS_ROOT", str(tmp_path / "accounts"))
    service = AccountService(_FakeDb(), SecretStore(tmp_path / "secrets.json"))
    monkeypatch.setattr(module, "get_account_service", lambda: service)

    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[require_auth] = lambda: {"username": "admin"}
    return TestClient(app)


class TestCatalogue:
    def test_the_kinds_the_ui_renders_are_served(self, client: TestClient) -> None:
        body = client.get("/api/llm-accounts/kinds").json()
        assert "claude_code" in body["kinds"]
        assert "codex" in body["kinds"]
        assert body["kinds"]["claude_code"]["engineProvider"] == "geny_claude_code"
        assert body["efforts"]

    def test_every_kind_declares_what_it_needs(self, client: TestClient) -> None:
        for name, info in client.get("/api/llm-accounts/kinds").json()["kinds"].items():
            assert info["label"] and info["hint"], name
            assert info["secret"] in ("api_key", "optional_key", "none", "oauth"), name


class TestAccounts:
    def test_an_empty_server_lists_nothing_and_routes_nowhere(self, client: TestClient) -> None:
        body = client.get("/api/llm-accounts").json()
        assert body["accounts"] == []
        assert body["defaultRoute"] == {"primary": None, "fallbacks": []}

    def test_create_read_update_delete(self, client: TestClient) -> None:
        created = client.post("/api/llm-accounts", json={"kind": "claude_code"}).json()["account"]
        assert created["kind"] == "claude_code"

        patched = client.patch(f"/api/llm-accounts/{created['id']}",
                               json={"label": "일하는 계정"}).json()["account"]
        assert patched["label"] == "일하는 계정"

        assert client.delete(f"/api/llm-accounts/{created['id']}").json() == {"ok": True}
        assert client.get("/api/llm-accounts").json()["accounts"] == []

    def test_a_bad_kind_is_a_400_with_a_reason(self, client: TestClient) -> None:
        res = client.post("/api/llm-accounts", json={"kind": "telepathy"})
        assert res.status_code == 400
        assert "telepathy" in res.json()["detail"]

    def test_an_api_account_without_a_key_is_refused(self, client: TestClient) -> None:
        assert client.post("/api/llm-accounts", json={"kind": "anthropic"}).status_code == 400

    def test_a_missing_account_is_a_404(self, client: TestClient) -> None:
        assert client.patch("/api/llm-accounts/nope", json={"label": "x"}).status_code == 404
        assert client.delete("/api/llm-accounts/nope").status_code == 404

    def test_the_secret_never_leaves_the_server(self, client: TestClient) -> None:
        res = client.post("/api/llm-accounts", json={"kind": "anthropic", "secret": "sk-do-not-leak"})
        assert res.json()["account"]["hasSecret"] is True
        assert "sk-do-not-leak" not in json.dumps(client.get("/api/llm-accounts").json())

    def test_reordering_changes_which_account_answers_first(self, client: TestClient) -> None:
        first = client.post("/api/llm-accounts", json={"kind": "claude_code"}).json()["account"]
        second = client.post("/api/llm-accounts", json={"kind": "codex"}).json()["account"]
        client.post("/api/llm-accounts/reorder", json={"order": [second["id"], first["id"]]})
        assert client.get("/api/llm-accounts").json()["defaultRoute"]["primary"]["accountId"] == second["id"]


class TestLoginFlow:
    def test_a_claude_login_needs_a_claude_account(self, client: TestClient) -> None:
        codex = client.post("/api/llm-accounts", json={"kind": "codex"}).json()["account"]
        res = client.post(f"/api/llm-accounts/{codex['id']}/claude/login", json={"console": False})
        assert res.status_code == 400

    def test_a_codex_login_needs_a_codex_account(self, client: TestClient) -> None:
        claude = client.post("/api/llm-accounts", json={"kind": "claude_code"}).json()["account"]
        assert client.post(f"/api/llm-accounts/{claude['id']}/codex/login").status_code == 400

    def test_code_for_a_finished_job_is_a_404_not_a_hang(self, client: TestClient) -> None:
        res = client.post("/api/llm-accounts/login/input", json={"jobId": "gone", "text": "123"})
        assert res.status_code == 404

    def test_importing_with_no_cli_login_says_so(self, client: TestClient, tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "nothing"))
        account = client.post("/api/llm-accounts", json={"kind": "codex"}).json()["account"]
        assert client.post(f"/api/llm-accounts/{account['id']}/codex/import-cli").status_code == 404

    def test_events_replay_what_the_job_already_said(self, client: TestClient) -> None:
        """Opening the stream a moment late must not lose the URL the whole
        flow hangs on."""
        service = module.get_account_service()
        service.events.publish({"jobId": "j1", "accountId": "a1", "type": "url",
                                "url": "https://claude.ai/oauth"})
        service.events.publish({"jobId": "j1", "accountId": "a1", "type": "done", "ok": True})

        # The stream ends by itself once the job reports its verdict — a
        # login is a bounded thing, and a connection left open per sign-in is
        # a leak.
        response = client.get("/api/llm-accounts/events?job_id=j1")
        assert response.status_code == 200
        frames: List[Dict[str, Any]] = [
            json.loads(line[5:].strip())
            for line in response.text.splitlines()
            if line.startswith("data:")
        ]
        assert [f["type"] for f in frames] == ["url", "done"]
        assert frames[0]["url"] == "https://claude.ai/oauth"

    def test_another_job_s_events_are_not_mine(self, client: TestClient) -> None:
        service = module.get_account_service()
        service.events.publish({"jobId": "other", "type": "url", "url": "https://elsewhere"})
        service.events.publish({"jobId": "mine", "type": "done", "ok": True})
        response = client.get("/api/llm-accounts/events?job_id=mine")
        frames = [
            json.loads(line[5:].strip())
            for line in response.text.splitlines()
            if line.startswith("data:")
        ]
        assert [f["type"] for f in frames] == ["done"]


class TestAuthGuard:
    def test_every_route_is_behind_auth(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """These calls read and write live credentials; an unguarded one is a
        credential store on the open internet."""
        monkeypatch.setenv("GENY_LLM_ACCOUNTS_ROOT", str(tmp_path / "accounts"))
        service = AccountService(_FakeDb(), SecretStore(tmp_path / "secrets.json"))
        monkeypatch.setattr(module, "get_account_service", lambda: service)

        app = FastAPI()
        app.include_router(module.router)

        unguarded = []
        for route in app.routes:
            dependant = getattr(route, "dependant", None)
            if dependant is None:
                continue
            names = {getattr(d.call, "__name__", "") for d in dependant.dependencies}
            if "require_auth" not in names:
                unguarded.append(getattr(route, "path", "?"))
        assert unguarded == []
