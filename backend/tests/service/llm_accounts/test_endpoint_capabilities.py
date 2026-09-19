"""What an endpoint serves, and who gets to say so.

``openrouter``, a company gateway and a laptop's llama.cpp are all reached
through one executor client class, because they all speak the OpenAI wire
format. Nothing else about them is alike. The class has to assume the weakest
of them, so vision — the capability whose absence is silent — has to be
declared, and this pins where the declaration comes from:

* the KIND declares what is true of the vendor (OpenRouter fronts Claude and
  GPT; a bare compatible endpoint is anyone's guess);
* the ACCOUNT overrides it, because which model sits behind one address is
  the operator's knowledge and nobody else's;
* the declaration only rides to the clients that accept one.

The regression that motivated it: making ``supports_vision`` default False
was right for a local server and silently turned every OpenRouter image into
"[an image was attached here]".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from service.database.models.llm_account import LLMAccountModel
from service.llm_accounts.kinds import KINDS
from service.llm_accounts.secrets import SecretStore
from service.llm_accounts.service import (
    CAPABILITY_AWARE_PROVIDERS,
    DECLARABLE_CAPABILITIES,
    AccountService,
)

from tests.service.llm_accounts.test_account_service import _FakeDb


@pytest.fixture()
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AccountService:
    monkeypatch.setenv("GENY_LLM_ACCOUNTS_ROOT", str(tmp_path / "accounts"))
    return AccountService(_FakeDb(), SecretStore(tmp_path / "secrets.json"))


def _make(service: AccountService, kind: str, **extra: Any) -> Dict[str, Any]:
    return service.create_account({"kind": kind, "secret": "k", **extra})


class TestTheKindDeclares:
    @pytest.mark.asyncio
    async def test_openrouter_says_it_can_see(self, service: AccountService) -> None:
        account = _make(service, "openrouter")
        hop = await service.resolve_hop({"accountId": account["id"]})
        assert hop["options"]["capabilities"]["supports_vision"] is True

    @pytest.mark.asyncio
    async def test_a_bare_compatible_endpoint_claims_nothing(
        self, service: AccountService
    ) -> None:
        """Silence is the safe answer here: guessing yes is a 400 on a
        text-only server, and the operator can say otherwise in one click."""
        account = _make(service, "openai_compatible", baseUrl="http://box:8080/v1")
        hop = await service.resolve_hop({"accountId": account["id"], "model": "local"})
        assert "capabilities" not in hop["options"]

    @pytest.mark.asyncio
    async def test_a_vllm_account_arrives_able_to_call_tools(
        self, service: AccountService
    ) -> None:
        """VLLMClient defaults to no tools — correct for the class, useless
        for an account added to run this harness."""
        account = _make(service, "vllm", baseUrl="http://box:8000/v1")
        hop = await service.resolve_hop({"accountId": account["id"], "model": "qwen"})
        assert hop["options"]["capabilities"]["supports_tools"] is True


class TestTheAccountOverrides:
    @pytest.mark.asyncio
    async def test_an_operator_can_say_their_gateway_sees(
        self, service: AccountService
    ) -> None:
        account = _make(
            service,
            "openai_compatible",
            baseUrl="http://gw:8080/v1",
            capabilities={"supports_vision": True},
        )
        hop = await service.resolve_hop({"accountId": account["id"], "model": "gpt-5.6-terra"})
        assert hop["options"]["capabilities"] == {"supports_vision": True}

    @pytest.mark.asyncio
    async def test_and_can_contradict_the_kind(self, service: AccountService) -> None:
        """An OpenRouter key pinned to a text-only model is a real setup —
        the account is nearer the truth than the catalogue."""
        account = _make(service, "openrouter", capabilities={"supports_vision": False})
        hop = await service.resolve_hop({"accountId": account["id"]})
        assert hop["options"]["capabilities"]["supports_vision"] is False

    def test_a_flag_nobody_declared_is_not_invented(self, service: AccountService) -> None:
        account = _make(service, "openrouter", capabilities={"supports_telepathy": True})
        assert account["capabilities"] == {}

    def test_the_kinds_own_declaration_is_reported_separately(
        self, service: AccountService
    ) -> None:
        """So the settings page can show a toggle that is ON by default
        without pretending the account set it."""
        account = _make(service, "openrouter")
        assert account["capabilities"] == {}
        assert account["kindCapabilities"] == {"supports_vision": True}

    def test_an_update_round_trips(self, service: AccountService) -> None:
        account = _make(service, "vllm", baseUrl="http://box:8000/v1")
        updated = service.update_account(account["id"], {"capabilities": {"supports_vision": True}})
        assert updated["capabilities"] == {"supports_vision": True}


class TestOnlyWhereItIsAccepted:
    """A declaration sent to a client that takes no such kwarg is a
    TypeError on the first turn, not a warning."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["anthropic", "openai", "google"])
    async def test_the_vendor_clients_are_left_alone(
        self, service: AccountService, kind: str
    ) -> None:
        account = _make(service, kind)
        hop = await service.resolve_hop({"accountId": account["id"]})
        assert "capabilities" not in hop["options"]

    def test_every_listed_provider_really_takes_the_kwarg(self) -> None:
        """Pins the list against the library rather than against a memory of
        it: a provider added here whose client has no such parameter would
        fail only on a live turn against that account."""
        import inspect

        from geny_executor.llm_client.registry import ClientRegistry

        for provider in CAPABILITY_AWARE_PROVIDERS:
            client_cls = ClientRegistry.get(provider)
            params = inspect.signature(client_cls.__init__).parameters
            assert "capabilities" in params, f"{provider} client takes no capabilities kwarg"

    def test_every_declarable_flag_is_a_real_capability(self) -> None:
        from geny_executor.llm_client.base import ClientCapabilities

        for flag in DECLARABLE_CAPABILITIES:
            assert hasattr(ClientCapabilities(), flag), flag

    def test_every_kinds_declaration_is_a_real_capability(self) -> None:
        from geny_executor.llm_client.base import ClientCapabilities

        caps = ClientCapabilities()
        for name, info in KINDS.items():
            for flag in info.capabilities:
                assert hasattr(caps, flag), f"{name} declares unknown capability {flag}"
            if info.capabilities:
                assert info.engine_provider in CAPABILITY_AWARE_PROVIDERS, (
                    f"{name} declares capabilities its client never receives"
                )


class TestAnAccountWithNoModelYet:
    """Every vendor kind below OpenRouter ships an empty catalogue on purpose
    (``GET /v1/models`` is more current than a release). Until discovery runs
    there is no model to name."""

    @pytest.mark.asyncio
    async def test_the_hop_is_dropped_not_sent_empty(self, service: AccountService) -> None:
        account = _make(service, "groq")
        assert await service.resolve_hop({"accountId": account["id"]}) is None

    @pytest.mark.asyncio
    async def test_a_discovered_model_makes_it_usable(self, service: AccountService) -> None:
        account = _make(service, "groq")
        service._stamp(account["id"], models=["llama-3.3-70b-versatile"])
        hop = await service.resolve_hop({"accountId": account["id"]})
        assert hop["model"] == "llama-3.3-70b-versatile"

    @pytest.mark.asyncio
    async def test_the_route_degrades_past_it(self, service: AccountService) -> None:
        """A half-configured account must not take the conversation with it."""
        empty = _make(service, "groq")
        ready = _make(service, "anthropic")
        hops = await service.resolve_route(
            {"primary": {"accountId": empty["id"]},
             "fallbacks": [{"accountId": ready["id"]}]}
        )
        assert [h["kind"] for h in hops] == ["anthropic"]


class TestTheVendorCatalogue:
    def test_every_api_kind_carries_an_address(self) -> None:
        """A kind whose only value over "paste a URL" is the URL."""
        for name, info in KINDS.items():
            if info.engine_provider == "custom" and info.family == "api":
                assert info.default_base_url.startswith("https://"), name

    def test_no_two_kinds_claim_the_same_address(self) -> None:
        seen: Dict[str, str] = {}
        for name, info in KINDS.items():
            url = info.default_base_url
            if not url:
                continue
            assert url not in seen, f"{name} duplicates {seen[url]}"
            seen[url] = name

    def test_the_catch_all_still_takes_any_address(self) -> None:
        info = KINDS["openai_compatible"]
        assert info.needs_base_url and not info.default_base_url
