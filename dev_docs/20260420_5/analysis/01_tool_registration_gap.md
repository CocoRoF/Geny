# Analysis 01 — Tool-registration gap

## Symptom

1. Frontend shows `Tool Call: geny_send_direct_message …
   ERROR (0ms) — No output`.
2. VTuber's own text output: *"I only have web_search,
   news_search, and web_fetch. I don't have a direct messaging or
   file tool."*
3. Sub-Worker's own text output: the same — even though the
   worker preset is supposed to have *everything*.

## Trace

### Step 1 — seed env creation at boot

`backend/main.py:321-325`

```python
env_templates_installed = install_environment_templates(
    environment_service,
    external_tool_names=tool_loader.get_custom_names(),
)
```

`tool_loader.get_custom_names()` returns **only** the contents of
`backend/tools/custom/` — i.e. `web_search`, `news_search`,
`web_fetch`, `browser_*`. The Geny platform builtins in
`backend/tools/built_in/` (`geny_*`, `memory_*`, `knowledge_*`)
are **never** passed through.

### Step 2 — worker env factory

`backend/service/environment/templates.py:50-74`

```python
def create_worker_env(external_tool_names=None):
    manifest = build_default_manifest(
        preset="worker_adaptive",
        external_tool_names=list(external_tool_names or []),
    )
    ...
```

The worker env therefore receives `external = [web_search,
news_search, web_fetch, browser_*]` — and **nothing else**.

### Step 3 — vtuber env factory

`backend/service/environment/templates.py:77-94`

```python
def create_vtuber_env():
    manifest = build_default_manifest(
        preset="vtuber",
        external_tool_names=["web_search", "news_search", "web_fetch"],
    )
```

Hardcoded to three web tools. Still no platform tools.

### Step 4 — manifest factory

`backend/service/langgraph/default_manifest.py:374-377`

```python
tools = ToolsSnapshot(
    built_in=list(_DEFAULT_BUILT_IN_TOOLS),
    external=list(external_tool_names or []),
)
```

`_DEFAULT_BUILT_IN_TOOLS = ["Read", "Write", "Edit", "Bash",
"Glob", "Grep"]` (`default_manifest.py:30-37`).

**This list is dead metadata.** Nothing on the Geny side supplies
tools with those names, and — critically — the executor never
consumes `manifest.tools.built_in` at all.

### Step 5 — pipeline reads only `.external`

`geny-executor/src/geny_executor/core/pipeline.py:85-122`

```python
def _register_external_tools(manifest, registry, providers):
    external_names = list(getattr(manifest.tools, "external", []) or [])
    ...
    for name in external_names:
        tool = None
        for provider in providers:
            tool = provider.get(name)
            if tool is not None:
                break
        ...
        registry.register(tool)
```

There is **no sibling `_register_builtin_tools`**. The only
registration path is `.external` via the `adhoc_providers` list.
`manifest.tools.built_in` is written to disk, read back on
instantiation, and never touched again.

### Step 6 — consequence

`pipeline.tool_registry` after `from_manifest_async`:

| Env | What reaches the registry |
| --- | --- |
| worker | `web_search`, `news_search`, `web_fetch`, `browser_*` |
| vtuber | `web_search`, `news_search`, `web_fetch` |

Neither session has `geny_send_direct_message`, so the LLM's
structured `tool_use` block is refused by the router with
`unknown_tool`. SystemStage's `state.tools` also excludes it, so
when the LLM is *asked* what tools it has, it honestly reports
"web tools only" — matching LOG2 exactly.

## What's available but not wired

`GenyToolProvider.list_names()` already advertises **both**
builtin and custom tools:

`backend/service/langgraph/geny_tool_provider.py:67-75`

```python
def list_names(self) -> List[str]:
    """Names the underlying loader can supply (built-in + custom)."""
    get_all = getattr(self._loader, "get_all_names", None)
    if get_all is not None:
        return list(get_all())
    ...
```

And `ToolLoader.get_tool(name)` resolves across both dirs:

`backend/service/tool_loader.py:128-130`

```python
def get_tool(self, name: str) -> Optional[Any]:
    """Get a tool by name (built-in or custom)."""
    return self.builtin_tools.get(name) or self.custom_tools.get(name)
```

So the *provider* is ready. The missing piece is the **manifest
declaration**: the seed env factories need to list every builtin
+ custom name in `.external` so the pipeline walks them and asks
the provider for each.

## Why the "built_in" split existed

Historical. Early plans (see
`dev_docs/20260419/plan/02_default_env_per_role.md`) envisioned
two distinct registration paths — executor-side builtins
(filesystem) and Geny-side externals. But the executor never
grew the first half: `geny-executor`'s own
`src/geny_executor/tools/built_in/` (`ReadTool`, `WriteTool`, …)
has no auto-registration hook either. `_DEFAULT_BUILT_IN_TOOLS`
was a promissory note that was never cashed.

Two coherent resolutions:

1. **Collapse into `.external`** — treat every tool the provider
   can supply (Geny builtin + Geny custom) as a single roster in
   `.external`. This works today with a one-line change in
   `default_manifest.build_default_manifest` +
   `install_environment_templates` passing the **union** of
   names.
2. **Honour `.built_in` in the executor** — have
   `Pipeline.from_manifest` also walk `.built_in` through the
   same provider chain. Functionally equivalent, but requires an
   executor release.

Recommendation: **option 1 for this cycle**. It is a pure Geny-
side change, delivers the user-visible fix immediately, and
leaves the executor free to adopt option 2 later as a cleanup
(with `.built_in` acting as "always-on, not preset-filterable"
— a semantic the frontend may want).

## Tests that would have caught this

None exist. `install_environment_templates` is exercised in
parity tests that check manifest *shape* (has-stage-list,
has-tools-snapshot), not *roster contents*. Parallel to the
v0.26.2 regression test on ToolStage registry identity, this
cycle should add:

```python
def test_worker_env_roster_includes_platform_tools():
    manifest = create_worker_env(
        external_tool_names=[<all loader names>]
    )
    assert "geny_send_direct_message" in manifest.tools.external
    assert "memory_write" in manifest.tools.external

def test_vtuber_env_roster_includes_dm_and_memory():
    manifest = create_vtuber_env()
    assert "geny_send_direct_message" in manifest.tools.external
    assert "memory_read" in manifest.tools.external
```

Under PR #1's resolution, the second test will need
`create_vtuber_env(all_names=...)` to take the full loader
(matching the worker factory's signature) — see plan/02 for the
exact signature shift.
