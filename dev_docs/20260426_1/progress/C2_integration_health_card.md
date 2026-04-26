# C.2 — Admin Integration Health card

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/controller/admin_controller.py` — new `GET /api/admin/integration-health` aggregator + `IntegrationHealthResponse` schema + `_ring_fill` helper.
- `frontend/src/lib/api.ts` — `adminTelemetryApi.integrationHealth` + types.
- `frontend/src/components/admin/IntegrationHealthCard.tsx` (new) — pill-grid renderer with reload + auto-load on mount.
- `frontend/src/components/admin/AdminPanel.tsx` — mount the card at the top of the panel (above System Status).

## What it answers

A single endpoint reply lets the operator see, at a glance:

| Question | Source |
|---|---|
| `~/.geny/settings.json` exists at expected path? | filesystem check |
| Legacy `~/.geny/hooks.yaml` still around? | filesystem check |
| `GENY_ALLOW_HOOKS` env gate open? | env var |
| `app.state.task_runner` running? | request.app.state |
| Tool event ring fill | `service.telemetry.tool_event_ring.snapshot()` |
| Permission decision ring fill | `service.telemetry.permission_ring.snapshot()` |
| Cron history ring fill | `service.telemetry.cron_history.snapshot()` |

Operator-facing notes appear when something is amber/red (e.g. "GENY_ALLOW_HOOKS env is closed — registered hooks will not fire.").

## Why

Audit (cycle 20260426_1, analysis/02 §B.2 / §B.4 / §C.1) — these wiring checks were spread across separate endpoints (some had no UI at all) and required an operator to deduce the integration state from logs. The new card collapses them into one render.

## Tests

No new test files; the endpoint is a thin aggregation over already-tested helpers (settings paths, hooks.yaml resolution, env var read, ring buffer snapshot). CI lint + tsc + Next build is the gate.

## Out of scope

- Settings-section reader map (D.2).
- Live reload action button (E.1).
- Per-ring "click to inspect" deep-link.
