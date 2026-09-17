"""An upgrade must not cost a working install its model.

Before accounts, a server reached its model through one global credential per
provider. Environments now name ``geny_router`` and the route decides — so an
install that upgrades with credentials but no accounts cannot start a session
at all, and tells a user to add the account they configured years ago.

The mapping has one subtle case and one dangerous one:

* ``in_modal_login`` / ``host_mount`` mean "the login in this machine's own
  ~/.claude" — which is ``system``, NOT ``login``. ``login`` points the CLI at
  a fresh per-account directory that nobody has signed into, so the adopted
  account would report itself signed out and answer nothing.
* It must run ONCE. Running again on a server that already has accounts would
  duplicate them on every boot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from service.llm_accounts.adopt_legacy import adopt_legacy_credentials, plan_legacy_accounts
from service.llm_accounts.secrets import SecretStore
from service.llm_accounts.service import AccountService
from tests.service.llm_accounts.test_account_service import _FakeDb


class _Creds:
    anthropic_api_key = ""
    openai_api_key = ""
    google_api_key = ""
    base_url = ""
    ollama_base_url = ""
    lmstudio_base_url = ""
    custom_base_url = ""


class _Cli:
    enabled = False
    auth_mode = "host_mount"
    api_key = ""


def creds(**kwargs: Any) -> _Creds:
    c = _Creds()
    for key, value in kwargs.items():
        setattr(c, key, value)
    return c


def cli(**kwargs: Any) -> _Cli:
    c = _Cli()
    for key, value in kwargs.items():
        setattr(c, key, value)
    return c


class TestMapping:
    def test_nothing_configured_adopts_nothing(self) -> None:
        assert plan_legacy_accounts(creds(), cli()) == []

    def test_an_api_key_becomes_an_account_with_its_key(self) -> None:
        plan = plan_legacy_accounts(creds(openai_api_key="sk-live"), cli())
        assert [p["kind"] for p in plan] == ["openai"]
        assert plan[0]["secret"] == "sk-live"

    def test_a_modal_login_maps_to_the_machines_own_claude(self) -> None:
        """NOT 'login' — that would point the CLI at an empty per-account
        directory and the adopted account would answer nothing."""
        plan = plan_legacy_accounts(creds(), cli(enabled=True, auth_mode="in_modal_login"))
        assert plan[0]["claude"]["authMethod"] == "system"
        assert "secret" not in plan[0]

    def test_a_host_mount_maps_the_same_way(self) -> None:
        plan = plan_legacy_accounts(creds(), cli(enabled=True, auth_mode="host_mount"))
        assert plan[0]["claude"]["authMethod"] == "system"

    def test_a_setup_token_is_carried_over(self) -> None:
        plan = plan_legacy_accounts(creds(), cli(enabled=True, auth_mode="setup_token", api_key="sk-ant-oat"))
        assert plan[0]["claude"]["authMethod"] == "token"
        assert plan[0]["secret"] == "sk-ant-oat"

    def test_a_console_key_is_carried_over(self) -> None:
        plan = plan_legacy_accounts(creds(), cli(enabled=True, auth_mode="api_key", api_key="sk-ant"))
        assert plan[0]["claude"]["authMethod"] == "api_key"
        assert plan[0]["secret"] == "sk-ant"

    def test_a_setup_token_mode_with_no_token_falls_back_to_the_machine(self) -> None:
        plan = plan_legacy_accounts(creds(), cli(enabled=True, auth_mode="setup_token"))
        assert plan[0]["claude"]["authMethod"] == "system"

    def test_a_disabled_cli_backend_is_not_adopted(self) -> None:
        assert plan_legacy_accounts(creds(), cli(enabled=False, api_key="sk")) == []

    def test_the_subscription_answers_first(self) -> None:
        """The plan order becomes the default route, and on a working install
        the subscription is what has been answering."""
        plan = plan_legacy_accounts(creds(openai_api_key="sk", anthropic_api_key="sk2"),
                                    cli(enabled=True))
        assert [p["kind"] for p in plan] == ["claude_code", "anthropic", "openai"]

    def test_local_endpoints_are_adopted_by_address(self) -> None:
        plan = plan_legacy_accounts(creds(ollama_base_url="http://localhost:11434/v1"), cli())
        assert plan[0]["kind"] == "ollama"
        assert plan[0]["baseUrl"] == "http://localhost:11434/v1"

    def test_an_empty_string_is_not_a_credential(self) -> None:
        assert plan_legacy_accounts(creds(openai_api_key="   "), cli()) == []


class _Config:
    def __init__(self, creds_obj: Any, cli_obj: Any) -> None:
        self._creds, self._cli = creds_obj, cli_obj

    def load_config(self, cls: Any) -> Any:
        return self._cli if 'CLI' in cls.__name__ else self._creds


class TestAdoption:
    @pytest.fixture()
    def service(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AccountService:
        monkeypatch.setenv("GENY_LLM_ACCOUNTS_ROOT", str(tmp_path / "accounts"))
        return AccountService(_FakeDb(), SecretStore(tmp_path / "secrets.json"))

    def test_it_creates_the_accounts_and_the_route_follows(self, service: AccountService) -> None:
        config = _Config(creds(openai_api_key="sk-live"), cli(enabled=True))
        assert adopt_legacy_credentials(service, config) == 2
        kinds = [a["kind"] for a in service.list_accounts()]
        assert kinds == ["claude_code", "openai"]
        assert service.default_route()["primary"]["accountId"] == service.list_accounts()[0]["id"]

    def test_the_secret_actually_moved(self, service: AccountService) -> None:
        adopt_legacy_credentials(service, _Config(creds(openai_api_key="sk-live"), cli()))
        account = service.list_accounts()[0]
        assert account["hasSecret"] is True
        assert service.secret_of(account["id"]) == "sk-live"

    def test_it_runs_once(self, service: AccountService) -> None:
        """Every boot after the first must be a no-op, or a server accumulates
        a duplicate set of accounts per restart."""
        config = _Config(creds(openai_api_key="sk-live"), cli(enabled=True))
        assert adopt_legacy_credentials(service, config) == 2
        assert adopt_legacy_credentials(service, config) == 0
        assert len(service.list_accounts()) == 2

    def test_an_account_the_user_already_has_is_not_duplicated(self, service: AccountService) -> None:
        service.create_account({"kind": "claude_code", "label": "mine"})
        config = _Config(creds(openai_api_key="sk-live"), cli(enabled=True))
        assert adopt_legacy_credentials(service, config) == 1
        kinds = sorted(a["kind"] for a in service.list_accounts())
        assert kinds == ["claude_code", "openai"]
        assert [a["label"] for a in service.list_accounts() if a["kind"] == "claude_code"] == ["mine"]

    def test_a_partial_adoption_is_finished_on_the_next_boot(self, service: AccountService) -> None:
        """The failure this was rewritten for: production created one account,
        failed on the second, and an 'is the table empty' gate then blocked
        the retry forever — a server permanently half-migrated."""
        config = _Config(creds(openai_api_key="sk-live"), cli(enabled=True))
        real_create = service.create_account
        calls = {"n": 0}

        def flaky(entry):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("database hiccup")
            return real_create(entry)

        service.create_account = flaky  # type: ignore[method-assign]
        assert adopt_legacy_credentials(service, config) == 1

        service.create_account = real_create  # type: ignore[method-assign]
        assert adopt_legacy_credentials(service, config) == 1
        assert sorted(a["kind"] for a in service.list_accounts()) == ["claude_code", "openai"]

    def test_a_completed_adoption_does_not_resurrect_a_deleted_account(
        self, service: AccountService
    ) -> None:
        """A user who deletes an adopted account must not be handed it back on
        the next restart — which is exactly what 'is the table empty' would
        have done once they deleted the last one."""
        config = _Config(creds(openai_api_key="sk-live"), cli(enabled=True))
        adopt_legacy_credentials(service, config)
        for account in service.list_accounts():
            service.delete_account(account["id"])
        assert adopt_legacy_credentials(service, config) == 0
        assert service.list_accounts() == []

    def test_a_fresh_install_adopts_nothing(self, service: AccountService) -> None:
        assert adopt_legacy_credentials(service, _Config(creds(), cli())) == 0

    def test_a_fresh_install_is_not_asked_again(self, service: AccountService) -> None:
        config = _Config(creds(), cli())
        assert adopt_legacy_credentials(service, config) == 0
        # Adding a legacy key later is not a migration — the product has
        # accounts now, and that is where a new credential goes.
        assert adopt_legacy_credentials(service, _Config(creds(openai_api_key="sk"), cli())) == 0

    def test_a_broken_config_does_not_stop_the_boot(self, service: AccountService) -> None:
        class _Exploding:
            def load_config(self, cls: Any) -> Any:
                raise RuntimeError("config store is down")

        assert adopt_legacy_credentials(service, _Exploding()) == 0
