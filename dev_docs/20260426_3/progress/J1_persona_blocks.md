# J.1 — Persona blocks per-role config

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/service/settings/sections.py` — `PersonaConfigSection` (`tail_blocks_by_role: Dict[str, List[str]]`).
- `backend/service/settings/install.py` — `register_section("persona", PersonaConfigSection)`.
- `backend/service/settings/known_sections.py` + `tests/service/settings/test_known_sections.py` — reader map + lock test.
- `backend/service/persona/blocks_resolver.py` (new) — `resolve_tail_blocks(role)` reads settings, falls back to historical default.
- `backend/service/executor/agent_session.py` — `_build_pipeline` consumes the resolver instead of hardcoding `[DateTimeBlock(), MemoryContextBlock()]`.
- `backend/tests/service/persona/test_blocks_resolver.py` (new) — 6 unit cases.

## What it changes

`settings.json:persona.tail_blocks_by_role` lets operators reorder / drop the tail blocks the system-prompt builder uses, per role:

```json
{
  "persona": {
    "tail_blocks_by_role": {
      "vtuber": ["datetime"],
      "worker": ["datetime", "memory_context"],
      "default": ["datetime", "memory_context"]
    }
  }
}
```

Resolution order per role:
1. Role-specific list.
2. `"default"` list.
3. Historical hardcoded `["datetime", "memory_context"]`.

Available block keys: `datetime`, `memory_context`. Unknown keys log a warning + are skipped (no crash).

The resolver is consumed by both branches in `_build_pipeline` — the dynamic builder (`DynamicPersonaSystemBuilder.tail_blocks`) and the legacy `ComposablePromptBuilder.blocks`.

## Why

Audit (cycle 20260426_3, analysis/01) — the s03 (System) tail-block chain was hardcoded. Operators wanting to drop `MemoryContextBlock` for a stateless persona variant or reorder for token-budget control had to patch the source.

## Tests

6 unit cases (default fallback, role override, "default" key override, unknown key skip, empty list fallback, garbage section coercion). Skip-on-geny_executor; CI runs.

## Out of scope

- Adding new block types via the registry (e.g. operator-defined blocks). The current resolver only knows `datetime` + `memory_context`; extending requires importing more executor builders + listing them in `_builder_map`. Defer to future cycle if demand emerges.
- The role-driven persona block itself (mood / relationship / vitals / progression / acclimation) — those come from the persona provider, not the tail. J.1's scope is the tail only.
