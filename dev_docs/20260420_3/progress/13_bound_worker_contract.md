# Progress 13 — BoundWorker contract doc

| Field | Value |
|-------|-------|
| Plan ref | `plan/03_vtuber_worker_binding.md` → **PR D** |
| Master ref | `plan/00_overview.md` → **Phase 3 / PR 24** |
| Geny PR | [#166](https://github.com/CocoRoF/Geny/pull/166) |
| Geny merge commit | `484cbb9` on `main` |
| Status | **Merged** |

---

## Why this PR exists

Across Phase 3, PRs 18 / 20 / 22 shipped the code and prose for the
VTuber-Worker binding but scattered the rationale across four
commits and their progress docs. A developer arriving at
`backend/docs/` looking for "what is a bound Worker?" would find
no single page answering it. PR 24 consolidates the invariants,
lifecycle, and failure modes into the docs tree, so future
readers don't need to reverse-engineer the contract from
`agent_session_manager.py`.

This is the closing code-ish PR of the 25-PR master plan. PR 25
(this doc) is the final progress entry.

## What changed

### `backend/docs/BOUND_WORKER.md` (new)

230-line spec with sections:

- **Intent** — why persona/execution split exists and what problem
  it solves.
- **Invariants** — I1 (1:1), I2 (bind at creation), I3 (dissolve
  at termination), I4 (no hot-swap), I5 (bound Workers can't
  recursively bind). Each invariant names the specific code that
  enforces it.
- **Session lifecycle** — creation sequence as an ASCII flow
  diagram matching the actual `create_session` control flow,
  termination table covering the four ways either side can go
  away, and a note on restart restoration using
  `_build_system_prompt`'s VTuber branch.
- **env_id resolution** — truth table for the four
  `bound_worker_env_id` cases (None / default explicit / custom
  env / unknown env).
- **Failure modes** — Worker unavailable at send time, inbox
  full, tool call timeout, orphan Worker, recursion guard
  failure. Each failure mode names the observed symptom and
  the expected recovery path.
- **Non-goals** — multi-Worker fan-out, hot-swap, cross-VTuber
  sharing, dynamic rebind. All four explicitly out of scope with
  the rationale spelled out, so future readers know these
  weren't accidentally unimplemented.
- **Related code** — table mapping the eight files that touch
  the binding to their role.
- **See also** — cross-links to `SESSIONS.md`, `PROMPTS.md`,
  `EXECUTION.md`, plus the original plan docs.

### `backend/docs/BOUND_WORKER_KO.md` (new)

Mirrors the English version section-for-section. Matches the
existing bilingual convention in `backend/docs/` (every major
doc has a `_KO.md` counterpart).

## One correction made during writing

An early draft asserted "bound Workers are *not* always-warm"
under the idle-monitor row of the termination table. A quick
grep of `agent_session.py` found the actual property:

```python
@property
def _is_always_on(self) -> bool:
    if self._role == SessionRole.VTUBER:
        return True
    if self._session_type == "bound" and self._linked_session_id:
        return True
    return False
```

Bound Workers are in fact always-on — the property name is
`_is_always_on`, not `_is_always_warm`, and it returns `True`
for both VTubers and their bound Workers (the "tightly-coupled
unit must stay warm together" rationale in the docstring).
Fixed in both language variants before commit.

(Sidenote: `agent_session.py:341` still carries a stale
docstring — `"Session type: 'vtuber', 'cli', or None."` The
`'cli'` literal was renamed to `'bound'` in PR 18, but the
docstring wasn't updated. Noted but not fixed here — PR 24 is
scoped to docs creation, not touching up missed renames. Leave
as a follow-up if anyone cares.)

## Scope boundary

Per plan PR D: *"document BoundWorker contract in `backend/docs/`
(invariants, lifecycle, failure modes)."*

Included (within scope):

- New `BOUND_WORKER.md` + `BOUND_WORKER_KO.md` at
  `backend/docs/` root, matching existing naming convention.
- Cross-references from the new doc to existing docs and the
  plan. No back-links added from existing docs — that's the
  reader's next hop, not a code-touch.

Kept out (not in this PR):

- Updates to `backend/docs/SESSIONS.md` / `SESSIONS_KO.md` to
  cross-link `BOUND_WORKER.md`. These would be small edits to
  existing files, but each one broadens blast radius and risks
  merge conflicts with unrelated doc work. Defer.
- Fix for the stale `_session_type` docstring in
  `agent_session.py:341`. Out of scope for a docs PR.
- `prompts/vtuber.md` pointer to the new doc. Prompts are not
  for developer onboarding; the VTuber persona doesn't benefit
  from knowing the contract doc exists.

## Smoke test

None — markdown-only content. Verification is reading the
document and checking that every code reference is live.
Manually spot-checked:

- `_is_always_on` → `agent_session.py:345`  ✓
- `session_type != "bound"` guard → `agent_session_manager.py:603` ✓
- `role == "vtuber" and request.linked_session_id` restoration →
  `agent_session_manager.py:275` ✓
- `DelegationTag.CLI_RESULT` → `service/vtuber/delegation.py`  ✓
  (via PR 22 progress doc's file list)

## Manual verification

- [ ] Click each link in **See also** and **Related code** from
      the rendered doc on GitHub. Confirm `SESSIONS.md`,
      `PROMPTS.md`, `EXECUTION.md`, and the two plan files all
      resolve.
- [ ] Read the **Invariants** section as a new engineer. Do the
      five invariants compose a mental model that lets the
      reader predict the system's behavior without running it?
- [ ] Compare the **Creation sequence** diagram against
      `create_session` in `agent_session_manager.py`. Are the
      steps in the right order? (Manual diff; no automated
      check.)

## Phase 3 status

| # | Title | PR | Status |
|---|-------|----|--------|
| 18 | Rename `cli_*` → `bound_worker_*` | #160 | Done |
| 19 | Progress doc for PR 18 | #161 | Done |
| 20 | Reshape VTuber auto-pair block | #162 | Done |
| 21 | Progress doc for PR 20 | #163 | Done |
| 22 | Rewrite `prompts/vtuber.md` delegation | #164 | Done |
| 23 | Progress doc for PR 22 | #165 | Done |
| 24 | Document BoundWorker contract | #166 | **Done** |
| 25 | Progress doc for PR 24 | *this doc* | **Done** |

## Master plan status

All three phases complete. Full 25-PR run:

### Phase 1 — Executor event-shape foundation (PRs 1–6)

| # | Title | Status |
|---|-------|--------|
| 1 | `_GenyToolAdapter` signature-introspects `session_id` | Done |
| 2 | Progress doc for PR 1 | Done |
| 3 | executor v0.23.0 — `tool.call_start` / `tool.call_complete` | Done |
| 4 | Progress doc for PR 3 | Done |
| 5 | Geny pin 0.23.0 + consume `tool.call_start` | Done |
| 6 | Progress doc for PR 5 | Done |

### Phase 2 — ENV-based session model (PRs 7–17)

| # | Title | Status |
|---|-------|--------|
| 7 | executor v0.24.0 — `Pipeline.attach_runtime` | Done |
| 8 | Progress doc for PR 7 | Done |
| 9 | Geny pin 0.24.0 | Done |
| 10 | Populate `build_default_manifest.stages` | Done |
| 10a | executor v0.25.0 — register `binary_classify` | Done |
| 11 | Progress doc for PRs 10/10a | Done |
| 12 | Seed WORKER/VTUBER envs + `ROLE_DEFAULT_ENV_ID` | Done |
| 13 | Progress doc for PR 12 | Done |
| 14 | `AgentSessionManager` always resolves `env_id` | Done |
| 15 | Progress doc for PR 14 | Done |
| 16 | `AgentSession._build_pipeline` → `attach_runtime` only | Done |
| 16a | executor v0.26.0 — `attach_runtime(system_builder, tool_context)` | Done |
| 16b | Geny pin 0.26.0 | Done |
| 16c | Progress doc for v0.26.0 + pin bump | Done |
| 17 | Progress doc for PR 16 | Done |

### Phase 3 — VTuber ↔ Bound Worker (PRs 18–25)

| # | Title | Status |
|---|-------|--------|
| 18 | Rename `cli_*` → `bound_worker_*` | Done |
| 19 | Progress doc for PR 18 | Done |
| 20 | Reshape VTuber auto-pair block | Done |
| 21 | Progress doc for PR 20 | Done |
| 22 | Rewrite `prompts/vtuber.md` delegation | Done |
| 23 | Progress doc for PR 22 | Done |
| 24 | Document BoundWorker contract | **Done** |
| 25 | Progress doc for PR 24 | **Done** |

## What this run delivered

In order of the three phases:

1. **Event-shape foundation** — the executor now emits typed
   `tool.call_start` / `tool.call_complete` events with a
   consistent `session_id` threading, and the Geny logger
   consumes them. This was the quiet-but-load-bearing plumbing
   that the later phases implicitly rely on.

2. **ENV-based session model** — every Geny session now flows
   through `resolve_env_id(role, explicit)` → manifest →
   `Pipeline.attach_runtime`. The preset-based fallback
   (`GenyPresets.*`) is gone. Adding a new session type is now
   "write a manifest" rather than "write a preset class and
   wire it into the executor."

3. **Bound Worker as a first-class feature** — VTuber sessions
   automatically spawn a bound Worker, back-link it, and inject
   its `session_id` into the persona prompt. Delegation is a
   plain DM. The contract is documented at
   `backend/docs/BOUND_WORKER.md`.

## Next

Master plan closed. No follow-on PRs in the 20260420_3 cycle.

Potential follow-ups (out of scope for this run):

- Fix stale `_session_type` docstring in `agent_session.py:341`
  (still says `'vtuber', 'cli', or None`).
- Cross-link `BOUND_WORKER.md` from `SESSIONS.md` /
  `PROMPTS.md` to improve discovery.
- Rename `[CLI_RESULT]` / `[ACTIVITY_TRIGGER]` tag literals →
  `[WORKER_RESULT]` / `[ACTIVITY_TRIGGER]`. Touches 4+ Python
  modules in a carefully sequenced way (emitters + matchers +
  TTS filter + prompts). Documented in progress 12 as a known
  legacy marker.
- Bound-Worker smoke tests as pytest fixtures (not `/tmp/` ad
  hoc scripts). Requires a test harness for MCP + shared
  folder + memory registry that doesn't yet exist.

None of these are urgent. The contract is complete; the code
matches the contract; the docs match the code.
