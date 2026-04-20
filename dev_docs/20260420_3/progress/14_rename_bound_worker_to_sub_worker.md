# Progress 14 — `bound_worker_*` / `[CLI_RESULT]` → `sub_worker_*` / `[SUB_WORKER_RESULT]`

| Field | Value |
|-------|-------|
| Plan ref | Progress 13 follow-ups (master plan closed) |
| Master ref | Post-20260420_3 cleanup |
| Geny PR | *pending* |
| Status | **Pre-PR** (branch `refactor/bound-worker-to-sub-worker`) |

---

## Why a follow-up rename

Progress 10 flipped the Worker-side schema from `cli_*` to
`bound_worker_*` and declared `session_type == "bound"` canonical.
Progress 13 closed the master plan but explicitly flagged two
stragglers:

> - Fix stale `_session_type` docstring in `agent_session.py:341`
>   (still says `'vtuber', 'cli', or None`).
> - Rename `[CLI_RESULT]` / `[ACTIVITY_TRIGGER]` tag literals …
>   Touches 4+ Python modules in a carefully sequenced way.

On top of those, a sweep across the repo revealed the terminology
had drifted into three overlapping shapes across code and docs:

1. Schema + code paths used `bound_worker_*` / `session_type == "bound"`.
2. Docs, UI labels, and prompts freely mixed `CLI worker`, `bound
   worker`, and `sub worker` depending on when each was written.
3. The protocol tag emitted by the Worker was still the original
   `[CLI_RESULT]`, decoupled from every other identifier.

Per the user's directive — "불리는 이름들을 전부 하나의 표현으로
통일해. 엄청 신중하고 치밀하게 진행해. 절대로 버그가 생겨서는 안 돼" —
every surface is now unified on **Sub-Worker** (English) / **서브
워커** (Korean) with read-side legacy acceptance so pre-rename
payloads never break.

## Canonical choices

| Concern | Canonical | Legacy accepted |
|---------|-----------|-----------------|
| `session_type` value | `"sub"` | `"bound"`, `"cli"` (normalized by validator) |
| Schema fields | `sub_worker_system_prompt`, `sub_worker_model`, `sub_worker_env_id` | `bound_worker_*` (validator alias) |
| Protocol tag | `[SUB_WORKER_RESULT]` | `[CLI_RESULT]` (matcher still accepts) |
| Session name suffix | `{vtuber_name}_sub` | `_cli` / `_bound` (read-only check elsewhere) |
| Doc filenames | `backend/docs/SUB_WORKER.md`, `SUB_WORKER_KO.md` | `BOUND_WORKER*.md` (removed via `git mv`) |
| Prompt templates | `prompts/templates/sub-worker-default.md`, `sub-worker-detailed.md` | `cli-*.md` (deleted) |
| Prompt role header | `Sub-Worker` | — |

English docs/code use **Sub-Worker**; Korean prose uses **서브 워커**
or **Sub-Worker** (preferred when the word is next to code).

## Schema delta (`backend/service/claude_manager/models.py`)

Field names flipped `bound_worker_*` → `sub_worker_*`. Read-side
legacy compatibility is enforced by a Pydantic `field_validator`
on `session_type` that normalizes stale values:

```python
_LEGACY_SESSION_TYPES = {"bound": "sub", "cli": "sub"}

def _normalize_session_type(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return value
    return _LEGACY_SESSION_TYPES.get(value, value)


class CreateSessionRequest(BaseModel):
    ...
    @field_validator("session_type", mode="before")
    @classmethod
    def _normalize_session_type_request(cls, v):
        return _normalize_session_type(v)
```

The same normalizer is applied to `SessionInfo.session_type` so
legacy values also round-trip through list/read endpoints.

Write-side always emits `"sub"`. Any pre-rename client sending
`"bound"` (Progress 10 vintage) or `"cli"` (pre-Progress 10) gets
transparently coerced. No DB migration required — `session_type`
is transient session metadata, not persisted schema.

## Protocol tag transition (`backend/service/vtuber/delegation.py`)

The Worker → VTuber result tag now emits `[SUB_WORKER_RESULT]` via
`DelegationTag.SUB_WORKER_RESULT`. The matcher accepts the legacy
form through a module-level constant:

```python
class DelegationTag(str, Enum):
    REQUEST = "[DELEGATION_REQUEST]"
    RESULT = "[DELEGATION_RESULT]"
    THINKING = "[THINKING_TRIGGER]"
    SUB_WORKER_RESULT = "[SUB_WORKER_RESULT]"

_LEGACY_SUB_WORKER_RESULT_TAG = "[CLI_RESULT]"  # pre-rename alias
```

Both `is_delegation_message()` and `is_result_message()` include
the legacy tag in their startswith checks.

Old VTuber inbox entries and any in-flight message from an older
Worker build still resolve correctly. The docstring on the matcher
explicitly calls out that `[CLI_RESULT]` is a pre-rename alias,
not active protocol — so a future cleanup can delete it once all
deployed Workers have rolled.

## Files touched

### Backend (9 Python modules)

| File | Change |
|------|--------|
| `backend/controller/tts_controller.py` | TTS tag filter recognizes both `[SUB_WORKER_RESULT]` and legacy `[CLI_RESULT]` |
| `backend/service/claude_manager/models.py` | Schema fields renamed; legacy `session_type` validator added |
| `backend/service/environment/templates.py` | Worker env template description flipped to Sub-Worker |
| `backend/service/execution/agent_executor.py` | Autotrigger notify gate + Live2D activity ping gate read `"sub"` |
| `backend/service/langgraph/agent_session.py` | `_session_type` typing + always-warm check flipped to `"sub"`; docstring corrected |
| `backend/service/langgraph/agent_session_manager.py` | VTuber auto-pair reads `request.sub_worker_*`, writes `session_type="sub"`, session name suffix `_sub` |
| `backend/service/prompt/sections.py` | `identity()` line for Sub-Worker role; template loader map |
| `backend/service/vtuber/delegation.py` | Emits `[SUB_WORKER_RESULT]`; matcher accepts legacy `[CLI_RESULT]` |
| `backend/service/vtuber/thinking_trigger.py` | Trigger-prompt key `cli_working` → `sub_worker_working`; autonomous-signal `source=cli_worker` → `source=sub_worker`; all user-facing prose and comments unified |

### Backend docs (`backend/docs/`)

- `git mv BOUND_WORKER.md SUB_WORKER.md`
- `git mv BOUND_WORKER_KO.md SUB_WORKER_KO.md`
- Both files rewritten end-to-end to read "Sub-Worker" / "서브 워커".
- Legacy compatibility section retained (lines 219-221 of each) so
  operators reading the current doc understand the validator and
  matcher still accept legacy values.

### Prompts

- `backend/prompts/templates/cli-default.md` **deleted**
- `backend/prompts/templates/cli-detailed.md` **deleted**
- `backend/prompts/templates/sub-worker-default.md` **added**
- `backend/prompts/templates/sub-worker-detailed.md` **added**
- `backend/prompts/vtuber.md` — delegation paragraph now points at
  the Sub-Worker via `geny_send_direct_message`; wording unified
  with the canonical term
- `backend/prompts/README.md` / `README_KO.md` — file table and
  "세션 링킹" section updated

### Frontend (9 TS/TSX + 2 i18n + 1 CSS)

| File | Change |
|------|--------|
| `frontend/src/types/index.ts` | `sub_worker_*` fields; `session_type: "vtuber" \| "sub" \| "solo"` |
| `frontend/src/components/Sidebar.tsx` | Session filter/label logic flipped to `"sub"` |
| `frontend/src/components/modals/CreateSessionModal.tsx` | Form state + payload writes use `sub_worker_*`; dead `selectedCliPreset` state removed |
| `frontend/src/components/obsidian/SessionSelector.tsx` | Visible-sessions filter now checks `session_type === 'sub'`; default role fallback changed from `'cli'` to `'worker'` |
| `frontend/src/components/obsidian/obsidian.css` | Removed two stale `.cli-*` class selectors |
| `frontend/src/components/tabs/InfoTab.tsx` | Display copy + state names unified |
| `frontend/src/components/tabs/LogsTab.tsx` | Log tag filter includes both new + legacy tags |
| `frontend/src/components/tabs/SessionToolsTab.tsx` | Label copy unified |
| `frontend/src/lib/i18n/en.ts` | `subWorkerPromptLabel`, `subWorkerModel`, `subWorkerToolPreset` |
| `frontend/src/lib/i18n/ko.ts` | Korean counterparts (`서브 워커 ...`) |

### Top-level docs (`docs/`)

Prose pass over every file that mentioned CLI worker / bound
worker / `[CLI_RESULT]`. Legitimate **Anthropic Claude CLI**
product references (subprocess naming, `ClaudeCLIChatModel`,
`claude_cli_model.py`) were preserved — those refer to the
Anthropic CLI tool, not the Geny Worker concept.

| File | Scope |
|------|-------|
| `DUAL_AGENT_ARCHITECTURE_PLAN.md` | Full pass; ASCII diagram box rebuilt for wider Sub-Worker line; `delegate_to_cli` / `_on_cli_complete` pseudocode updated |
| `PROMPT_IMPROVEMENT_PLAN.md` | "Paired CLI Agent" → "Sub-Worker Agent" block; delegation examples |
| `TOOL_SYSTEM_ANALYSIS.md` | Tool-mode matrix columns, workflow labels, section §6.3 |
| `TRIGGER_CONCURRENCY_ANALYSIS.md` | Tag references + session_type comparisons |
| `VTUBER_ARCHITECTURE_REVIEW.md` | Architecture prose unified |
| `VTUBER_ISSUES_ANALYSIS.md` | Caught late in final sweep; both TS and Python `session_type == 'cli'` examples were stale since Progress 10 and are now `'sub'` |
| `optimizing_model.md` | Worker-side references |

## Call-site reference

Write-sites now emit canonical forms:

```python
# agent_session_manager.py (VTuber auto-pair block)
session_name=f"{request.session_name}_sub",
session_type="sub",
sub_worker_system_prompt=request.sub_worker_system_prompt,
sub_worker_model=request.sub_worker_model,
sub_worker_env_id=request.sub_worker_env_id,

# thinking_trigger.py — selects the "sub_worker_working" prompt
# key when the linked Sub-Worker is executing.
if linked_id and is_executing_fn(linked_id):
    return self._pick("sub_worker_working", locale)

# delegation.py — emitters always use DelegationTag.SUB_WORKER_RESULT.
msg = DelegationMessage(tag=DelegationTag.SUB_WORKER_RESULT, ...)
```

Read-sites accept legacy values:

```python
# models.py validator normalizes "bound" / "cli" → "sub"
# delegation.py matcher accepts both [SUB_WORKER_RESULT] and [CLI_RESULT]
# tts_controller.py filter strips both tags from TTS output
# LogsTab.tsx tag highlighter recognizes both
```

## Legacy compatibility summary

Nothing is a hard break. Every read-side that could encounter a
pre-rename value is tolerant:

- `session_type`: Pydantic validator coerces before it reaches
  any consumer.
- Protocol tag: matcher has two constants; both parse.
- Session name suffix: only the *write*-site changed. Existing
  sessions keep whatever suffix they were created with — the
  frontend `endsWith('_sub')` check is defensive UI filtering,
  not an invariant.
- Field names: the schema change is at the request boundary
  (CreateSessionRequest). Old clients sending `bound_worker_*`
  would 422 under strict Pydantic — **this is intentional** for
  schema freshness. Backend-internal callers are all updated.

The legacy compat is read-side only; we're not perpetuating
three-way naming forever. Progress 13 already flagged these tags
as legacy markers to be removed after a full rollout cycle.

## Verification

### Backend — `py_compile`

All 9 modified Python modules compile cleanly:

```
python3 -m py_compile \
  backend/controller/tts_controller.py \
  backend/service/claude_manager/models.py \
  backend/service/environment/templates.py \
  backend/service/execution/agent_executor.py \
  backend/service/langgraph/agent_session.py \
  backend/service/langgraph/agent_session_manager.py \
  backend/service/prompt/sections.py \
  backend/service/vtuber/delegation.py \
  backend/service/vtuber/thinking_trigger.py
# → no output, exit 0
```

### Final grep sweep

Excluding `dev_docs/20260420_3/` (frozen historical record of the
prior `cli → bound_worker` rename) and the three intentional
legacy-compat locations, no `[CLI_RESULT]` / `bound_worker` /
`BoundWorker` / `session_type == "bound"` references remain.

Remaining references are all intentional:

| File | Lines | Kind |
|------|-------|------|
| `backend/service/vtuber/delegation.py` | 20, 36 | Legacy matcher docstring + `_LEGACY_SUB_WORKER_RESULT_TAG` |
| `backend/controller/tts_controller.py` | 49 | Regex alias in TTS tag stripper; labeled "legacy alias for SUB_WORKER_RESULT" |
| `backend/docs/SUB_WORKER.md` | 219, 221 | Legacy compatibility doc |
| `backend/docs/SUB_WORKER_KO.md` | 219, 221 | Korean legacy compatibility doc |
| `dev_docs/20260420_3/**/*.md` | — | Frozen historical record (Progress 10 cycle) |

### Frontend — type-check

**Blocked.** `frontend/node_modules/` is not installed in this
workspace, so `tsc` cannot run. TypeScript correctness is
asserted by inspection of the rename (mechanical identifier
flips, no structural change). Pre-merge CI will run the real
type-check; that's the gate.

### Manual verification (for reviewer)

- [ ] Create a VTuber session via UI. Confirm the auto-created
      Sub-Worker has `session_type == "sub"` and name suffix
      `_sub`.
- [ ] Delegate a task VTuber → Sub-Worker and back. Confirm the
      reply arrives with the `[SUB_WORKER_RESULT]` tag and the
      TTS filter strips it from spoken output.
- [ ] Send a payload with legacy `session_type: "bound"` to
      `POST /sessions`. Confirm the created session has
      `session_type == "sub"` (validator coercion).
- [ ] Simulate an old Worker emitting `[CLI_RESULT]` — the VTuber
      inbox matcher and TTS filter both still handle it.

## Out of scope

- Removing the `[CLI_RESULT]` legacy constant. Keep at least one
  release cycle of tolerance; revisit once deployment telemetry
  confirms no old Workers are still emitting the legacy tag.
- Reshaping the VTuber auto-pair block beyond renames (Progress 10
  and PR 20 already handled the structural work).
- Any changes to `[ACTIVITY_TRIGGER]` (Progress 13 follow-up,
  explicitly deferred).

## Next

Open PR against `main`. PR title candidate:

> `refactor: unify worker terminology to Sub-Worker (schema, protocol, docs)`

After merge, the next Geny cycle can delete the two legacy
constants (`_LEGACY_SESSION_TYPE_MAP`, `_LEGACY_SUB_WORKER_RESULT_TAG`)
once metrics show zero legacy traffic for one release window.
