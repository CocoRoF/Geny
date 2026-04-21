"""Persona service — dynamic system prompt assembly.

Public API:
    - ``PersonaProvider`` Protocol: one ``resolve(state, session_meta)`` per turn.
    - ``PersonaResolution``: persona_blocks + optional system_tail + cache_key.
    - ``DynamicPersonaSystemBuilder``: executor ``PromptBuilder`` that calls
      the provider every turn and composes resolved blocks via
      ``ComposablePromptBuilder``.
    - ``MoodBlock``/``RelationshipBlock``/``VitalsBlock``/``ProgressionBlock``:
      no-op stubs for X1. X3/X4 replace ``render`` with real CreatureState reads.
"""

from backend.service.persona.blocks import (
    MoodBlock,
    ProgressionBlock,
    RelationshipBlock,
    VitalsBlock,
)
from backend.service.persona.dynamic_builder import DynamicPersonaSystemBuilder
from backend.service.persona.provider import PersonaProvider, PersonaResolution

__all__ = [
    "PersonaProvider",
    "PersonaResolution",
    "DynamicPersonaSystemBuilder",
    "MoodBlock",
    "RelationshipBlock",
    "VitalsBlock",
    "ProgressionBlock",
]
