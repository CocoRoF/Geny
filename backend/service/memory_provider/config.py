"""Resolve the default :class:`MemorySessionRegistry` config from env vars.

Contract
--------
``MEMORY_PROVIDER``  selects the factory key:
  * ``disabled`` → registry stays dormant (``build_default_memory_config``
    returns ``None``), legacy ``SessionMemoryManager`` stays sole owner.
  * ``ephemeral`` (default) → in-memory only. Lost on restart.
  * ``file``     → filesystem-rooted. Requires ``MEMORY_ROOT``.
  * ``sql``      → SQLite or Postgres. Requires ``MEMORY_DSN``.
                   ``MEMORY_DIALECT`` (``sqlite`` | ``postgres``) overrides
                   the DSN-scheme auto-detect.

Optional: ``MEMORY_TIMEZONE``, ``MEMORY_SCOPE`` (default ``session``).

Empty strings are omitted from the config dict so
:class:`MemoryProviderFactory` falls back to its own defaults rather than
seeing blank values.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from service.memory_provider.exceptions import MemoryConfigError

_DISABLED = "disabled"


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or default).strip()


def _settings_section() -> Dict[str, Any]:
    """G.1 (cycle 20260426_2) — best-effort read of
    ``settings.json:memory``. Returns ``{}`` when unavailable so the
    caller can fall back to env vars.
    """
    try:
        from geny_executor.settings import get_default_loader
    except ImportError:
        return {}
    section = get_default_loader().get_section("memory")
    if section is None:
        return {}
    if hasattr(section, "model_dump"):
        return section.model_dump(exclude_none=True)
    if isinstance(section, dict):
        return dict(section)
    return {}


def _resolve(name_settings: str, env_name: str, default: str = "") -> str:
    """Settings.json key wins; env var is fallback."""
    settings_val = _settings_section().get(name_settings)
    if isinstance(settings_val, str) and settings_val.strip():
        return settings_val.strip()
    return _env(env_name, default)


def build_default_memory_config() -> Optional[Dict[str, Any]]:
    """Assemble the default factory config dict, or ``None`` if disabled.

    Resolution priority for every field:
      1. ``settings.json:memory.<field>`` (G.1)
      2. ``MEMORY_<FIELD>`` env var
      3. Hardcoded default (where applicable).

    Unlike ``geny-executor-web`` (greenfield), Geny is a legacy target —
    when ``MEMORY_PROVIDER`` is **unset everywhere**, the registry stays
    dormant and the existing ``SessionMemoryManager`` keeps full
    ownership. Operators must opt in explicitly.

    Raises :class:`MemoryConfigError` when the declared provider needs
    extra fields that weren't supplied.
    """
    provider = _resolve("provider", "MEMORY_PROVIDER").lower()
    if provider in ("", _DISABLED, "off", "none"):
        return None

    cfg: Dict[str, Any] = {
        "provider": provider,
        "scope": _resolve("scope", "MEMORY_SCOPE", "session") or "session",
    }

    if provider == "file":
        root = _resolve("root", "MEMORY_ROOT")
        if not root:
            raise MemoryConfigError(
                "MEMORY_PROVIDER=file requires settings.json:memory.root or "
                "MEMORY_ROOT env var to be set",
            )
        cfg["root"] = root
    elif provider == "sql":
        dsn = _resolve("dsn", "MEMORY_DSN")
        if not dsn:
            raise MemoryConfigError(
                "MEMORY_PROVIDER=sql requires settings.json:memory.dsn or "
                "MEMORY_DSN env var to be set",
            )
        cfg["dsn"] = dsn
        dialect = _resolve("dialect", "MEMORY_DIALECT")
        if dialect:
            cfg["dialect"] = dialect.lower()

    tz = _resolve("timezone", "MEMORY_TIMEZONE")
    if tz:
        cfg["timezone"] = tz

    return cfg


def load_memory_tuning(*, is_vtuber: bool) -> Dict[str, Any]:
    """G.2 (cycle 20260426_2) — return the per-session memory tuning
    knobs the agent_session._build_pipeline path consumes.

    Resolution order per knob (matches G.1's per-field convention):
      1. ``settings.json:memory.tuning.<field>``
      2. Hardcoded historical default (role-aware for ``max_inject_chars``).

    Returns a dict with keys:
      - ``max_inject_chars`` (int)
      - ``recent_turns`` (int)
      - ``enable_vector_search`` (bool)
      - ``enable_reflection`` (bool)

    ``max_inject_chars`` accepts int OR ``{"vtuber": int, "worker":
    int}`` to match the executor's role-aware historical defaults.
    """
    tuning = (_settings_section().get("tuning") or {})
    if not isinstance(tuning, dict):
        tuning = {}

    # max_inject_chars — role-aware historical defaults preserved.
    raw_mic = tuning.get("max_inject_chars")
    default_mic = 8000 if is_vtuber else 10000
    if isinstance(raw_mic, int):
        max_inject_chars = raw_mic
    elif isinstance(raw_mic, dict):
        # Per-role dict — pick the one matching is_vtuber, fall back.
        candidate = raw_mic.get("vtuber" if is_vtuber else "worker")
        max_inject_chars = candidate if isinstance(candidate, int) else default_mic
    else:
        max_inject_chars = default_mic

    return {
        "max_inject_chars": max_inject_chars,
        "recent_turns": (
            int(tuning["recent_turns"])
            if isinstance(tuning.get("recent_turns"), int)
            else 6
        ),
        "enable_vector_search": (
            bool(tuning["enable_vector_search"])
            if isinstance(tuning.get("enable_vector_search"), bool)
            else True
        ),
        "enable_reflection": (
            bool(tuning["enable_reflection"])
            if isinstance(tuning.get("enable_reflection"), bool)
            else True
        ),
    }


def is_attach_enabled() -> bool:
    """Return True when providers should be attached to pipeline Stage 2.

    Controlled by ``MEMORY_PROVIDER_ATTACH`` (default ``false``). Kept
    false until operators opt in so the legacy SessionMemoryManager path
    remains authoritative. Accepts the usual truthy strings: ``1``,
    ``true``, ``yes``, ``on`` (case-insensitive).
    """
    return _env("MEMORY_PROVIDER_ATTACH").lower() in ("1", "true", "yes", "on")


def is_api_provider_enabled() -> bool:
    """Return True when ``/api/agents/{id}/memory/*`` endpoints should
    prefer the per-session ``MemoryProvider`` over the legacy
    ``SessionMemoryManager`` path.

    Controlled by ``MEMORY_API_PROVIDER`` (default ``false``). Phase 7
    of the integration plan keeps the legacy URL paths (option B —
    "paths stay, internals swap") and gates the swap behind this flag.
    Until set, the controller logs which backend would have served the
    request but always uses the legacy path; flipping the flag enables
    provider-first routing once the body-swap PRs land.
    """
    return _env("MEMORY_API_PROVIDER").lower() in ("1", "true", "yes", "on")
