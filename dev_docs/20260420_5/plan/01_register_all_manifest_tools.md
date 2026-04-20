# Plan 01 — PR #1: Register all manifest tools

**Branch.** `fix/manifest-tool-roster`

## Goal

Every tool the `GenyToolProvider` can supply — both
`tools/built_in/*` (platform tools: `geny_*`, `memory_*`,
`knowledge_*`) and `tools/custom/*` (web + browser) — reaches
`pipeline.tool_registry` after `from_manifest_async`.

## Change surface

### `backend/service/langgraph/default_manifest.py`

Delete the dead `_DEFAULT_BUILT_IN_TOOLS` constant (the executor
doesn't read `.built_in`, so seeding it is a lie).

Change `build_default_manifest` to emit `ToolsSnapshot(built_in=[],
external=<caller-supplied>)`:

```python
tools = ToolsSnapshot(
    built_in=[],
    external=list(external_tool_names or []),
)
```

Rationale: `.external` is the *sole* registration path. Keeping
`.built_in` empty makes the manifest file honest about that —
future readers won't be misled into thinking `["Read", "Write",
…]` is active. If/when the executor grows option-2 behaviour
(analysis/01), we revisit.

### `backend/main.py:321-325`

Change the `install_environment_templates` call to pass the
**union** of builtin + custom names:

```python
env_templates_installed = install_environment_templates(
    environment_service,
    external_tool_names=tool_loader.get_all_names(),
)
```

`get_all_names` already exists
(`backend/service/tool_loader.py:144-146`) and returns
`builtin_tools.keys() + custom_tools.keys()`. This single line
turns the worker env from "custom-only" into "platform +
custom".

### `backend/service/environment/templates.py`

- `create_worker_env` stays as-is (already takes
  `external_tool_names`). Its doc-comment updates from "custom-
  tool registry" to "all provider-backed tools".
- `create_vtuber_env` — signature gains an
  `all_tool_names: Optional[List[str]] = None` kwarg so the
  VTuber can take a narrower whitelist. PR #2 populates this.
  For PR #1, leave the hardcoded `["web_search", "news_search",
  "web_fetch"]` in place — the VTuber still has the pre-PR
  behaviour. Only the worker's roster changes in this PR.

### Test — `backend/tests/service/environment/test_templates.py`

New:

```python
def test_worker_env_external_includes_platform_tools():
    loader = get_tool_loader()
    manifest = create_worker_env(
        external_tool_names=loader.get_all_names()
    )
    assert "geny_send_direct_message" in manifest.tools.external
    assert "geny_read_inbox" in manifest.tools.external
    assert "memory_read" in manifest.tools.external
    assert "knowledge_search" in manifest.tools.external
    assert "web_search" in manifest.tools.external
```

If a test module at that path doesn't exist, create one. Use
the existing test_templates pattern (ToolLoader fixture via
`get_tool_loader()`).

## Why the builtin/custom split collapses

Before this PR the split was enforced at three layers — loader,
manifest, preset. After this PR:

- **Loader.** Still splits for *discovery*
  (`builtin_tools` / `custom_tools` dicts). Unchanged.
- **Manifest.** Flat `external` list. What's registered is
  what's listed. Honest.
- **Preset.** `tool_preset.custom_tools` still filters custom
  tools for the worker's UI picker — unchanged. PR #1 doesn't
  touch presets.

Effectively: "builtin" now means "we never ask the preset to
gate it". That's already how the old `_register_tools_as_mcp`
path behaved. We're just propagating the invariant into the
manifest layer.

## Non-goals in this PR

- VTuber's roster (stays 3 web tools in this PR; PR #2
  broadens).
- Removing `built_in` from `ToolsSnapshot` upstream — that's an
  executor-side change. Here we just stop populating it.
- Frontend "all tools" indicator — currently infers from preset;
  unchanged.

## Verification before merge

1. `pytest backend/tests/service/environment/test_templates.py`
   passes.
2. Manual: spin up backend, check logs at boot for "Environment
   templates installed: 2" + log line showing the worker roster
   now contains `geny_send_direct_message` etc.
3. Spin up a worker session via the UI, send a prompt that lists
   tools, confirm the LLM reports platform tools.

## Rollback

Revert the PR. Worker sessions lose platform tools again (back
to today's broken state). VTuber unaffected (its roster was
identical before and after this PR).
