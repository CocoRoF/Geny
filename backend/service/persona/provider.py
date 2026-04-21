"""PersonaProvider Protocol + PersonaResolution dataclass.

Contract: ``DynamicPersonaSystemBuilder.build`` calls ``provider.resolve`` on
every pipeline run and composes the returned blocks through
``ComposablePromptBuilder``. The provider owns all mutable persona state
(character overrides, static prompt overrides, appended context).

``resolve`` is **synchronous** — ``PromptBuilder.build`` is sync by executor
contract (``SystemStage.execute`` calls ``builder.build(state)`` without
await), so smuggling async through that boundary would require an event-loop
hack. All provider-side I/O (character markdown reads, DB lookups) is
expected to be cached by the provider at configuration time or on first use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Protocol, runtime_checkable

from geny_executor.stages.s03_system.interface import PromptBlock


@dataclass(frozen=True)
class PersonaResolution:
    """Single-turn persona snapshot returned by ``PersonaProvider.resolve``.

    Attributes:
        persona_blocks: Ordered ``PromptBlock`` instances that produce the
            persona portion of the system prompt. Rendered in list order.
            Empty list is valid (yields an empty persona section).
        system_tail: Optional text appended *after* all other system-prompt
            blocks. Reserved for short, high-volatility content that should
            not sit in a cache-controlled block.
        cache_key: Stable token summarising inputs. Identical cache_keys
            across turns signal to callers that the persona section is
            cacheable unchanged. Empty string means "do not cache".
    """

    persona_blocks: List[PromptBlock] = field(default_factory=list)
    system_tail: Optional[str] = None
    cache_key: str = ""


@runtime_checkable
class PersonaProvider(Protocol):
    """Per-turn persona resolver.

    Implementations must be safe for concurrent sessions — typically by
    keying all mutable state on ``session_id``. The caller
    (``DynamicPersonaSystemBuilder``) passes the live ``PipelineState`` and a
    provider-agnostic ``session_meta`` mapping
    (``session_id``, ``is_vtuber``, ``character_id``, ``owner_user_id`` …).
    """

    def resolve(
        self,
        state: Any,
        *,
        session_meta: dict,
    ) -> PersonaResolution:
        """Return the persona snapshot to use for this turn."""
        ...
