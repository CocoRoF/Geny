"""LLM backend health + Claude Code login routes.

Phase E4 of the LLM backend upgrade cycle. The frontend uses these
endpoints to:

  * Render a "backend health" card per provider on Settings → LLM
    Backends.
  * Surface a *real* login flow for Claude Code: the API key path
    (parity with Anthropic) and the subscription path (run
    ``claude auth login`` in a terminal). The endpoint also reports
    the binary version, which auth mode is active, and whether a
    quick smoke test passed.
  * List the registered sub-agent types so the frontend's catalog
    page can render them without re-walking the registry.

Cycle 20260520 — the ``gh copilot`` CLI routes were removed.
``gh copilot`` is one-shot text-in / text-out with no streaming, no
tool round-trip, and no MCP support, so it could never host Geny's
Sub-Worker delegation or Stage-10 dispatch. See
``service/executor/credentials.py`` module docstring + the matching
removal commit for the full rationale.

All routes are guarded by ``require_auth``.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from service.auth.auth_middleware import require_auth
from service.config import get_config_manager
from service.executor.credentials import CredentialBundleBuilder


router = APIRouter(prefix="/api/llm-backends", tags=["llm-backends"])


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


class ProviderHealth(BaseModel):
    provider: str
    label: str
    kind: str                            # "api" | "cli"
    available: bool
    # ``detail`` / ``install_help`` are the English fallback strings — the
    # frontend renders ``detail_code`` + ``detail_params`` through its
    # i18n module first and falls back to these strings only when the
    # code is missing or unknown (handles deploy ordering / unknown
    # backends).
    detail: Optional[str] = None
    detail_code: Optional[str] = None
    detail_params: Optional[Dict[str, str]] = None
    binary_path: Optional[str] = None
    binary_version: Optional[str] = None
    auth_ok: Optional[bool] = None
    auth_method: Optional[str] = None    # "api_key" | "subscription" | "extension"
    install_help: Optional[str] = None
    install_help_code: Optional[str] = None


class BackendsHealthResponse(BaseModel):
    providers: List[ProviderHealth]


class SubagentInfo(BaseModel):
    agent_type: str
    description: str
    provider: Optional[str] = None
    allowed_tools: List[str] = []
    model_override: Optional[str] = None


class SubagentsResponse(BaseModel):
    items: List[SubagentInfo]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


PROVIDER_LABELS: Dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google Gemini",
    "vllm": "vLLM (self-host)",
    # Branded local (OpenAI-compatible) backends — executor 2.9.0.
    "ollama": "Ollama (local)",
    "lmstudio": "LM Studio (local)",
    "custom": "Custom (OpenAI-compatible)",
}

# Default endpoints for the branded local providers — used when the user
# hasn't pinned a base_url yet (matches the executor ProviderProfile
# defaults). ``custom`` has no default (the user must supply one).
LOCAL_PROVIDER_DEFAULT_URLS: Dict[str, str] = {
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://127.0.0.1:1234/v1",
    "custom": "",
}


async def _run_cmd(argv: List[str], timeout: float = 5.0) -> tuple[int, str, str]:
    """Run a short command (e.g. ``claude --version``) and capture
    stdout/stderr. Returns (returncode, stdout, stderr). On timeout or
    spawn failure returns (-1, "", error_text)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        return (-1, "", str(e))
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return (-1, "", "command timed out")
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
    )


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------


async def _api_key_health(
    provider: str, env_var: str, bundle, revalidate: bool = False,
) -> ProviderHealth:
    creds = bundle.get(provider)
    have = bool(creds.api_key)
    if not have:
        return ProviderHealth(
            provider=provider,
            label=PROVIDER_LABELS[provider],
            kind="api",
            available=False,
            detail="No API key set.",
            detail_code="api.key_missing",
            detail_params={"env": env_var},
            auth_method=None,
            auth_ok=None,
        )

    # Live auth probe (cached per key value) — a rejected key must show
    # RED here, not a green "configured" that fails downstream.
    from service.config.credentials import validate_provider_key

    ok, verdict = await validate_provider_key(
        provider, creds.api_key, force=revalidate,
    )
    if ok is False:
        detail = f"{env_var} is set but the provider REJECTED it ({verdict})."
        detail_code = "api.key_rejected"
    elif ok is True:
        detail = f"{env_var} verified with the provider."
        detail_code = "api.key_verified"
    else:
        detail = f"{env_var} configured."
        detail_code = "api.key_configured"
    return ProviderHealth(
        provider=provider,
        label=PROVIDER_LABELS[provider],
        kind="api",
        available=ok is not False,
        detail=detail,
        detail_code=detail_code,
        detail_params={"env": env_var},
        auth_method="api_key",
        auth_ok=(True if ok is not False else False),
    )


async def _check_anthropic(bundle, revalidate: bool = False) -> ProviderHealth:
    return await _api_key_health("anthropic", "ANTHROPIC_API_KEY", bundle, revalidate)


async def _check_openai(bundle, revalidate: bool = False) -> ProviderHealth:
    return await _api_key_health("openai", "OPENAI_API_KEY", bundle, revalidate)


async def _check_google(bundle, revalidate: bool = False) -> ProviderHealth:
    return await _api_key_health("google", "GOOGLE_API_KEY", bundle, revalidate)


async def _check_vllm(bundle) -> ProviderHealth:
    creds = bundle.get("vllm")
    have_url = bool(creds.base_url)
    return ProviderHealth(
        provider="vllm",
        label=PROVIDER_LABELS["vllm"],
        kind="api",
        available=have_url,
        detail=(
            f"base_url={creds.base_url}" if have_url
            else "vLLM base URL not set. Open this card and paste the OpenAI-compatible endpoint."
        ),
        detail_code="vllm.base_url_set" if have_url else "vllm.base_url_missing",
        detail_params={"url": creds.base_url or ""},
        auth_method=None,
        auth_ok=have_url or None,
    )


# ---------------------------------------------------------------------------
# Local (OpenAI-compatible) backends — reachability + model discovery
# ---------------------------------------------------------------------------


async def _http_get_json(url: str, timeout: float = 5.0) -> Optional[Any]:
    """GET *url* and parse JSON. Best-effort: any failure → ``None``."""
    try:
        import httpx  # transitive via geny-executor / anthropic
    except ImportError:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
    except Exception:  # noqa: BLE001 — unreachable server / DNS / TLS
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def _ollama_native_root(base_url: str) -> str:
    """``http://host:11434/v1`` → ``http://host:11434`` (native API root)."""
    root = (base_url or "").rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")].rstrip("/")
    return root


async def _discover_local_models(provider: str, base_url: str) -> Optional[List[str]]:
    """List model ids served at *base_url*, or ``None`` if unreachable.

    Ollama exposes its catalogue at the native ``/api/tags``; every other
    OpenAI-compatible server (LM Studio / llama.cpp / vLLM / custom) uses
    ``/v1/models``. An empty list means "reachable but no models loaded".
    """
    if not base_url:
        return None
    if provider == "ollama":
        body = await _http_get_json(f"{_ollama_native_root(base_url)}/api/tags")
        if not isinstance(body, dict):
            return None
        models = body.get("models")
        if not isinstance(models, list):
            return []
        names = [m.get("name") for m in models if isinstance(m, dict) and m.get("name")]
        return sorted(str(n) for n in names)
    # OpenAI-compatible /models
    body = await _http_get_json(f"{base_url.rstrip('/')}/models")
    if not isinstance(body, dict):
        return None
    data = body.get("data")
    if not isinstance(data, list):
        return []
    ids = [d.get("id") for d in data if isinstance(d, dict) and d.get("id")]
    return sorted(str(i) for i in ids)


def _resolve_local_base_url(provider: str, creds, override: Optional[str]) -> str:
    """Effective base_url for a local provider: explicit override → stored
    credential → the provider's default endpoint."""
    if override:
        return override
    stored = getattr(creds, "base_url", "") or ""
    if stored:
        return stored
    return LOCAL_PROVIDER_DEFAULT_URLS.get(provider, "")


async def _check_local(provider: str, bundle) -> ProviderHealth:
    """Health for a branded local provider: configured? reachable? how
    many models are served? A live probe makes the card actionable —
    "준비됨 (3 models)" vs "엔드포인트에 연결할 수 없어요"."""
    creds = bundle.get(provider)
    configured_url = getattr(creds, "base_url", "") or ""
    base_url = _resolve_local_base_url(provider, creds, None)
    label = PROVIDER_LABELS[provider]

    # ``custom`` with no endpoint is simply not set up yet.
    if not base_url:
        return ProviderHealth(
            provider=provider,
            label=label,
            kind="api",
            available=False,
            detail="Endpoint not set. Open this card and paste the OpenAI-compatible base URL.",
            detail_code="local.base_url_missing",
            detail_params={"provider": provider},
            auth_ok=None,
        )

    models = await _discover_local_models(provider, base_url)
    reachable = models is not None
    configured = bool(configured_url)
    if not reachable:
        return ProviderHealth(
            provider=provider,
            label=label,
            kind="api",
            available=False,
            detail=f"Could not reach {base_url}. Is the local server running?",
            detail_code="local.unreachable",
            detail_params={"url": base_url},
            auth_ok=False,
        )
    count = len(models or [])
    return ProviderHealth(
        provider=provider,
        # ``available`` means usable now: reachable AND the operator
        # actually opted in (a configured base_url). A reachable default
        # endpoint the user never saved is surfaced but not auto-active.
        label=label,
        kind="api",
        available=configured and count > 0,
        detail=(
            f"Reachable at {base_url} — {count} model(s)."
            if configured
            else f"Reachable at {base_url} — {count} model(s). Save this endpoint to enable it."
        ),
        detail_code="local.reachable" if configured else "local.reachable_unsaved",
        detail_params={"url": base_url, "count": str(count)},
        auth_ok=True if configured else None,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health", response_model=BackendsHealthResponse, dependencies=[Depends(require_auth)])
async def get_backends_health(revalidate: bool = False) -> BackendsHealthResponse:
    """Per-provider health probe. Surfaces what the UI needs to render
    the LLM & Provider settings cards: which providers are usable now,
    what's missing, and how the user can finish the setup.
    ``revalidate=true`` (the panel's refresh button) re-probes the cloud
    keys against their providers instead of using the cached verdict."""
    cm = get_config_manager()
    bundle = CredentialBundleBuilder(cm).build()

    results = await asyncio.gather(
        _check_anthropic(bundle, revalidate),
        _check_openai(bundle, revalidate),
        _check_google(bundle, revalidate),
        _check_vllm(bundle),
        _check_local("ollama", bundle),
        _check_local("lmstudio", bundle),
        _check_local("custom", bundle),
    )
    return BackendsHealthResponse(providers=list(results))


class LocalModelsResponse(BaseModel):
    provider: str
    base_url: str
    reachable: bool
    models: List[str] = []
    detail_code: Optional[str] = None


@router.get(
    "/local-models",
    response_model=LocalModelsResponse,
    dependencies=[Depends(require_auth)],
)
async def list_local_models(
    provider: str,
    base_url: Optional[str] = None,
) -> LocalModelsResponse:
    """Discover the model ids served by a local backend so the LLM
    Backends card can render a dropdown instead of a free-form box.

    *base_url* (optional) overrides the stored / default endpoint — the
    card passes the value the user is typing so "Test" works before save.
    """
    if provider not in ("ollama", "lmstudio", "custom"):
        raise HTTPException(status_code=400, detail=f"not a local provider: {provider!r}")
    cm = get_config_manager()
    bundle = CredentialBundleBuilder(cm).build()
    creds = bundle.get(provider)
    resolved = _resolve_local_base_url(provider, creds, base_url)
    if not resolved:
        return LocalModelsResponse(
            provider=provider, base_url="", reachable=False,
            detail_code="local.base_url_missing",
        )
    models = await _discover_local_models(provider, resolved)
    if models is None:
        return LocalModelsResponse(
            provider=provider, base_url=resolved, reachable=False,
            detail_code="local.unreachable",
        )
    return LocalModelsResponse(
        provider=provider, base_url=resolved, reachable=True, models=models,
        detail_code="local.reachable",
    )


# ── Unified per-provider model discovery (cloud + local) ─────────────────────
# Live-lists the models a backend actually serves via the executor's
# discover_models (geny-executor >=2.9.0): cloud providers authenticate with
# their configured key; local providers probe their endpoint. source="live"
# means the list is real; "unavailable" means the caller should fall back to
# its static catalogue (the FE keeps MODEL_CATALOG for that).
# ``geny_claude_code`` is always "unavailable" — the CLI has no model-list
# command; its version-robust aliases (sonnet/opus/haiku) are the fallback.

_LOCAL_DISCOVERY_PROVIDERS = {"ollama", "lmstudio", "vllm", "custom", "local"}

class ProviderModel(BaseModel):
    id: str
    display_name: Optional[str] = None


class ProviderModelsResponse(BaseModel):
    provider: str
    source: str = "unavailable"  # "live" | "unavailable"
    models: List[ProviderModel] = []
    error: Optional[str] = None


# OpenAI's /v1/models returns the whole account catalogue (embeddings, whisper,
# tts, dall-e, …) — a model picker only wants chat/completions models. Keep the
# chat families and drop known non-chat ones. Other providers already return
# chat-only (anthropic = all claude; google filtered to generateContent; local
# = user-controlled), so the filter is a no-op for them.
_OPENAI_CHAT_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt")
_NON_CHAT_SUBSTR = (
    "embedding", "whisper", "tts", "dall-e", "davinci", "babbage", "ada",
    "moderation", "audio", "transcribe", "realtime", "image", "-search",
)


def _filter_chat_models(
    provider: str, models: List[ProviderModel]
) -> List[ProviderModel]:
    if provider != "openai":
        return models
    kept = [
        m for m in models
        if m.id.lower().startswith(_OPENAI_CHAT_PREFIXES)
        and not any(s in m.id.lower() for s in _NON_CHAT_SUBSTR)
    ]
    return kept or models  # never return empty — fall back to the full list


@router.get(
    "/models",
    response_model=ProviderModelsResponse,
    dependencies=[Depends(require_auth)],
)
async def list_provider_models(
    provider: str,
    base_url: Optional[str] = None,
) -> ProviderModelsResponse:
    """Discover the models *provider* currently serves (best-effort, live).

    The model picker calls this on provider change. On ``source="unavailable"``
    the caller falls back to its static catalogue — so a backend version bump
    (e.g. a new Ollama pull, a new cloud model) shows up automatically while a
    backend that can't be enumerated (Claude Code CLI) still works via aliases.
    """
    try:
        from geny_executor.llm_client import discover_models
    except Exception:  # noqa: BLE001 — executor < 2.9.0
        return ProviderModelsResponse(
            provider=provider, source="unavailable", error="discovery unsupported"
        )

    cm = get_config_manager()
    bundle = CredentialBundleBuilder(cm).build()
    creds = bundle.get(provider)
    api_key = getattr(creds, "api_key", "") or None
    resolved_base = base_url
    if provider in _LOCAL_DISCOVERY_PROVIDERS:
        resolved_base = _resolve_local_base_url(provider, creds, base_url) or None

    disc = await discover_models(
        provider, api_key=api_key, base_url=resolved_base
    )
    models = _filter_chat_models(
        provider,
        [ProviderModel(id=m.id, display_name=m.display_name) for m in disc.models],
    )
    return ProviderModelsResponse(
        provider=provider, source=disc.source, models=models, error=disc.error
    )


class LocalContextWindowResponse(BaseModel):
    provider: str
    base_url: str
    model: str
    context_window: Optional[int] = None


@router.get(
    "/local-context-window",
    response_model=LocalContextWindowResponse,
    dependencies=[Depends(require_auth)],
)
async def get_local_context_window(
    provider: str,
    model: str,
    base_url: Optional[str] = None,
) -> LocalContextWindowResponse:
    """Probe a local model's real context window (Ollama ``/api/show``)
    via the executor's :func:`resolve_local_context_window`, so the card
    can auto-fill the Ollama context-window field instead of guessing.
    ``context_window`` is ``None`` when the probe can't determine it."""
    if provider not in ("ollama", "lmstudio", "custom"):
        raise HTTPException(status_code=400, detail=f"not a local provider: {provider!r}")
    cm = get_config_manager()
    bundle = CredentialBundleBuilder(cm).build()
    creds = bundle.get(provider)
    resolved = _resolve_local_base_url(provider, creds, base_url)
    num_ctx: Optional[int] = None
    if resolved and model:
        try:
            from geny_executor.llm_client import resolve_local_context_window

            num_ctx = await resolve_local_context_window(provider, resolved, model)
        except Exception:  # noqa: BLE001 — probe is best-effort
            num_ctx = None
    return LocalContextWindowResponse(
        provider=provider, base_url=resolved, model=model, context_window=num_ctx,
    )


@router.get(
    "/subagents",
    response_model=SubagentsResponse,
    dependencies=[Depends(require_auth)],
)
async def list_subagents() -> SubagentsResponse:
    """List the registered sub-agent types so the frontend's Sub-agent
    Catalog can render them without depending on the manifest."""
    try:
        from service.agent_types import SubagentRegistryBuilder

        reg = SubagentRegistryBuilder().build()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"failed to build subagent registry: {e}")
    if reg is None:
        return SubagentsResponse(items=[])
    items: List[SubagentInfo] = []
    for at in reg.list_types():
        d = reg.get(at)
        items.append(SubagentInfo(
            agent_type=at,
            description=getattr(d, "description", ""),
            provider=getattr(d, "provider", None),
            allowed_tools=list(getattr(d, "allowed_tools", ()) or ()),
            model_override=getattr(d, "model_override", None),
        ))
    return SubagentsResponse(items=items)


# ---------------------------------------------------------------------------
# The server-wide Claude Code login used to live here: one `claude auth login`
# subprocess for the whole server, its output streamed to a modal.
#
# It is gone because a login is not a property of the server. It belongs to an
# ACCOUNT — `POST /api/llm-accounts/{id}/claude/login` — and an account has
# its own CLAUDE_CONFIG_DIR, so you can hold as many logins side by side as
# you have accounts. While both existed there were two places claiming to say
# who this server was signed in as, and the one that answered a turn was not
# the one the settings page showed.
# ---------------------------------------------------------------------------


# ── Claude Code CLI version management (keep-latest + rollback) ───────
#
# The ``claude`` binary backs the ``geny_claude_code`` provider; the image
# pins @latest at build time. These endpoints let an operator update /
# roll back at runtime, with the choice persisted + re-applied on boot.

class ClaudeCodeUpdateRequest(BaseModel):
    version: str = "latest"  # "latest" or "x.y.z"


@router.get("/claude-code/version", dependencies=[Depends(require_auth)])
async def get_claude_code_version() -> dict:
    """Installed vs. latest Claude Code version + pin/history."""
    from service.claude_code import version_service
    return await version_service.status()


@router.post("/claude-code/version/update", dependencies=[Depends(require_auth)])
async def update_claude_code_version(body: ClaudeCodeUpdateRequest) -> dict:
    """Install a specific version (or 'latest') and persist the pin."""
    from service.claude_code import version_service
    result = await version_service.install(body.version)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "update failed"))
    return {**result, **(await version_service.status())}


@router.post("/claude-code/version/rollback", dependencies=[Depends(require_auth)])
async def rollback_claude_code_version() -> dict:
    """Reinstall the previously-installed version."""
    from service.claude_code import version_service
    result = await version_service.rollback()
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "rollback failed"))
    return {**result, **(await version_service.status())}
