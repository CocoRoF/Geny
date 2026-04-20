# Progress 12 — `prompts/vtuber.md` delegation rewrite

| Field | Value |
|-------|-------|
| Plan ref | `plan/03_vtuber_worker_binding.md` → **PR C** |
| Master ref | `plan/00_overview.md` → **Phase 3 / PR 22** |
| Geny PR | [#164](https://github.com/CocoRoF/Geny/pull/164) |
| Geny merge commit | `0b6f09e` on `main` |
| Status | **Merged** |

---

## Why this PR exists

The LLM's view of the world is whatever text we feed it at the
system-prompt layer. After PR 20 the auto-injected block said
"Bound Worker Agent" but the persona base prompt (`vtuber.md`)
still told the model about "paired CLI agent" — two inconsistent
phrasings describing the same concept. A VTuber reading both at
once would be unsure whether it had a CLI agent, a bound Worker,
or both.

This PR re-aligns the persona base prompt with the auto-injected
block, plus fixes the `prompts/README.md` / `README_KO.md`
section that documented the (now stale) injection text.

## What changed

### `backend/prompts/vtuber.md`

Prose replacements (keeping the voice and Korean-first persona):

| Location | Before | After |
|----------|--------|-------|
| §Task Delegation opening | *(no preamble)* | One paragraph stating the binding is first-class (one Worker per VTuber, injected as a "Bound Worker Agent" block). |
| §Task Delegation bullet 2 | "to your paired CLI agent via `geny_send_direct_message`" | "to your bound Worker via `geny_send_direct_message` with `target_session_id` set to the bound Worker's session_id" |
| §Task Handling → subsection header | "### Delegate to CLI Agent (send via DM)" | "### Delegate to Bound Worker (send via DM)" |
| §Task Handling step 2 | "Send the task to your paired CLI agent via `geny_send_direct_message`" | "Call `geny_send_direct_message` with `target_session_id` set to the bound Worker's session_id" |
| §Task Handling step 4 | "When CLI agent responds back, summarize the results conversationally" | "When the Worker's reply arrives (tagged `[CLI_RESULT]`), summarize conversationally — do not forward its verbose output verbatim; your job is to be the persona layer" |
| §Triggers → `[ACTIVITY_TRIGGER]` | "Delegate the activity to your CLI agent" | "Delegate the activity to your bound Worker" |
| §Triggers → `[CLI_RESULT]` | "Summarize the CLI agent's work result conversationally" | "A task your bound Worker was running has finished. Summarize the result conversationally… (Tag name is a legacy protocol marker and will not change in user-visible prose.)" |

### `backend/prompts/README.md` + `README_KO.md`

The "VTuber ↔ CLI Session Linking" section is the developer-facing
documentation of the exact text injected into VTuber / Worker
system prompts. PR 20 changed the injected text; this PR brings
the documentation in sync. Both language variants updated
symmetrically.

## Why `[CLI_RESULT]` and `[ACTIVITY_TRIGGER]` stay

These are protocol marker tags matched at runtime by:

- `service/vtuber/delegation.py` — `DelegationTag.CLI_RESULT = "[CLI_RESULT]"`, `DelegationTag.ACTIVITY_TRIGGER = "[ACTIVITY_TRIGGER]"`
- `service/execution/agent_executor.py` — emits `[CLI_RESULT]` messages when the bound Worker finishes a task
- `service/vtuber/thinking_trigger.py` — emits `[ACTIVITY_TRIGGER]` prompts
- `controller/tts_controller.py` — regex filter strips both tags before TTS

Renaming `[CLI_RESULT]` → `[WORKER_RESULT]` would touch at minimum
those four Python modules plus the prompt files, and requires a
carefully sequenced change (if the emitter renames first, live
VTubers stop recognizing task completion; if the matcher renames
first, live emitters stop working). That's a separate PR with its
own progress doc. For PR 22, the tag literal stays; the prose
references *around* the tag are updated. Added a parenthetical
in the Triggers section so a reader doesn't confuse the tag with
the CLI naming we just retired.

## Scope boundary

Plan PR C text says: *"rewrite the delegation paragraph. Exact
text lands in the PR; this plan doesn't fix the wording."* I
interpreted this broadly enough to include:

- The subsection header ("### Delegate to CLI Agent") — reading
  the bullet list below the renamed header would be jarring
  if the header still said "CLI Agent."
- The `[ACTIVITY_TRIGGER]` and `[CLI_RESULT]` trigger descriptions
  in the same file — they reference "your CLI agent" in a way
  that would contradict the delegation paragraph's new wording.
- The two README files in the same directory, because they were
  documenting the exact (now stale) injected text. Docs that
  lie to readers are worse than no docs.

Kept out:

- `prompts/templates/cli-default.md` and `cli-detailed.md` — these
  are *Worker* personas selectable by a VTuber creator (the
  `selectedCliPrompt` state in the old UI). Renaming the templates
  is a UI concern; the files stay as-is until the VTuber-creation
  modal is restructured.
- Python trigger tag literals — see above.

## Smoke test

None written — this is a text-only change in markdown files. The
`grep` for stale prose is the test:

```
$ grep -rn "paired CLI\|Paired CLI\|CLI agent\|CLI Agent\|paired cli" backend/prompts/
all clean
```

## Manual verification

- [ ] Open a fresh VTuber session. Compare the full system prompt
      (via `/session/:id/prompt` or a debug log) against the
      merged `vtuber.md` + the auto-injected "Bound Worker Agent"
      block. Confirm they read as one coherent instruction set
      with no "CLI agent" echo.
- [ ] Send a delegation-worthy user message (e.g. "edit this
      file"). Confirm the VTuber calls `geny_send_direct_message`
      with `target_session_id` set correctly, summarizes the
      Worker's reply when it arrives tagged `[CLI_RESULT]`, and
      stays in persona (doesn't forward verbose tool output
      verbatim).

## Phase 3 status

| # | Title | PR | Status |
|---|-------|----|--------|
| 18 | Rename `cli_*` → `bound_worker_*` | #160 | Done |
| 19 | Progress doc for PR 18 | #161 | Done |
| 20 | Reshape VTuber auto-pair block | #162 | Done |
| 21 | Progress doc for PR 20 | #163 | Done |
| 22 | Rewrite `prompts/vtuber.md` delegation | #164 | **Done** |
| 23 | Progress doc for PR 22 | *this doc* | Done |
| 24 | Document BoundWorker contract | — | Next |
| 25 | Progress doc for PR 24 | — | Pending |

## Next

Master-plan PR 24 — document the BoundWorker contract in
`backend/docs/`. Covers:

- The invariants (1:1 binding, bind at creation, dissolve at
  termination)
- The session lifecycle (creation, termination from either side,
  Worker crash mid-session)
- The recursion guard (`session_type != "bound"` + `not linked_session_id`)
- The env_id resolution path
- Failure modes (Worker unavailable, inbox full, tool call
  timeout)
- What's explicitly out of scope (multi-Worker fan-out, hot-swap,
  cross-VTuber sharing)

After PR 24 + its progress doc (25), the full 25-PR master plan
is complete.
