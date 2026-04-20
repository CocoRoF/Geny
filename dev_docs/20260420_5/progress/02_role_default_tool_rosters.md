# Progress/02 — Role-default tool rosters

**PR.** `fix/role-default-tool-rosters` (cycle 20260420_5, PR #2)
**Depends on.** PR #1 (`fix/manifest-tool-roster`)
**Date.** 2026-04-20

---

## Symptom

After PR #1, the **worker** env received the full builtin +
custom roster. But `create_vtuber_env` was still hardcoded to
`["web_search", "news_search", "web_fetch"]` — so the VTuber
couldn't DM its Sub-Worker, couldn't read its inbox, and had no
memory or knowledge access.

Matches the user's LOG2 where both the VTuber and Sub-Worker
independently reported *"I only have web_search, news_search,
and web_fetch"* — the VTuber was honestly reporting its three-
tool roster, and the Sub-Worker was inheriting the same narrow
vision via the same pre-PR-#1 `get_custom_names()` plumbing.

## Fix

### `backend/service/environment/templates.py`

Added two module-level constants and one helper:

```python
_VTUBER_CUSTOM_TOOL_WHITELIST = frozenset(
    {"web_search", "news_search", "web_fetch"}
)
_PLATFORM_TOOL_PREFIXES = ("geny_", "memory_", "knowledge_", "opsidian_")

def _vtuber_tool_roster(all_tool_names: List[str]) -> List[str]:
    return [
        name
        for name in all_tool_names
        if name.startswith(_PLATFORM_TOOL_PREFIXES)
        or name in _VTUBER_CUSTOM_TOOL_WHITELIST
    ]
```

**Prefix-based platform detection.** A hardcoded allowlist of
platform tool names would drift the moment someone adds a new
builtin under `backend/tools/built_in/*.py`. Prefix matching on
`geny_` / `memory_` / `knowledge_` / `opsidian_` is stable: new
tools under those namespaces are auto-included.

**Whitelist for custom tools.** The custom-tool layer is where
the VTuber explicitly differs from the worker — `browser_*` is
too heavy for the conversational persona. A hardcoded
whitelist here is the right shape because the inclusion
decision is *persona-specific*, not pattern-driven.

### Signature change

`create_vtuber_env` now takes `all_tool_names: Optional[List[str]]
= None`. When omitted, it falls back to the legacy
`["web_search", "news_search", "web_fetch"]` roster so older
callers and tests don't break.

`install_environment_templates` pipes its `external_tool_names`
kwarg through to `create_vtuber_env(all_tool_names=...)` —
previously it ignored the kwarg for the VTuber case.

### Why this couldn't be in PR #1

PR #1 was about the executor-side contract: "what's in
`.external` is what gets registered". Collapsing that truth onto
the worker env was a one-argument change. The VTuber env needed
a *new* filtering function because it has a different
persona-level policy — that's additive code that deserves its
own review surface.

## Tests

Five new cases in
`backend/tests/service/environment/test_templates.py`:

- `test_vtuber_env_includes_platform_tools` — locks in platform
  access.
- `test_vtuber_env_excludes_browser_tools` — prevents accidental
  re-admission of `browser_*`.
- `test_vtuber_env_keeps_conversational_web_tools` — prevents
  the whitelist from being narrowed by mistake.
- `test_vtuber_env_legacy_call_site_still_works` — backward
  compat for callers that don't pass `all_tool_names`.
- `test_install_templates_propagates_to_vtuber` — boot-path
  integration: `install_environment_templates(all_names)` puts
  platform tools *and* filtered custom tools on the VTuber seed.

Inline verification confirmed the filter logic and module
structure (pytest unavailable in sandbox).

## Verification

1. AST check: `_vtuber_tool_roster` defined, uses prefix tuple
   and whitelist frozenset.
2. Signature check: `create_vtuber_env` accepts `all_tool_names`.
3. Pipeline check: `install_environment_templates(all_names)`
   flows `all_names` into `create_vtuber_env(all_tool_names=...)`.
4. Simulated filter against a representative roster:
   `browser_*` filtered, `geny_*` / `memory_*` / `knowledge_*` /
   `opsidian_*` kept, three web tools kept.

## What this unlocks

After PR #1 + PR #2 ship together, a VTuber session built
through `install_environment_templates(all_names)` sees:

| Category | Worker | VTuber |
| --- | --- | --- |
| `geny_*` (session mgmt, DM, rooms, inbox) | ✓ | ✓ |
| `memory_*` | ✓ | ✓ |
| `knowledge_*` / `opsidian_*` | ✓ | ✓ |
| `web_search` / `news_search` / `web_fetch` | ✓ | ✓ |
| `browser_*` | ✓ | ✗ |

The VTuber → Sub-Worker DM flow becomes reachable end to end,
and LOG2's "I only have web tools" regression no longer matches
what `state.tools` actually publishes.

## Rollback

Revert. VTuber goes back to three web tools only. Worker
unchanged (its roster is PR #1's responsibility).

## What's still broken (explicitly out of scope)

- The `.process` AttributeError on file endpoints — PR #3.
- End-to-end regression harness — PR #4.
- If PR #1 is reverted after this PR ships, the worker env
  loses platform tools again *and* the VTuber filter still
  works correctly against whatever narrow list it receives.
  The two PRs are composable in either direction of revert.
