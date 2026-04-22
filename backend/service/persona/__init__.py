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

from service.persona.blocks import (
    AcclimationBlock,
    MoodBlock,
    ProgressionBlock,
    RelationshipBlock,
    VitalsBlock,
)
from service.persona.character_provider import CharacterPersonaProvider
from service.persona.dynamic_builder import DynamicPersonaSystemBuilder
from service.persona.provider import PersonaProvider, PersonaResolution

__all__ = [
    "PersonaProvider",
    "PersonaResolution",
    "DynamicPersonaSystemBuilder",
    "CharacterPersonaProvider",
    "MoodBlock",
    "RelationshipBlock",
    "VitalsBlock",
    "ProgressionBlock",
    "AcclimationBlock",
]
