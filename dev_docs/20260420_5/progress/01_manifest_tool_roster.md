# Progress/01 — Manifest tool roster fix

**PR.** `fix/manifest-tool-roster` (cycle 20260420_5, PR #1)
**Date.** 2026-04-20

---

## Symptom

Even after 20260420_4's registry-wiring fixes (v0.26.1 +
v0.26.2), VTuber and Worker sessions reported *"I only have web
tools"* when asked about their tool inventory, and
`geny_send_direct_message` still returned `ERROR (0ms)` with no
execution trail.

v0.26.2's router-identity check confirmed the router was
correctly looking at the shared registry — but the shared
registry never contained `geny_send_direct_message` in the first
place. The bug was upstream of routing: it was in what the
manifest declared.

## Root cause

`Pipeline.from_manifest` populates `tool_registry` via a single
function — `_register_external_tools` at
`geny-executor/src/geny_executor/core/pipeline.py:85-122`:

```python
external_names = list(getattr(manifest.tools, "external", []) or [])
...
for name in external_names:
    tool = None
    for provider in providers:
        tool = provider.get(name)
        ...
    registry.register(tool)
```

There is no sibling walk over `manifest.tools.built_in`. It is
declarative metadata that nothing reads.

Meanwhile Geny's `backend/main.py:321-325` seeded the worker env
with only `tool_loader.get_custom_names()` — which returns
`tools/custom/*` names (`web_search`, `news_search`, `web_fetch`,
`browser_*`) but *not* the `tools/built_in/*` platform tools
(`geny_*`, `memory_*`, `knowledge_*`).

And `default_manifest._DEFAULT_BUILT_IN_TOOLS = ["Read", "Write",
"Edit", "Bash", "Glob", "Grep"]` was populated into
`manifest.tools.built_in` — a promissory note that was never
cashed because the executor never walks `.built_in`.

Net effect: platform tools (including DM, inbox, memory, and
knowledge) never reached `pipeline.tool_registry` on any session.

## Fix

Three file changes, all Geny-side:

### `backend/main.py`

```diff
-    external_tool_names=tool_loader.get_custom_names(),
+    external_tool_names=tool_loader.get_all_names(),
```

Now the boot-time seed for the worker env includes builtin +
custom names.

### `backend/service/langgraph/default_manifest.py`

- Deleted `_DEFAULT_BUILT_IN_TOOLS` constant (dead metadata).
- `build_default_manifest` now emits
  `ToolsSnapshot(built_in=[], external=<caller-supplied>)` with a
  comment explaining why `.built_in` stays empty until/unless
  the executor grows a second registration path.

### `backend/service/environment/templates.py`

Docstrings only — updated to reflect the new invariant
("pass the full union of builtin + custom names to
*external_tool_names*"). Behaviour already matches; the factory
is a pass-through.

## Tests

Three new cases in
`backend/tests/service/langgraph/test_default_manifest.py`:

- `test_manifest_built_in_is_empty` — locks in the empty
  `.built_in` invariant across all three presets.
- `test_manifest_external_is_caller_supplied` — verifies the
  pass-through contract.

Three new cases in the new module
`backend/tests/service/environment/test_templates.py`:

- `test_worker_env_includes_platform_tools_when_given_all_names`
- `test_worker_env_external_mirrors_caller_input`
- `test_install_environment_templates_passes_all_names` — walks
  the boot path end-to-end against a real `EnvironmentService`
  with a tmp storage dir.

Sandbox note: pytest is not installed in this environment, so
verification used inline AST + import checks. The test code has
been hand-reviewed against the existing style; actual pytest
execution will happen in CI / reviewer environment.

## Verification

1. `ast` walk confirms `_DEFAULT_BUILT_IN_TOOLS` is gone from
   `default_manifest.py` (no assignment, no reference).
2. `built_in=[]` appears in the `ToolsSnapshot` construction.
3. `tool_loader.get_all_names()` is the only argument to
   `install_environment_templates(external_tool_names=...)` in
   `main.py`.

## What's still broken (explicitly out of scope)

- **VTuber env roster** still hardcoded to
  `["web_search", "news_search", "web_fetch"]` in
  `create_vtuber_env`. After this PR, the VTuber can technically
  reach `GenyToolProvider`, but the manifest tells the pipeline
  to register only those three names. PR #2 of this cycle
  broadens the VTuber roster to include platform tools while
  still excluding browser automation.
- **`.process` AttributeError** on file endpoints — PR #3 handles.
- **End-to-end harness** — PR #4.

## Rollback

Revert this PR. The boot-time call reverts to
`get_custom_names()`; `_DEFAULT_BUILT_IN_TOOLS` is reintroduced
in dead form. The worker env regresses to custom-tools-only
(the pre-PR broken state). VTuber unaffected by either
direction.
