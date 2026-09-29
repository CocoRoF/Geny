"""Host-side memory tool catalogue prompt block.

Cycle 20260503_7. Companion to ``geny-executor`` 1.15.0's
``_MEMORY_USAGE_CLAUSE`` decoupling. The executor preset now ships
generic *policy* only ("consult memory before asking the user; trust
Pinned Facts"); the concrete *tool catalogue* — names, semantics,
ladder — belongs to the host (Geny) because Geny owns the tool
identities.

This module exposes :class:`HostMemoryToolsBlock`, a
:class:`PromptBlock` Geny appends to its system-prompt tail (after
``MemoryContextBlock``) so the agent sees:

  PersonaBlock              ← who the agent is
  DateTimeBlock             ← current time
  MemoryContextBlock        ← Pinned Facts + Relevant Knowledge (data)
  HostMemoryToolsBlock      ← Memory Usage policy + concrete tools

The block is static — no per-state context — so its ``render`` just
emits the constant string. Keep the catalogue here in lockstep with
the actual tools registered in ``backend/tools/built_in/memory_tools.py``.
"""

from __future__ import annotations

from typing import Any

from geny_executor.stages.s03_system.artifact.default.builders import (
    PromptBlock,
)


# The full Memory Usage clause for Geny: executor's policy +
# Geny's concrete tool ladder + write-path index. Centralised here
# (rather than scattered across preset prompts or agent_session.py)
# so a tool name change in ``memory_tools.py`` only ripples through
# this single file.
# Policy only — the concrete tool catalogue (names/args) is delivered to the
# model via tool schemas, so the prompt carries only behaviour the schemas can't.
_HOST_MEMORY_USAGE_AND_TOOLS = """\
## Memory Usage

You have a persistent long-term memory (its tools' schemas are provided to you).
The **Pinned Facts** section of this prompt — when present — holds authoritative
must-know facts about the user, you, and the ongoing work; never claim ignorance
of anything stated there. The **Vault Map** summarises what's stored.

When intent is ambiguous and the answer may already be remembered, consult memory
before asking something the user may have already answered — and pin facts worth
always knowing. Do this silently; don't announce the lookup.

Your earlier turns in this conversation are in the message history: treat them as
history, not as facts to re-verify, and act on the current request."""


class HostMemoryToolsBlock(PromptBlock):
    """Static block that appends Geny's memory-usage policy + tool
    catalogue to the system prompt's tail.
    """

    @property
    def name(self) -> str:
        return "host_memory_tools"

    def render(self, state: Any) -> str:  # noqa: ARG002 — state unused
        return _HOST_MEMORY_USAGE_AND_TOOLS


__all__ = ["HostMemoryToolsBlock"]
