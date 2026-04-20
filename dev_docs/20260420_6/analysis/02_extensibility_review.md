# Analysis/02 — Tool interface extensibility review

The user's directive: *"geny_executor should provide a strong,
extensible tool interface; external services like Geny should be able
to define their own tools (LangChain-style / geny-style / MCP) and
register them properly."* The probe bug from analysis/01 is a single
symptom; this doc steps back and audits the end-to-end tool-plug-in
story to flag what's actually robust and what is duct-tape.

## The layers

```
┌──────────────────────────────────────────────────────┐
│  LLM turn                                           │
│    ↓                                                │
│  s03_system (SystemStage) — builds state.tools from │
│                              tool_registry.to_api_format() │
│    ↓                                                │
│  s06_api — sends tools to Anthropic                 │
│    ↓                                                │
│  s09_parse — extracts pending_tool_calls            │
│    ↓                                                │
│  s10_tool (ToolStage) — router: registry.get(name). │
│                         execute(input, ctx)         │
└──────────────────────────────────────────────────────┘
                         │
             ┌───────────┴───────────┐
             ↓                       ↓
    pipeline.tool_registry   (holds executor-shaped Tool objects)
             ↓                          ↑
     _register_external_tools       AdhocToolProvider.get(name)
       (walks manifest.tools.external, asks providers for each name)
                                        ↑
                          ┌─────────────┼──────────────┐
                          ↓             ↓              ↓
                 GenyToolProvider  MCPManager     (future: LangChain,
                   wraps a          connects         HTTP, etc.)
                   ToolLoader       MCP servers
                          ↓
                _GenyToolAdapter (this cycle's patient)
                          ↓
                    Geny BaseTool / ToolWrapper
                    (run(**kwargs) / arun(**kwargs))
```

## What's solid

1. **Tool protocol**: `geny_executor.tools.base.Tool` is a clean ABC
   — 4 properties (`name`, `description`, `input_schema`, plus
   `to_api_format`) + `async execute(input, context)`. Every adapter
   targets this.
2. **Context passing**: `ToolContext` is a proper dataclass —
   `session_id`, `working_dir`, `storage_path`, `env_vars`,
   `allowed_paths`, `metadata`. Rich enough for anything a tool needs
   from its caller.
3. **Registration path**: `manifest.tools.external` + `AdhocToolProvider`
   (20260420_5 nailed this down). Adding a new tool ecosystem means
   implementing a Provider with two methods (`list_names`, `get`).
4. **MCP**: handled end-to-end by `mcp_manager` inside geny-executor;
   tools get wrapped into `Tool`-shape automatically. Geny doesn't
   need to know.

## What's fragile

### A) The adapter probes a signature that doesn't match the callsite

Covered in `analysis/01`. The probe reads `arun`'s signature, but the
adapter's kwargs actually flow through to `run` via the inherited
forwarder. Fixing this is the scope of this cycle.

### B) Context is smuggled through kwargs, not `ToolContext`

`_GenyToolAdapter.execute` does:

```python
input.setdefault("session_id", context.session_id)
await self._tool.arun(**input)
```

This means the tool's `run` signature has to declare `session_id` as
a real parameter to receive context. For Geny's platform tools that's
the current convention (`memory_read(session_id, filename)`,
`knowledge_read(session_id, filename)`), but it conflates:

1. **Input from the LLM** (schema-visible, described to Claude).
2. **Context from the runtime** (hidden, injected by the adapter).

Claude sees `session_id` in the tool's input_schema — because
`BaseTool._generate_parameters_schema` inspects the same `run`
signature — and may try to fill it in from conversation state
("the user's session_id is abc123"). Sometimes it guesses wrong.

**Ideal**: context flows via a side channel. `run(input, *, ctx=None)`
or `run(**kwargs, _context=None)` — and the schema generator skips
context params. Every Geny platform tool then gains a consistent,
typed way to reach `session_id` without polluting the LLM's schema.

**Pragmatic**: out of scope for this cycle — requires touching every
Geny platform tool. But it's the right next step if this class of bug
keeps surfacing. Noted here so the next time someone asks "should we
accept `session_id` as a param?", we can point at this doc.

### C) `ToolWrapper` (decorator-style) isn't probed

`ToolWrapper.run(**kwargs)` forwards to `self.func(**kwargs)`. The
probe reads `ToolWrapper.run` and sees `**kwargs` → True. Injection
then happens via `run → func`; `func` may or may not accept
`session_id`. Today no `@tool`-decorated function in the tree declares
`session_id`, so this is latent, not live. Same class of bug as (A).
Fix: probe `tool.func` when present.

### D) No LangChain adapter today

User mentions LangChain as an example of "external ecosystems".
There's no LangChain adapter in the tree today. Adding one is a
single file (`LangChainToolProvider` implementing `AdhocToolProvider`,
wrapping each `langchain.tools.BaseTool` into a geny-executor Tool).
Out of scope; noted to confirm the architecture would support it
cleanly — it would.

### E) Tool schemas are generated from `run` signature

`BaseTool._generate_parameters_schema` walks `run.__signature__` to
produce the JSON Schema shown to Claude. This is terse and works for
positional string/int params, but:

- Optional / Union / List[X] → "string" fallback.
- Nested dicts → "object" with no sub-properties.
- No docstring → generic "Parameter: x" description.

Tools that want fidelity can override `parameters = {...}` explicitly.
Everything else gets the inferred schema. Acceptable for now; if
LLMs start hallucinating param shapes on our custom tools, revisit.

## What this cycle delivers

Narrow: fix (A) + (C). The probe learns to inspect the concrete
callable, not the inherited forwarder. Regression tests prove the fix
handles both `BaseTool` subclasses and `ToolWrapper`, with and
without session_id in the signature.

Broad: this doc + `01` record where the next incremental investments
should go — context-as-side-channel (B), LangChain adapter (D) if and
when a consumer needs it.
