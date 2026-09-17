"""Accounts, and the route a session resolves from them.

The properties that matter here are the ones whose absence is silent:

* Two Claude Code logins must not share a credential directory, or signing
  into the second signs the first out and neither user is told.
* A Codex refresh token is single-use. If a rotation is not persisted the
  account is logged out on the next turn, with no error until then.
* Deleting an account must take its credential directory with it, or a
  recreated account inherits the deleted one's identity.
* A route that names a disabled or deleted account must degrade to its next
  hop, not raise: a route outlives the accounts it was built from.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from service.database.models.llm_account import LLMAccountModel
from service.llm_accounts.secrets import SecretStore
from service.llm_accounts.service import AccountService


class _FakeDb:
    """The slice of AppDatabaseManager the service uses, in memory.

    Reads return MODEL objects, because that is what the real manager returns
    (``model_class.from_dict(dict(row))``). An earlier version of this fake
    returned dicts — every test passed and the service raised
    ``'LLMAccountModel' object has no attribute 'get'`` on its first real
    query in production. A fake that is kinder than the real thing does not
    test anything.
    """

    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []
        self._next_id = 1

    def insert(self, model: LLMAccountModel) -> Dict[str, Any]:
        row = {k: v for k, v in model.__dict__.items() if not k.startswith("_")}
        row["id"] = self._next_id
        self._next_id += 1
        self.rows.append(row)
        return row

    def update(self, model: LLMAccountModel) -> bool:
        for i, row in enumerate(self.rows):
            if row.get("id") == model.id:
                merged = {k: v for k, v in model.__dict__.items() if not k.startswith("_")}
                self.rows[i] = {**row, **merged}
                return True
        return False

    def delete(self, model_class: Any, record_id: int) -> bool:
        before = len(self.rows)
        self.rows = [r for r in self.rows if r.get("id") != record_id]
        return len(self.rows) != before

    @staticmethod
    def _model(row: Dict[str, Any]) -> LLMAccountModel:
        return LLMAccountModel.from_dict(dict(row))

    def find_all(self, model_class: Any, limit: int = 500, offset: int = 0) -> List[Any]:
        return [self._model(r) for r in self.rows]

    def find_by_condition(self, model_class: Any, conditions: Dict[str, Any],
                          limit: int = 100, **kwargs: Any) -> List[Any]:
        out = [self._model(r) for r in self.rows
               if all(r.get(k) == v for k, v in conditions.items())]
        return out[:limit]


@pytest.fixture()
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AccountService:
    monkeypatch.setenv("GENY_LLM_ACCOUNTS_ROOT", str(tmp_path / "accounts"))
    return AccountService(_FakeDb(), SecretStore(tmp_path / "secrets.json"))


# ── creating accounts ────────────────────────────────────────────────


class TestCreate:
    def test_an_unknown_kind_is_refused(self, service: AccountService) -> None:
        with pytest.raises(ValueError):
            service.create_account({"kind": "telepathy"})

    def test_an_api_kind_without_a_key_is_refused(self, service: AccountService) -> None:
        with pytest.raises(ValueError):
            service.create_account({"kind": "anthropic"})

    def test_a_compatible_endpoint_needs_an_address(self, service: AccountService) -> None:
        with pytest.raises(ValueError):
            service.create_account({"kind": "openai_compatible", "secret": "k"})

    def test_a_subscription_login_needs_nothing_up_front(self, service: AccountService) -> None:
        account = service.create_account({"kind": "claude_code"})
        assert account["kind"] == "claude_code"
        assert account["hasSecret"] is False
        assert account["engineProvider"] == "geny_claude_code"

    def test_labels_do_not_collide(self, service: AccountService) -> None:
        first = service.create_account({"kind": "claude_code"})
        second = service.create_account({"kind": "claude_code"})
        assert first["label"] != second["label"]

    def test_the_secret_never_comes_back_out(self, service: AccountService) -> None:
        account = service.create_account({"kind": "anthropic", "secret": "sk-secret"})
        assert account["hasSecret"] is True
        assert "sk-secret" not in json.dumps(account)


class TestClaudeIsolation:
    def test_each_login_owns_its_own_config_dir(self, service: AccountService) -> None:
        """Otherwise the second login signs the first one out, silently."""
        a = service.create_account({"kind": "claude_code"})
        b = service.create_account({"kind": "claude_code"})
        assert service.claude_config_dir(a["id"]) != service.claude_config_dir(b["id"])

    def test_the_env_points_the_cli_at_that_account(self, service: AccountService) -> None:
        account = service.create_account({"kind": "claude_code"})
        row = service._row(account["id"])
        env = service.claude_env(row)
        assert env["CLAUDE_CONFIG_DIR"] == service.claude_config_dir(account["id"])
        assert "ANTHROPIC_API_KEY" not in env

    def test_deleting_takes_the_credential_directory_with_it(
        self, service: AccountService, tmp_path: Path
    ) -> None:
        """A recreated account must not inherit a deleted one's login."""
        account = service.create_account({"kind": "claude_code"})
        config_dir = Path(service.claude_config_dir(account["id"]))
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / ".credentials.json").write_text("{}", encoding="utf-8")

        assert service.delete_account(account["id"]) is True
        assert not config_dir.exists()
        assert service.get_account(account["id"]) is None


class TestSecrets:
    def test_a_rotated_secret_replaces_the_old_one(self, service: AccountService) -> None:
        account = service.create_account({"kind": "anthropic", "secret": "old"})
        service.update_account(account["id"], {"secret": "new"})
        assert service.secret_of(account["id"]) == "new"

    def test_clearing_a_secret_clears_the_flag_too(self, service: AccountService) -> None:
        account = service.create_account({"kind": "anthropic", "secret": "k"})
        updated = service.update_account(account["id"], {"secret": ""})
        assert updated["hasSecret"] is False
        assert service.secret_of(account["id"]) == ""

    def test_the_file_is_not_world_readable(self, service: AccountService, tmp_path: Path) -> None:
        service.create_account({"kind": "anthropic", "secret": "k"})
        mode = (tmp_path / "secrets.json").stat().st_mode & 0o777
        assert mode == 0o600

    def test_deleting_an_account_deletes_its_secret(self, service: AccountService) -> None:
        account = service.create_account({"kind": "anthropic", "secret": "k"})
        service.delete_account(account["id"])
        assert service.secret_of(account["id"]) == ""


# ── routes ───────────────────────────────────────────────────────────


class TestRoute:
    @pytest.mark.asyncio
    async def test_a_hop_carries_what_its_backend_needs(self, service: AccountService) -> None:
        account = service.create_account({"kind": "anthropic", "secret": "sk-k"})
        hop = await service.resolve_hop({"accountId": account["id"], "model": "claude-opus-5"})
        assert hop["engineProvider"] == "anthropic"
        assert hop["model"] == "claude-opus-5"
        assert hop["apiKey"] == "sk-k"

    @pytest.mark.asyncio
    async def test_a_claude_hop_runs_token_only_by_default(self, service: AccountService) -> None:
        """The harness keeps the tool loop; the CLI only generates tokens."""
        account = service.create_account({"kind": "claude_code"})
        hop = await service.resolve_hop({"accountId": account["id"]})
        assert hop["engineProvider"] == "geny_claude_code"
        assert hop["options"]["config_dir"] == service.claude_config_dir(account["id"])

    @pytest.mark.asyncio
    async def test_agent_mode_hands_the_loop_back_to_the_cli(self, service: AccountService) -> None:
        account = service.create_account({"kind": "claude_code"})
        service.update_account(account["id"], {"claude": {"mode": "agent"}})
        hop = await service.resolve_hop({"accountId": account["id"]})
        assert hop["engineProvider"] == "claude_code_cli"

    @pytest.mark.asyncio
    async def test_a_hop_with_no_model_falls_back_to_the_kind_default(
        self, service: AccountService
    ) -> None:
        account = service.create_account({"kind": "claude_code"})
        hop = await service.resolve_hop({"accountId": account["id"]})
        assert hop["model"] == "sonnet"

    @pytest.mark.asyncio
    async def test_a_disabled_account_is_dropped_not_raised(self, service: AccountService) -> None:
        """A route outlives the accounts it names — it should degrade to its
        next hop, not stop the conversation."""
        first = service.create_account({"kind": "anthropic", "secret": "k1"})
        second = service.create_account({"kind": "openai", "secret": "k2"})
        service.update_account(first["id"], {"enabled": False})
        targets = await service.resolve_route({
            "primary": {"accountId": first["id"], "model": "a"},
            "fallbacks": [{"accountId": second["id"], "model": "b"}],
        })
        assert [t["accountId"] for t in targets] == [second["id"]]

    @pytest.mark.asyncio
    async def test_a_deleted_account_is_dropped_too(self, service: AccountService) -> None:
        account = service.create_account({"kind": "anthropic", "secret": "k"})
        targets = await service.resolve_route({
            "primary": {"accountId": account["id"], "model": "a"},
            "fallbacks": [{"accountId": "gone-forever", "model": "b"}],
        })
        assert [t["accountId"] for t in targets] == [account["id"]]

    @pytest.mark.asyncio
    async def test_the_order_of_a_route_is_the_order_of_its_hops(
        self, service: AccountService
    ) -> None:
        a = service.create_account({"kind": "anthropic", "secret": "k"})
        b = service.create_account({"kind": "openai", "secret": "k"})
        targets = await service.resolve_route({
            "primary": {"accountId": b["id"]},
            "fallbacks": [{"accountId": a["id"]}],
        })
        assert [t["accountId"] for t in targets] == [b["id"], a["id"]]

    @pytest.mark.asyncio
    async def test_effort_comes_from_the_hop_then_the_account(
        self, service: AccountService
    ) -> None:
        account = service.create_account({"kind": "openai", "secret": "k", "effort": "low"})
        default = await service.resolve_hop({"accountId": account["id"]})
        assert default["options"]["effort"] == "low"
        pinned = await service.resolve_hop({"accountId": account["id"], "effort": "high"})
        assert pinned["options"]["effort"] == "high"

    def test_the_default_route_is_every_enabled_account_in_order(
        self, service: AccountService
    ) -> None:
        a = service.create_account({"kind": "claude_code"})
        b = service.create_account({"kind": "anthropic", "secret": "k"})
        c = service.create_account({"kind": "openai", "secret": "k"})
        service.update_account(b["id"], {"enabled": False})
        route = service.default_route()
        assert route["primary"]["accountId"] == a["id"]
        assert [f["accountId"] for f in route["fallbacks"]] == [c["id"]]

    def test_reordering_changes_the_default_route(self, service: AccountService) -> None:
        a = service.create_account({"kind": "claude_code"})
        b = service.create_account({"kind": "anthropic", "secret": "k"})
        service.reorder([b["id"], a["id"]])
        assert service.default_route()["primary"]["accountId"] == b["id"]

    def test_no_accounts_means_an_empty_route_not_a_crash(self, service: AccountService) -> None:
        assert service.default_route() == {"primary": None, "fallbacks": []}


class TestCodexTokens:
    @pytest.mark.asyncio
    async def test_a_refreshed_token_set_is_persisted_immediately(
        self, service: AccountService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A Codex refresh token is single-use: a rotation that is not stored
        logs the account out on the next turn, with nothing said."""
        from service.llm_accounts import codex_auth

        account = service.create_account({"kind": "codex"})
        service._secrets.set(account["id"], {"access_token": "old", "refresh_token": "r1"})

        async def fake_ensure(tokens: Dict[str, Any], **_: Any):
            return {"access_token": "new", "refresh_token": "r2"}, True

        monkeypatch.setattr(codex_auth, "ensure_fresh", fake_ensure)
        hop = await service.resolve_hop({"accountId": account["id"]})
        assert hop["options"]["tokens"]["access_token"] == "new"
        assert service.codex_tokens(account["id"])["refresh_token"] == "r2"

    @pytest.mark.asyncio
    async def test_a_dead_refresh_token_still_produces_a_hop(
        self, service: AccountService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """So the router can fail over from it, rather than the whole route
        failing to resolve."""
        from service.llm_accounts import codex_auth

        account = service.create_account({"kind": "codex"})
        service._secrets.set(account["id"], {"access_token": "old", "refresh_token": "r1"})

        async def fake_ensure(tokens: Dict[str, Any], **_: Any):
            raise ValueError("refresh failed")

        monkeypatch.setattr(codex_auth, "ensure_fresh", fake_ensure)
        hop = await service.resolve_hop({"accountId": account["id"]})
        assert hop is not None
        assert hop["engineProvider"] == "geny_codex"

    def test_importing_a_cli_login_copies_it(
        self, service: AccountService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A copy, not a share: two holders of one single-use refresh token
        rotate each other out."""
        home = tmp_path / "codex"
        home.mkdir()
        (home / "auth.json").write_text(
            json.dumps({"tokens": {"access_token": "at", "refresh_token": "rt"}}),
            encoding="utf-8",
        )
        monkeypatch.setenv("CODEX_HOME", str(home))
        account = service.create_account({"kind": "codex"})
        assert service.import_codex_cli_login(account["id"]) is True
        assert service.codex_tokens(account["id"])["access_token"] == "at"

    def test_importing_with_no_cli_login_says_so(
        self, service: AccountService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "nothing-here"))
        account = service.create_account({"kind": "codex"})
        assert service.import_codex_cli_login(account["id"]) is False
