# claude_code_cli ⇄ GAPT tools — the complete fix

> **HISTORY (2026-09-19).** Everything below describes the `claude_code_cli`
> provider, which was removed in geny-executor 2.68.0 along with
> `containerize_cli` and the MCP bridge. The problem it solved no longer
> exists: no backend runs its own tool loop, so every session's tools
> execute in its sandbox through Stage 10, whichever provider answers.
> Kept as the record of why that arrangement was a dead end.


## Diagnosis (code-verified)

Why claude_code_cli sessions can't use GAPT/forge/env tools:

1. **MCP bridge is session-blind.** `controller/mcp_bridge_controller.py`
   `_list_session_tools` (line 148) + `_execute_tool` (line 204) resolve tools from
   the **global** `ToolLoader`, and dispatch with a **bare**
   `ToolContext(session_id=...)` (line 226) — **no `.environment`, no `.sandbox`,
   no `.working_dir`**. So:
   - `env` / `forge_tool` / `save_pack` → `context.environment is None` → error.
   - session-scoped tools (forged, per-env packs, env-enabled) → invisible (global
     loader doesn't have them).
2. **OAuth sessions get no sandbox.** `_skip_for_cli_oauth` skips workspace
   provisioning for rotating OAuth → `forge_tool` has no `ctx.sandbox` anyway.
3. **Coupling.** executor `attach_runtime(sandbox=)` BOTH sets `ctx.sandbox` (good)
   AND wraps the CLI in `ContainerCLIRunner` (runs CLI in-container → needs a
   non-rotating token; and the stdio MCP bridge can't even spawn in-container).

## Decision: decouple + make the bridge session-aware (host CLI, sandboxed backend tools)

claude_code_cli runs on the **host** (OAuth-safe), but its `env`/`forge`/`save_pack`/
`gapt_*` tools execute in the **backend** against the session's GAPT workspace via
`ctx.sandbox` (docker exec). Works for ALL auth modes; no in-container bridge.

### A. executor (2.33.0)
- `attach_runtime(sandbox=, containerize_cli: bool = True)` + `_apply_runtime` +
  `__init__` (`self._containerize_cli`). `_build_client_for` wraps the CLI only when
  `_attached_sandbox and self._containerize_cli`. → attach `ctx.sandbox` for tools
  WITHOUT containerizing the CLI.

### B. Geny backend
1. **mcp_bridge_controller (critical):** resolve tools from the live session's
   pipeline registry (env + forged + pack + global) and dispatch with a full
   `ToolContext(session_id, environment=pipeline.environment, sandbox=session sandbox,
   working_dir=/workspace)`. Fallback to the global loader when no live session.
2. **agent_session_manager:** stop skipping the sandbox for claude_code_cli — always
   provision the workspace; pass `containerize_cli=False` for claude_code_cli so the
   CLI stays on host.
3. **AgentSession:** thread `containerize_cli=False` into `attach_runtime` for the
   claude_code_cli provider.
4. **workspace_id injection:** surface the session's GAPT workspace id to the agent
   (prompt/context) so `gapt_*` tools + the agent target the right workspace.

### C. Verify
anthropic already binds + forge works (proven). Verify the bridge now passes
environment+sandbox (env/forge reachable) and the claude_code_cli path provisions a
workspace with `containerize_cli=False`.

## ✅ DONE + LIVE-VERIFIED — 2026-06-24
- executor 2.33.0 (PyPI): `containerize_cli` flag. Geny pinned >=2.33.0, deployed 2222.
- MCP-bridge e2e: tools/list shows session tools (env); `env→forge_tool` via the
  bridge works (env controller + sandbox wired); forged tool callable via bridge →
  `{"up":"HI"}`. PASS.
- Real claude_code_cli (VTuber) session: `bound to GAPT workspace … (tools
  sandboxed; CLI on host)`. PASS — no OAuth skip, CLI stays host.
- Net: claude_code_cli sessions (incl. VTuber, OAuth) can now use env/forge_tool/
  save_pack/gapt_* + session/pack tools. No setup-token required for GAPT tools.

## ✅ Self-service lifecycle [create→save→list→use] — ALL ENVS — 2026-06-24
Gaps found by review + fixed:
- [list]/[use] had NO agent tools → added built-in `list_tool_packs` + `use_tool_pack`
  (tools/built_in/sandbox_tool_pack_tools.py).
- VTuber envs had ONLY `env` (no gapt_run_command) → can't write code to /workspace.
  Fix: inject lifecycle toolset [gapt_run_command, list_tool_packs, use_tool_pack]
  into tools.external at instantiate-time for EVERY session (no per-env reseed).
- MCP bridge tools/list now UNIONs session registry (env+forged+pack) + global loader
  (base) — CLI sees env + session tools without losing base tools.

LIVE-VERIFIED:
- lifecycle_e2e (tool classes): create→save→list→use → loaded tool runs `{"hi":"Geny"}`. PASS.
- Real VTuber (claude_code_cli) session: `active tools (115): lifecycle=['env',
  'gapt_run_command','list_tool_packs','use_tool_pack']`; `bound to GAPT workspace …
  (tools sandboxed; CLI on host)`. PASS.
- Diagnostic log `active tools (N): lifecycle=[...]` added at session build for
  ongoing real-app verification across all envs.

## ✅ Split-brain ELIMINATED — sandbox boundary moved to the tool layer — 2026-06-24
WHY the limitation existed: claude_code_cli runs its NATIVE fs/shell tools wherever
its process runs → on the host (when not containerized) → host/workspace split-brain.

Fix (no containerization, no setup-token, no in-container networking): for a
claude_code_cli session WITH a GAPT sandbox, disallow the CLI's native fs/shell
tools (Bash/Read/Write/Edit/MultiEdit/NotebookEdit/Glob/Grep/LS) via
--disallowedTools (CredentialBundleBuilder(sandbox_fs_isolation=True)). The agent
then uses the bridged EXECUTOR tools (mcp__geny__Bash/Read/Write/…) which docker-
exec INTO /workspace via ctx.sandbox — identical sandbox model to SDK providers.
CLI stays on host (OAuth-safe) but has ZERO host access. One workspace, no split-brain.

LIVE-VERIFIED: isolation ON disallow=[9 native fs/shell tools]; OFF=[]. Real VTuber
session creates cleanly; active tools include env + gapt_run_command + list/use +
the sandboxed mcp fs/shell tools. The whole environment is now uniformly sandboxed
at the tool-execution layer regardless of provider.
