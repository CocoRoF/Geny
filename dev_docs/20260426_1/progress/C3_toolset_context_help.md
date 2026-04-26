# C.3 — ToolSets context help (env-driven note)

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `frontend/src/components/tabs/ToolSetsTab.tsx` — small persistent note strip below the header.
- `frontend/src/components/modals/CreateSessionModal.tsx` — preset selector tooltip swapped for an i18n key with corrected semantics (was hard-coded English, said the wrong thing).
- `frontend/src/lib/i18n/{en,ko}.ts` — `toolSetsTab.envDrivenNote.{title,body}` + `createSession.toolPreset` / `toolPresetHelp`.

## Why

Audit (cycle 20260426_1, analysis/02 §B.3) — the env-driven refactor moved tool ownership from preset to manifest. The UI still framed presets as "select which tools the agent has", which is misleading. Selecting a preset on an env-driven session mostly affects MCP server filtering (`agent_session_manager.py:539-542`).

## What it changes

- ToolSets tab gets a persistent note: "Tool list is owned by the bound environment manifest. … To change the actual tool list of a session, edit its environment manifest."
- CreateSessionModal preset selector now shows: "In env-driven sessions the tool list is owned by the bound environment manifest. The selected preset mainly influences MCP server filtering."

i18n in en + ko.

## Tests

Type-only changes; CI lint + tsc + Next build is the gate.

## Out of scope

- Removing the preset selector from CreateSessionModal entirely (UX call; defer to a separate cleanup PR).
- Removing `tool_preset_id` from the AgentSession constructor (still useful as metadata for SessionInfo).
