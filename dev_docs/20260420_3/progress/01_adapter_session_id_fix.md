# Progress 01 — `_GenyToolAdapter` signature-introspected `session_id` injection

| Field | Value |
|-------|-------|
| Plan ref | `plan/01_immediate_fixes.md` → **PR I** |
| Master ref | `plan/00_overview.md` → **Phase 1 / PR #1** |
| PR | [#143](https://github.com/CocoRoF/Geny/pull/143) |
| Branch | `feat/tool-bridge-session-id-introspect` (squashed + deleted) |
| Merge commit | `14cf6e8` on `main` |
| Status | **Merged** |

---

## What shipped

One file, `backend/service/langgraph/tool_bridge.py` (+38/-4):

- New static method `_probe_session_id_support(tool)` that returns
  `True` iff the wrapped tool's `arun`/`run` signature can accept a
  `session_id` kwarg — either as an explicit parameter or via
  `**kwargs`.
- `__init__` now caches that answer as `self._accepts_session_id`.
- `execute(...)` gates the `input.setdefault("session_id", ...)` call
  on the cached flag; tools that don't accept it never see it.

This fixes Bug A from `analysis/01_vtuber_tool_failure.md` directly
at its source: unconditional `session_id` injection. VTuber sessions
created without an `env_id` can now invoke `news_search`,
`web_search`, and `web_fetch` without the `TypeError: unexpected
keyword argument 'session_id'` that surfaced as `detail='2'` in the
log UI.

## What did *not* ship in this PR

Intentionally scoped out:

- **No test file checked in.** Geny has no `backend/tests/` tree yet
  (the repo has never established one). A full 13-assertion smoke
  test was written and executed locally against this exact diff
  using the executor venv — results below — but was not committed
  as a `pytest` file because landing a one-off test here would
  precede the testing-infrastructure decision that belongs in a
  separate conversation.
- **No executor-side change.** That is PR #3 in the master sequence
  (executor `v0.23.0`, `tool.call_start` / `tool.call_complete`).
- **No log-handler swap.** Bug B's Geny half is PR #5.

## Verification done

### Compile

```
$ python3 -m py_compile service/langgraph/tool_bridge.py
# exit 0
```

### Smoke test (13 assertions, all passing)

Run under `/home/geny-workspace/geny-executor/.venv/bin/python` with
`importlib.util.spec_from_file_location` to load `tool_bridge.py`
directly (bypasses `service/__init__.py`, which pulls `pydantic`
via `agent_session.py` — not available in the executor venv).

Assertions covered:

| # | Scenario | Expected | Observed |
|---|----------|----------|----------|
| 1 | Probe: explicit `session_id` param | `True` | `True` |
| 2 | Probe: `**kwargs` | `True` | `True` |
| 3 | Probe: neither | `False` | `False` |
| 4 | Probe: async `arun` explicit | `True` | `True` |
| 5 | Probe: tool without `run`/`arun` | `False` | `False` |
| 6 | Probe: uninspectable callable (C builtin) | `False` | `False` |
| 7 | Live `NewsSearchTool`, filled context | no injection, no `TypeError` | OK |
| 8 | Tool accepts `session_id`, filled context | injected | injected |
| 9 | Tool has `**kwargs`, filled context | injected | injected |
| 10 | `context.session_id` is `None` | not injected | not injected |
| 11 | Input already has `session_id` | value preserved (`setdefault`) | preserved |
| 12 | `context=None` on a non-accepting tool | still runs | OK |
| 13 | Async `arun` tool | awaited, `session_id` injected | OK |

### What was *not* verified

- **End-to-end VTuber flow in production.** The standing directive
  asks for continuous PR cadence, not per-PR deploys. The live
  reproduction lands with PR #5 (executor v0.23.0 consumer in
  Geny), at which point both halves of the failure are fixed and
  the full round-trip is meaningful. Until then PR #1 only removes
  the `TypeError`; the log UI's per-call rendering remains wrong
  because the executor still doesn't emit per-call events.

## Risk assessment

Low. The behavior change is strictly *less* invasive than before:

- Tools previously forced to accept `session_id` now receive it only
  when they can. No tool loses access — tools that already accepted
  it (via explicit param or `**kwargs`) still receive it.
- The probe is run once at adapter construction, not per-call — no
  hot-path overhead.
- The `TypeError` / `ValueError` branch of `inspect.signature`
  covers C-implemented callables; the fallback is the safest
  possible answer (`False` → don't inject).

## Next PR in sequence

**P1-PR2** — this progress doc itself, as its own documentation PR.
Progress doc cadence mirrors the 20260420_2 cycle: one code PR,
then one progress PR, alternating. Followed by:

- P1-PR3: executor `v0.23.0` with additive `tool.call_start` /
  `tool.call_complete` events (separate repo, separate release).
- P1-PR5: Geny pin to `>=0.23.0,<0.24.0` + consumer swap.
- P1-PR6: progress docs for PR3 & PR5.

Phase 1 exits when the user can run a VTuber session without
`env_id` and see both (a) `news_search` actually executing and
(b) the per-call input rendered correctly in the log UI.
