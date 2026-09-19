"""The number that decides whether a long conversation survives.

``context_window_budget`` sizes Stage-2 proactive compaction and the Stage-4
headroom guard. Geny never set it, so every session compacted at a fraction of
200_000 no matter which model answered — six times too late for a local server
launched at 32k, where the request overflows before compaction ever fires. The
same bug was diagnosed and fixed in the sibling product in August.

What is pinned here: the number comes from the ROUTE, is resolved rather than
guessed, and a route's budget is its smallest hop — because the conversation
has to be able to continue on any of them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from service.llm_accounts.secrets import SecretStore
from service.llm_accounts.service import AccountService, route_context_window

from tests.service.llm_accounts.test_account_service import _FakeDb


@pytest.fixture()
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AccountService:
    monkeypatch.setenv("GENY_LLM_ACCOUNTS_ROOT", str(tmp_path / "accounts"))
    return AccountService(_FakeDb(), SecretStore(tmp_path / "secrets.json"))


def _make(service: AccountService, kind: str, **extra: Any) -> Dict[str, Any]:
    return service.create_account({"kind": kind, "secret": "k", **extra})


class TestWhereTheNumberComesFrom:
    def test_a_known_family_answers_offline(self, service: AccountService) -> None:
        account = _make(service, "anthropic")
        assert service.context_window_of(account["id"], "claude-sonnet-5") == 200_000

    def test_what_the_endpoint_stated_wins(self, service: AccountService) -> None:
        """An aggregator routing to hundreds of models is the case the table
        cannot answer — and the case that states it."""
        account = _make(service, "openrouter")
        service._stamp(account["id"], windows={"anthropic/claude-sonnet-5": 131072})
        assert service.context_window_of(account["id"], "anthropic/claude-sonnet-5") == 131072

    def test_the_operator_wins_over_both(self, service: AccountService) -> None:
        account = _make(service, "openai_compatible", baseUrl="http://gw/v1",
                        contextWindow=8192)
        service._stamp(account["id"], windows={"m": 131072})
        assert service.context_window_of(account["id"], "m") == 8192

    def test_a_self_hosted_model_id_is_not_answered_from_the_table(
        self, service: AccountService
    ) -> None:
        """On a vLLM server the window belongs to the server, not the weights —
        so a familiar-looking id must not produce a confident wrong answer."""
        account = _make(service, "vllm", baseUrl="http://box:8000/v1")
        assert service.context_window_of(account["id"], "claude-sonnet-5") is None

    def test_an_unknown_model_stays_unknown(self, service: AccountService) -> None:
        account = _make(service, "openai_compatible", baseUrl="http://gw/v1")
        assert service.context_window_of(account["id"], "something-new") is None


class TestItReachesTheHop:
    @pytest.mark.asyncio
    async def test_the_hop_carries_the_window(self, service: AccountService) -> None:
        account = _make(service, "anthropic")
        hop = await service.resolve_hop({"accountId": account["id"], "model": "claude-opus-5"})
        assert hop["contextWindow"] == 200_000

    @pytest.mark.asyncio
    async def test_an_unknown_hop_carries_nothing_rather_than_a_guess(
        self, service: AccountService
    ) -> None:
        account = _make(service, "vllm", baseUrl="http://box:8000/v1")
        hop = await service.resolve_hop({"accountId": account["id"], "model": "qwen"})
        assert "contextWindow" not in hop


class TestARouteHoldsItsSmallestHop:
    """Fallbacks exist so the conversation can continue elsewhere. Sizing to
    the primary means the failover — which happens when things are already
    going wrong — walks into an overflow it cannot recover from."""

    @pytest.mark.asyncio
    async def test_the_small_hop_binds(self, service: AccountService) -> None:
        big = _make(service, "anthropic")
        small = _make(service, "openai_compatible", baseUrl="http://box/v1",
                      contextWindow=32768)
        targets = await service.resolve_route(
            {"primary": {"accountId": big["id"]},
             "fallbacks": [{"accountId": small["id"], "model": "local"}]}
        )
        assert route_context_window(targets) == 32_768

    @pytest.mark.asyncio
    async def test_an_unknown_hop_cannot_raise_it(self, service: AccountService) -> None:
        known = _make(service, "openai_compatible", baseUrl="http://a/v1", contextWindow=32768)
        unknown = _make(service, "openai_compatible", baseUrl="http://b/v1")
        targets = await service.resolve_route(
            {"primary": {"accountId": known["id"], "model": "x"},
             "fallbacks": [{"accountId": unknown["id"], "model": "y"}]}
        )
        assert route_context_window(targets) == 32_768

    def test_a_route_nobody_knows_is_unknown(self) -> None:
        assert route_context_window([{"model": "x"}, {"model": "y"}]) is None

    def test_an_empty_route_is_unknown(self) -> None:
        assert route_context_window([]) is None


class TestDiscoveryRecordsIt:
    def test_the_declared_half_survives_a_rediscovery(self, service: AccountService) -> None:
        """Discovery overwrites what it measured, never what the operator
        said — otherwise a refresh silently undoes their correction."""
        account = _make(service, "openai_compatible", baseUrl="http://gw/v1",
                        contextWindow=8192)
        service._stamp(account["id"], windows={"m": 131072})
        stored = service.get_account(account["id"])["contextWindow"]
        assert stored["declared"] == 8192
        assert stored["discovered"] == {"m": 131072}

    def test_an_operator_can_clear_their_declaration(self, service: AccountService) -> None:
        account = _make(service, "openai_compatible", baseUrl="http://gw/v1",
                        contextWindow=8192)
        updated = service.update_account(account["id"], {"contextWindow": None})
        assert updated["contextWindow"]["declared"] is None

    def test_junk_is_not_stored_as_a_window(self, service: AccountService) -> None:
        account = _make(service, "openai_compatible", baseUrl="http://gw/v1",
                        contextWindow="lots")
        assert service.get_account(account["id"])["contextWindow"]["declared"] is None
