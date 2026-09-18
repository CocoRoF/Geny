"""Unified memory-path LLM helper.

Builds a ``BaseClient`` + ``ModelConfig`` and wraps them in a small
``MemoryLLM`` adapter for offline memory-curation jobs that run
outside any session and therefore have no manifest to consult.

Provider resolution uses the library-owned
``CredentialBundle.preferred_provider()`` (geny-executor 2.2.0) —
Claude Code CLI when the user has it enabled, otherwise whichever
API-key backend they configured. Credentials flow through the same
``CredentialBundleBuilder`` Geny uses to feed live sessions, so a
user logged into Claude Code via OAuth gets their memory curation
run on the same backend as their chat sessions — no separate
``ANTHROPIC_API_KEY`` requirement.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from logging import getLogger
from typing import Any, Dict, Optional

from geny_executor.core.config import ModelConfig
from geny_executor.llm_client import BaseClient, ClientRegistry

logger = getLogger(__name__)

try:  # geny-executor >= 2.46.0
    from geny_executor.memory import MEMORY_ENGINE_SYSTEM_PROMPT
except Exception:  # noqa: BLE001 — older executor
    MEMORY_ENGINE_SYSTEM_PROMPT = (
        "You are a memory maintenance engine inside an agent platform. You "
        "are NOT an assistant and you are NOT talking to a user. Produce "
        "only the requested artifact — no preamble, no questions."
    )


def _parse_json_text(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort JSON object from a model reply (tolerates code fences)."""
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("```"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return None
        cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


@dataclass
class MemoryLLM:
    """Thin adapter wrapping a ``BaseClient`` + preconfigured ``ModelConfig``.

    Exposes a single ``complete(prompt)`` coroutine so callers that
    previously spoke the LangChain ``Runnable.ainvoke([HumanMessage])``
    shape migrate with one line per call site. Returns the joined text
    content; callers that need the full ``APIResponse`` can reach
    through ``client`` + ``model_config`` directly.
    """

    client: BaseClient
    model_config: ModelConfig

    async def complete(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        purpose: str = "memory.curation",
    ) -> str:
        """Freeform completion. The engine system framing is applied by
        default — every memory-path call is maintenance work, and without
        it a CLI-backed model answers the archival material as an
        assistant (the root cause of chat replies persisted as memory).
        Pass ``system=""`` explicitly to opt out."""
        response = await self.client.create_message(
            model_config=self.model_config,
            messages=[{"role": "user", "content": prompt}],
            system=MEMORY_ENGINE_SYSTEM_PROMPT if system is None else system,
            purpose=purpose,
        )
        return response.text

    async def complete_structured(
        self,
        prompt: str,
        schema: Dict[str, Any],
        *,
        purpose: str = "memory.structured",
    ) -> Optional[Dict[str, Any]]:
        """Schema-bound completion → parsed dict, or ``None`` (callers keep
        previous state on None — never persist an unvalidated reply).

        Enforcement is native where the backend supports it (Claude Code
        CLI ``--json-schema`` → ``APIResponse.structured``); other
        backends carry the format as advisory and we parse+validate the
        text, with one corrective retry."""
        response_format = {"type": "json_schema", "json_schema": schema}
        messages = [{"role": "user", "content": prompt}]
        for attempt in (0, 1):
            try:
                response = await self.client.create_message(
                    model_config=self.model_config,
                    messages=messages,
                    system=MEMORY_ENGINE_SYSTEM_PROMPT,
                    purpose=purpose,
                    response_format=response_format,
                )
            except Exception:  # noqa: BLE001 — transport; caller keeps state
                logger.warning(
                    "memory_llm: structured call failed", exc_info=True,
                )
                return None
            structured = getattr(response, "structured", None)
            if isinstance(structured, dict):
                return structured
            parsed = _parse_json_text(response.text)
            if parsed is not None:
                return parsed
            if attempt == 0:
                messages = messages + [
                    {"role": "assistant", "content": response.text or ""},
                    {
                        "role": "user",
                        "content": (
                            "Invalid output. Return ONLY a JSON object "
                            "matching the provided schema — no prose, no "
                            "code fences."
                        ),
                    },
                ]
        logger.warning("memory_llm: structured output unparseable after retry")
        return None


#: Which model families each provider actually serves. Used to refuse a
#: pairing rather than discover it as a 404 three layers down.
_FAMILIES: Dict[str, tuple] = {
    "anthropic": ("claude",),
    "geny_claude_code": ("claude", "sonnet", "opus", "haiku", "fable"),
    "geny_router": (),          # the router asks its hops; never refuse here
    "openai": ("gpt", "o1", "o3", "o4", "chatgpt"),
    "geny_codex": ("gpt", "o1", "o3", "o4", "codex"),
    "google": ("gemini",),
}


def _serves(provider: str, model: str) -> bool:
    """True when *provider* plausibly serves *model*.

    Deliberately permissive: an unknown provider (vllm, ollama, a custom
    endpoint, anything a host registers) serves whatever it is told, so
    only the families we KNOW are wrong get refused.
    """
    prefixes = _FAMILIES.get(provider)
    if not prefixes or not model:
        return True
    m = model.strip().lower()
    return any(m.startswith(p) for p in prefixes)


def _curation_account() -> Optional[tuple]:
    """``(provider, model, extras)`` for the default route's first account.

    Curation is offline work with no session, so it borrows the account a
    new session would get — memory is then curated by the same model the
    user actually talks to, on the same subscription, instead of whatever
    key happened to be configured years ago.

    Read-only and SYNCHRONOUS on purpose. ``resolve_hop`` is async (a
    Codex hop may refresh its token) and every caller here sits inside a
    running event loop, so reaching it would need a nested loop or a
    worker thread — and a background curation pass is the last place to
    introduce either (this process wedged on exactly that, in D-state,
    the first time it was tried). Claude Code accounts need no async
    work; ``AccountService.claude_options`` is the shared definition.
    Codex is skipped here for the same reason — its tokens rotate, and
    curation is not what should be rotating them.
    """
    try:
        from service.llm_accounts import service as accounts_module

        # The ALREADY-BUILT service only. ``get_account_service()`` would
        # lazily construct an AppDatabaseManager and open a connection, and
        # a background curation pass is not what should open the database.
        svc = getattr(accounts_module, "_service", None)
        if svc is None:
            return None
        primary = (svc.default_route() or {}).get("primary")
        if not isinstance(primary, dict):
            return None
        account_id = str(primary.get("accountId") or "")
        account = svc.get_account(account_id) or {}
        if account.get("kind") != "claude_code" or not account.get("enabled", True):
            return None
        model = str(primary.get("model") or "").strip() or "sonnet"
        return (
            "geny_claude_code",
            model,
            svc.claude_options(account_id, label=str(account.get("label") or "")),
        )
    except Exception as exc:  # noqa: BLE001 — no accounts is not a crash
        logger.debug("memory_llm: no curation account (%s)", exc)
        return None


def build_memory_llm() -> Optional[MemoryLLM]:
    """Build a memory-path LLM adapter for offline curation.

    The provider comes from the credential bundle and the model from
    config or the account route — and **the pair is checked**, which is
    what was missing. Those two choices were independent and had only
    ever agreed by luck; they stopped agreeing on 2026-09-19, when the
    legacy ``claude_code_cli`` entry left the bundle. The heuristic fell
    through to ``openai`` while the model stayed ``claude-haiku-*``, and
    every curation call got a 404 from the OpenAI API — caught in the
    prod logs, not by a test, because nothing had ever asserted that a
    provider is handed a model it can serve.

    Order: the default route's first account when it is a Claude Code
    subscription — memory is then curated by the same model the user
    actually talks to, on the same login, costing no extra key — and
    otherwise a configured key, with ``memory_model`` winning when the
    operator set one the provider can serve. A pair that cannot work
    yields ``None`` rather than a 404 three layers down.

    Returns ``None`` when nothing has usable credentials, so callers
    (``CurationEngine`` gates every LLM stage on ``self._llm``) degrade
    cleanly to rule-based paths.
    """
    try:
        from service.config.manager import get_config_manager
        from service.config.sub_config.general.api_config import APIConfig
        from service.executor.credentials import CredentialBundleBuilder
        # NOTE: ``_creds_to_client_kwargs`` is still private in
        # geny-executor 2.2.0 — flagged upstream for promotion to a
        # public client factory in 2.2.x. Revisit this import when that
        # lands.
        from geny_executor.core.pipeline import _creds_to_client_kwargs

        cm = get_config_manager()
        api_cfg = cm.load_config(APIConfig)

        # 1. The account the user actually talks to, when it is a Claude
        #    Code subscription — no extra key, same model family, and the
        #    curation reads like the conversation it is curating.
        account = _curation_account()
        if account is not None:
            provider, model_name, extras = account
            preferred = (api_cfg.memory_model or "").strip()
            if preferred and _serves(provider, preferred):
                model_name = preferred
            try:
                client_cls = ClientRegistry.get(provider)
                client = client_cls(**dict(extras))
                return MemoryLLM(
                    client=client,
                    model_config=ModelConfig(
                        model=model_name,
                        max_tokens=2048,
                        temperature=0.0,
                        thinking_enabled=False,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 — fall through to the bundle
                logger.warning("memory_llm: curation account unusable (%s)", exc)

        # 2. Otherwise a configured key, with the pairing CHECKED — the
        #    part that was missing.
        bundle = CredentialBundleBuilder(cm).build()
        provider = bundle.preferred_provider() or ""
        if not provider:
            return None
        creds = bundle.get(provider)
        if creds.is_empty():
            return None

        model_name = (api_cfg.memory_model or "").strip() or api_cfg.anthropic_model
        if not _serves(provider, model_name):
            logger.warning(
                "memory_llm: %r cannot serve %r — skipping LLM curation rather "
                "than sending a model id the provider will 404 on. Set "
                "memory_model to something %s serves, or add a Claude Code "
                "account (curation then rides the subscription).",
                provider, model_name, provider,
            )
            return None

        client_cls = ClientRegistry.get(provider)
        client = client_cls(**_creds_to_client_kwargs(provider, creds))

        if not model_name:
            return None

        model_config = ModelConfig(
            model=model_name,
            max_tokens=2048,
            temperature=0.0,
            thinking_enabled=False,
        )
        return MemoryLLM(client=client, model_config=model_config)
    except Exception as exc:
        logger.warning("build_memory_llm failed: %s", exc)
        return None
