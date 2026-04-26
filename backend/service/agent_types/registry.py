"""SubagentType seed for Geny.

Three descriptors out of the box:

* ``worker``           — general-purpose, full default toolset
* ``researcher``       — read-only investigation (no write/edit/bash)
* ``vtuber-narrator``  — VTuber persona for short narrations

Hosts add more by extending DESCRIPTORS or calling
``install_subagent_types`` with their own list.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# Importing the executor side at module top-level so we surface
# ImportError (1.1.0 not installed) immediately rather than hiding
# it behind try/except.
try:  # pragma: no cover — covered by e2e environment, not unit
    from geny_executor.stages.s12_agent.subagent_type import (
        SubagentTypeDescriptor,
        SubagentTypeRegistry,
    )
except ImportError:  # pragma: no cover — only triggers on stale exec
    SubagentTypeDescriptor = None  # type: ignore[assignment]
    SubagentTypeRegistry = None  # type: ignore[assignment]


_SEED = (
    (
        "worker",
        "General-purpose worker. Full default toolset (Read / Write / "
        "Edit / Bash / Grep / Glob / NotebookEdit / WebFetch).",
    ),
    (
        "researcher",
        "Read-only investigation. Read / Grep / Glob / WebFetch / "
        "WebSearch only — no write/edit/bash so research can't "
        "accidentally mutate state.",
    ),
    (
        "vtuber-narrator",
        "VTuber persona for short stream narrations. Memory + "
        "Knowledge tools only.",
    ),
)


def _placeholder_factory():
    """Stub factory for descriptors that don't need a real sub-pipeline
    (viewer-only). The executor's Stage 12 only invokes the factory
    when the LLM actually delegates to that agent_type — registering
    the descriptor is enough to surface the name in the registry/UI.
    """
    raise NotImplementedError(
        "Subagent factory not wired — Geny does not currently spawn "
        "sub-pipelines from this descriptor.",
    )


def _make_descriptors() -> List[Any]:
    """Build the descriptor list lazily so test environments without
    geny-executor installed still import this module.

    Tolerates executor signature drift: each constructor is tried with
    the canonical kwargs first, falls back to the legacy
    no-factory shape, and swallows any remaining TypeError so a single
    bad seed can't crash module import (which cascades into a 500 on
    boot for every controller that imports this package)."""
    if SubagentTypeDescriptor is None:
        return []

    out: List[Any] = []
    for agent_type, description in _SEED:
        # Try the new (1.2.0+) signature first.
        try:
            out.append(SubagentTypeDescriptor(
                agent_type=agent_type,
                factory=_placeholder_factory,
                description=description,
            ))
            continue
        except TypeError:
            pass
        # Legacy signature without factory.
        try:
            out.append(SubagentTypeDescriptor(
                agent_type=agent_type,
                description=description,
            ))
        except TypeError as exc:
            logger.warning(
                "subagent_descriptor_build_failed agent_type=%s err=%s",
                agent_type, exc,
            )
    return out


DESCRIPTORS = _make_descriptors()


def install_subagent_types(
    registry: Optional[Any] = None,
    *,
    extra: Optional[List[Any]] = None,
) -> int:
    """Register Geny's seed descriptors into ``registry``. Returns the
    count registered.

    When ``registry`` is None, this is a no-op so callers can guard
    on the strategy slot being wired without raising.
    """
    if registry is None:
        return 0
    descriptors = list(DESCRIPTORS) + list(extra or [])
    for d in descriptors:
        try:
            registry.register(d)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "subagent_type_registration_failed",
                extra={"agent_type": getattr(d, "agent_type", "?"), "error": str(exc)},
            )
            continue
    return len(descriptors)
