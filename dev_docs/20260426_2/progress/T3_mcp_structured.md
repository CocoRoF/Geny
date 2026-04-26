# T.3 — MCP servers structured editor

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `frontend/src/components/tabs/McpServersTab.tsx` — full rewrite of the edit modal to support a structured form alongside the existing raw JSON textarea.

## What it changes

The "Add / Edit MCP server" modal gains a **mode toggle** (Structured | JSON) and per-transport structured fields:

- **Transport**: dropdown picker (`stdio | http | sse`).
- **stdio transport**: `command` (single executable input) + `args` (textarea, one per line).
- **http / sse transport**: `url` input + headers (key/value rows).
- **Env (all transports)**: extra subprocess env (key/value rows).

Switching modes syncs the in-memory state:
- **Structured → JSON**: serialise structured fields to a JSON object, dump into the textarea.
- **JSON → Structured**: parse the textarea (best-effort); unknown keys land in the JSON view's authoritative state but won't render in structured mode (operator can flip back to JSON mode to see them).

The save handler honours the active mode — structured mode reconstructs a JSON object from the form fields; JSON mode parses the textarea.

Existing `customMcpApi.create / replace` endpoints are unchanged — both modes produce the same JSON object on the wire.

## Why

Audit (cycle 20260426_2, analysis/02 Tier 5) — MCP server config was raw JSON only. Operators editing OAuth headers or stdio args had to manually quote / escape inside a textarea. Structured mode catches typos at edit time + makes the schema discoverable.

## Tests

UI-only changes; CI lint + tsc + Next build is the gate.

## Out of scope

- Per-transport schema validation (e.g. require `url` for http) — defer; the existing endpoint validates server-side.
- Header presets (Authorization Bearer, custom auth schemes) — defer.
- Per-server enable/disable toggle — that lives in MCPAdminPanel (live-session view), not here.
