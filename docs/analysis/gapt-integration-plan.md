# Geny ⇄ GAPT Integration & Sandbox-Ownership Plan

> **HISTORY (2026-09-19).** The `claude_code_cli` paths described below were
> removed in geny-executor 2.68.0, along with `containerize_cli` and the MCP
> bridge. Every session's tools now run in its sandbox through Stage 10,
> whichever provider answers — the split this document works around is gone.

> Status: **design report (Phase 0)** — review before implementation.
> Scope: make `geny-adapted-project-toolkit` (GAPT) a Geny sub-repo; route Geny's
> project/sandbox/working-directory logic through GAPT; decide whether and how the
> sandboxing primitive is absorbed into `geny-executor`.
> All seams below are code-verified (file:line).

---

## 0. TL;DR — the decision

"Sandboxing" is **three different layers** that are currently conflated. The right
home for each is different:

| Layer | What it is | Today | **Should live in** |
|---|---|---|---|
| **L1 — sandbox *execution* primitive** | run a CLI/process inside an isolated container against a workdir | executor owns the *seam* (`runner_factory`); the concrete `docker exec` runner is **GAPT-side** | **geny-executor** (generalize GAPT's `SandboxedCLIProcessRunner` → a built-in `ContainerCLIRunner` + minimal `SandboxHandle` Protocol) |
| **L2 — sandbox/project *lifecycle* & platform** | DB of projects/workspaces/repos, container create/clone/start/stop/destroy, bare repos, mounts, networking, capacity caps, preview routing, deploy pipeline, secrets vault | **GAPT** (Postgres + docker SDK + Caddy) | **GAPT** (unchanged) — this is a stateful platform, must NOT bloat the executor |
| **L3 — project/sandbox *consumption*** | deciding a session needs a workspace, provisioning it, pointing the agent at it, surfacing files/terminal/preview/deploy to users | **nothing** (Geny has no sandbox) | **Geny** delegates to GAPT via a thin client |

**So:** *Yes, absorb sandboxing into the executor — but only L1 (the execution
primitive).* L2 stays in GAPT; Geny (L3) delegates project/sandbox/deploy to GAPT
and runs its **own** agent runtime pointed at a GAPT-provisioned container. This
preserves Geny's moat (persona/voice/emotion/memory) while making GAPT the
universal sandbox/devops substrate — consistent with the Hermes posture (keep the
moat, absorb universal infra) and the standing rule *extend the executor, don't
build an adapter layer in the app*.

---

## 1. Current state (verified)

### 1.1 Geny — no sandbox, host-fs execution
- Agents run **directly on the host filesystem**. There is **no docker socket
  mount and no container management** anywhere in `Geny/backend` (grep: empty).
- A session's execution context is just three host-side values, threaded into the
  executor at pipeline build:
  - `working_dir = self._working_dir or self.storage_path or ""`
    — [agent_session.py:2032](../../backend/service/executor/agent_session.py)
  - in-memory `WorkspaceStack(initial=Workspace(cwd=…))` (virtual cwd, push/pop
    only) — [agent_session.py:2361](../../backend/service/executor/agent_session.py)
  - `ToolContext(working_dir=…, storage_path=…, extras=…)` injected via
    **`self._pipeline.attach_runtime(**attach_kwargs)`** — the **primary seam**,
    [agent_session.py:2564](../../backend/service/executor/agent_session.py)
- `claude_code_cli` tool calls flow LLM → MCP bridge subprocess → HTTP back to
  Geny `/api/internal/mcp/{sid}/rpc` → host-side tool dispatch
  ([mcp_bridge_controller.py:171-275](../../backend/controller/mcp_bridge_controller.py)).
  **No isolation** — file/bash/git run on the host as the backend user.
- Session storage (memory vault, transcripts) lives on host under
  `storage_path` (volume `geny-agent-sessions-prod`).
- Executor pin: `geny-executor>=2.20.0,<3.0.0`
  ([requirements.txt:40](../../backend/requirements.txt)).

### 1.2 GAPT — a complete sandbox/devops platform
- FastAPI control plane (`server/src/gapt_server/app.py`), Postgres-backed.
- **Workspace/Sandbox model** (`db/models.py`): `Workspace` (`gapt-ws-<wid>`),
  `Sandbox` (`gapt-<ULID>`), `WorkspaceRepository` (multi-repo), `Environment`,
  `DeployRun`.
- **Container lifecycle** (`domains/workspace_sandbox/manager.py:313-687`):
  one container per workspace — `docker run -d --init -u <uid> --network gapt-net
  -v <worktree>:/workspace -v <bare>:<bare>:rw gapt-workspace:latest`. Methods:
  `ensure/exec/spawn_pty/spawn_background/kill_inside/stop`. Security mount
  blocklist in `domains/sandbox/backend.py`.
- **Agent surface**: REST under `/_gapt/api/**` (projects, workspaces, files,
  git, terminal/WS, services, deploy, preview, sessions, oneshot, cost) **+**
  41-tool MCP package (`gapt-mcp`, stdio, cookie auth). Single-admin auth
  (`GAPT_ADMIN_ID/PASSWORD`, session cookie; `GAPT_AUTH_ENABLED`).
- **It already runs agents via geny-executor**:
  `from geny_executor import EnvironmentManifest, Pipeline`
  (`agent/environment_service.py`), and sandboxes the CLI via the runner seam
  (next section). Executor pin: `geny-executor>=2.2.0,<3.0.0`.
- Boot needs: docker.sock, `gapt-net`, Postgres, (Redis/SeaweedFS optional),
  Caddy for preview. Ports follow the `3xxxx` convention.

### 1.3 The executor seam GAPT already uses (the linchpin)
- `ClaudeCodeCLIClient(runner_factory=…)` — kwarg receiving
  `binary= / cwd= / env_extras= / timeout_s=`, used by `_make_runner()`
  ([claude_code.py:165, 254-273](../../../geny-executor/src/geny_executor/llm_client/claude_code.py)).
  Its docstring: *"The supported seam for hosts that wrap process spawning
  (GAPT's docker sandbox) — absorbs the `CLIProcessRunner._spawn` monkey-patch
  that pinned GAPT to 2.1.0."*
- GAPT's concrete runner is **still GAPT-side**:
  `SandboxedCLIProcessRunner(CLIProcessRunner)` rewrites argv to
  `docker exec -i -w /workspace --env … <gapt-ws-X> claude <argv>`
  ([agent/sandbox_runner.py:54-107](../../../geny-adapted-project-toolkit/server/src/gapt_server/agent/sandbox_runner.py)),
  wired via `build_sandboxed_cli_client()` + `attach_session_runtime()`.
- **Important limitation:** this isolates **only the `claude_code_cli` path** (the
  CLI runs its *own* built-in tools inside the container). SDK-provider sessions
  (anthropic/openai/…) still dispatch tools host-side — they are **not**
  sandboxed by this mechanism. (See the executor's own note that Stage 10 skips
  host dispatch when the client `is_subprocess`.)
- `ToolContext.working_dir` is fully pluggable and reaches every tool via Stage
  10 — the seam for an eventual L1 *tool* sandbox (SDK path) already exists
  (`tools/base.py:116`, `stages/s10_tool/.../routers.py`).

---

## 2. Target architecture

```
                         ┌──────────────────────────────────────────┐
                         │                 Geny                      │
   user / channels  ───▶ │  persona · voice(TTS) · emotion · memory  │
                         │  pipeline · sub-agents · thinking-trigger │   ← MOAT, stays
                         │                                           │
                         │  GaptWorkspaceProvider (thin Python HTTP) │ ─┐ L3 (new, small)
                         └───────────────┬───────────────────────────┘ │
                                         │ attach executor runner       │
                                         ▼                              │
                         ┌──────────────────────────────────────────┐  │
                         │            geny-executor                  │  │
                         │  Pipeline · stages · llm_client           │  │
                         │  + ContainerCLIRunner(SandboxHandle)  ◀───┼──┘ L1 (absorbed)
                         └───────────────┬───────────────────────────┘
                                         │ docker exec (or exec-over-API)
                                         ▼
                         ┌──────────────────────────────────────────┐
                         │                 GAPT                      │
                         │  projects/workspaces/repos (Postgres)     │  L2 (owner, sub-repo)
                         │  container lifecycle · git · fs · terminal│
                         │  services · preview(Caddy) · deploy       │
                         │  gapt-ws-<wid>  ⟵ the box the agent runs in│
                         └──────────────────────────────────────────┘
```

### 2.1 The integration model (how Geny runs an agent in a GAPT box)

Two candidate models; the recommendation is a **default + an option**.

**Model A — Workspace-as-a-service (RECOMMENDED default).**
Geny keeps its own session/agent runtime. For a session that needs code/sandbox,
Geny asks GAPT to create/get a workspace (`gapt-ws-<wid>`), then attaches the
executor's `ContainerCLIRunner` pointed at that container — exactly what GAPT's
`sandbox_runner` does today, but using the now-built-in executor runner. Geny's
memory/persona/voice/sub-agents all stay. Files/terminal/preview/deploy surfaces
proxy to GAPT.
- ✅ preserves the moat; minimal change to Geny's agent runtime; reuses the proven
  seam; one agent runtime to maintain.
- ⚠️ only the `claude_code_cli` path is truly isolated (acceptable — it is Geny's
  primary backend; SDK-path tool isolation is a later optional L1 add).

**Model B — Full session delegation (OPTIONAL, for pure-code/devops tasks).**
Geny calls GAPT's `POST /_gapt/api/sessions` / `oneshot`; GAPT runs the agent.
- ✅ cleanest boundary, zero docker in Geny.
- ❌ GAPT sessions have **none** of Geny's memory/persona/TTS/sub-agent/channels.
  Unacceptable for companion/VTuber sessions. Keep as an option for headless code
  agents (e.g. "deploy this", "open a PR") and the MCP agent surface.

> **Recommendation:** Model A is the default for all Geny sessions. Expose Model B
> only as an explicit "delegate to GAPT" action / MCP path for headless code work.

### 2.2 The docker boundary (one real decision)

How does `ContainerCLIRunner._spawn` reach the container?

- **(B1) Shared docker socket + shared network (RECOMMENDED).** Geny backend
  mounts `/var/run/docker.sock` and joins `gapt-net`; the runner runs
  `docker exec` directly into `gapt-ws-<wid>` (the proven GAPT path, lowest
  latency). They ship in one compose, so this is co-located, not cross-host.
  - ⚠️ grants Geny backend docker access (already a powerful service in a
    single-admin self-host; acceptable, document it).
- **(B2) Exec-over-GAPT-API.** The runner posts to a GAPT exec/stream endpoint;
  no docker.sock in Geny. Cleaner privilege separation, but needs a streaming
  exec contract and adds HTTP overhead per spawn.

> **Recommendation:** B1 for the bundled deployment; keep B2 in mind for a future
> "Geny and GAPT on different hosts" topology (GAPT's Cloudflare/remote provider
> is the eventual path — see `project_gapt_cloudflare_provider`).

Note the MCP-bridge consequence: when the CLI runs **inside** `gapt-ws-<wid>`, the
`geny_mcp_bridge` stdio child also runs inside the container and must HTTP-reach
**Geny backend** for Geny's tools (memory, etc.). So the container must be on a
network that resolves Geny backend (shared net), and the bridge URL/token must be
injected as container env. (GAPT solves the analogous problem by pointing the
CLI's MCP config at the GAPT server over `gapt-net`.)

---

## 3. Where sandboxing lives — the L1 absorption (executor change)

Generalize GAPT's GAPT-specific runner into an executor built-in:

- **New Protocol** `SandboxHandle` (executor `llm_client` or a new
  `sandbox/` package):
  ```python
  class SandboxHandle(Protocol):
      container: str                       # e.g. "gapt-ws-abc"
      workdir: str = "/workspace"
      async def ensure(self) -> None: ...  # idempotent create/start
  ```
- **New built-in runner** `ContainerCLIRunner(CLIProcessRunner)` — the generalized
  form of GAPT's `SandboxedCLIProcessRunner._spawn` (argv →
  `docker exec -i -w <workdir> --env … <container> claude <argv>`), parameterized
  by a `SandboxHandle` and an injectable exec strategy (docker CLI by default; a
  hook for B2 exec-over-API later). Lives next to `CLIProcessRunner`
  (`_cli_runtime.py`).
- **Convenience** `build_container_cli_client(creds, sandbox)` mirroring GAPT's
  `build_sandboxed_cli_client`, so both GAPT and Geny call one executor function.
- **GAPT then deletes** its `SandboxedCLIProcessRunner`/`build_sandboxed_cli_client`
  and imports the executor's. (`attach_session_runtime` keeps its provider-match
  guard logic; only the runner moves.)
- **Out of scope for L1 (for now):** sandboxing the SDK-provider *tool* path
  (host-side dispatch). The executor reports a clean future home for it
  (`SandboxedRegistryRouter` or a `tool_runner_factory` on `ToolContext`,
  mirroring the CLI `runner_factory`). Defer until a non-CLI sandboxed session is
  actually needed.

This is the **only** executor change. Everything stateful/infrastructural stays in
GAPT. (Explicitly **rejected**: putting Postgres / docker-SDK workspace manager /
Caddy reconciler into the executor — it would violate the executor's layering and
burden every consumer.)

---

## 4. Phased implementation plan

> Each phase is independently shippable and reversible. Phases 1–2 have no
> user-visible behavior change.

### Phase 0 — this report + decisions (now)
Confirm: integration model (A default / B optional), docker boundary (B1), sub-repo
placement (vendor-copy into `Geny/gapt/`).

### Phase 1 — Absorb L1 into geny-executor *(executor release, e.g. 2.21.0)*
1. Add `SandboxHandle` Protocol + `ContainerCLIRunner` + `build_container_cli_client`.
2. Unit tests (argv shaping, ensure() idempotency, env passthrough, teardown).
3. Keep `runner_factory` 100% backward-compatible (it stays; the built-in just
   gives hosts a ready runner instead of writing their own).
4. Publish via the standard `publish.yml` → PyPI workflow.
- *Acceptance:* GAPT can swap to the executor's runner with no behavior change.

### Phase 2 — Vendor GAPT into Geny + bundled boot *(no behavior change)*
1. **Copy** `geny-adapted-project-toolkit/` → `Geny/gapt/` (vendor, not submodule —
   per the user's "Geny에 복사"). Record upstream commit in `Geny/gapt/UPSTREAM`.
2. Pin both to the same executor (GAPT pin → `>=2.21.0`); GAPT switches to the
   built-in runner (delete its copy).
3. **Compose**: add GAPT services to Geny's stack (`gapt-postgres`, optional
   `gapt-redis`, `gapt-server`, `caddy`) + the `gapt-net` network; mount
   docker.sock into `gapt-server` (and, for B1, into `geny-backend`); join
   `geny-backend` to `gapt-net`. Keep GAPT's Postgres **separate** from Geny's
   (GAPT owns its schema/migrations). Follow the `3xxxx` port convention; mind the
   `sudo`/`$HOME` and `--no-deps`/external-net pitfalls already documented.
4. Bring GAPT up alongside Geny; `geny-backend` health-checks `gapt-server` on boot.
- *Acceptance:* GAPT reachable from Geny over the internal network; both healthy.

### Phase 3 — Geny delegates project/sandbox to GAPT *(core integration)*
1. **`GaptClient`** (new, `Geny/backend/service/gapt/client.py`): thin async HTTP
   client for `/_gapt/api/**` (login→cookie; projects, workspaces, files, git,
   terminal, services, preview, deploy, cost). (GAPT has no Python SDK today — this
   is the contract surface.)
2. **`GaptWorkspaceProvider`**: on session create, if the session is sandbox-bound,
   provision/get a GAPT workspace (`POST …/workspaces`, poll to `running`) and
   return a `SandboxHandle` (`container=gapt-ws-<wid>`).
3. **Wire into the session build seam** ([agent_session.py:2564](../../backend/service/executor/agent_session.py)):
   when a `SandboxHandle` is present, attach the executor's `ContainerCLIRunner`
   (Model A) instead of host execution; set the CLI's MCP-bridge URL/token as
   container env so Geny tools still reach Geny backend.
4. Session model gains optional `project_id` / `workspace_id`; non-sandbox sessions
   (pure persona/VTuber chat) keep host execution unchanged (opt-in).
5. (Optional) Model B path: a "delegate to GAPT" action that calls
   `POST …/sessions` / `oneshot`.
- *Acceptance:* a Geny session can edit code, run commands, and commit **inside a
  GAPT workspace container**, with Geny's memory/persona intact.

### Phase 4 — Geny UI: files / terminal / preview / deploy
Proxy Geny frontend surfaces to GAPT (tree/file/terminal-WS/services/preview/deploy)
or embed GAPT's web UI for the devops panels. Reuse existing Geny tab chrome and the
new `SettingsCard` styling for consistency.

### Phase 5 — (optional) SDK-path tool sandboxing (L1 extension)
Only if a non-`claude_code_cli` sandboxed session is needed: add the executor
`tool_runner_factory` / `SandboxedRegistryRouter` so host-side tool dispatch can
also run inside the container.

---

## 5. Risks & open questions

1. **Container runtime / isolation.** GAPT defaults `GAPT_SANDBOX_RUNTIME=sysbox-runc`
   but the M1 workspace containers are **plain Docker** (`WorkspaceSandbox` uses
   `docker run`, `sandbox_id` FK still nullable). The prod host previously **lacked
   sysbox** (it blocked workspaces). → Decide isolation level: plain docker (works
   now, weaker isolation) vs. install sysbox (stronger, ops cost). Plain docker is
   fine for self-host/single-admin to start.
2. **Privilege.** B1 gives `geny-backend` docker.sock. Acceptable for single-admin
   self-host; document it. B2 avoids it at a latency cost.
3. **claude_code auth inside the box.** Geny manages claude creds
   (`geny-claude-creds-prod`); they must be mounted/injected into `gapt-ws`
   containers (GAPT already supports the `/root/.claude` mount).
4. **MCP-bridge reachability** from inside the container (network + injected
   URL/token) — Phase 3 must wire this or Geny's tools go dark for sandboxed CLI.
5. **Two Postgres instances** (Geny's + GAPT's). Keep separate; don't merge schemas.
6. **Auth bridging.** Geny is the front door; GAPT single-admin behind the internal
   network with `GAPT_AUTH_ENABLED=false` for trusted internal calls (sandbox-origin
   bypass) — or a shared service token. Decide in Phase 2.
7. **Memory vs code locality (by design):** Geny memory stays host-side
   (`storage_path`); agent code edits happen in the container `/workspace`. This
   separation is correct, but means "the agent's files" ≠ "the session's memory
   vault" — surface both clearly in the UI.
8. **Vendor drift.** Vendoring (copy) means GAPT improvements must be re-synced.
   Record `UPSTREAM` commit; periodic re-vendor. (Submodule rejected per user's
   "복사" preference.)

---

## 6. Decisions — **LOCKED** (2026-06-22)

- **Integration model:** ✅ **A (default) + B (optional)**. Every Geny session uses
  Model A (Geny keeps its runtime, attaches the executor `ContainerCLIRunner` to a
  GAPT workspace). Model B (full delegation to GAPT `/sessions`) exposed only as an
  explicit headless-code/devops path.
- **Docker boundary:** ✅ **B1 — shared docker socket + `gapt-net`**. `geny-backend`
  mounts `/var/run/docker.sock`, joins `gapt-net`; runner does `docker exec`
  directly. (Documented privilege grant; acceptable for single-admin self-host.)
- **Sub-repo placement:** ✅ **`Geny/gapt/` vendor-copy** with an `UPSTREAM` commit
  marker (not a submodule).
- **Isolation runtime:** ✅ **sysbox** (`sysbox-runc`) for strong workspace
  isolation. **Host prerequisite:** sysbox must be installed on the deploy host
  *before* P2 — the previous GAPT prod host (`:2223`) lacked it and that blocked
  workspaces. P2 gains an explicit "install/verify sysbox-runc + register runtime"
  step; `GAPT_SANDBOX_RUNTIME=sysbox-runc` and `WorkspaceSandbox` must pass
  `--runtime=sysbox-runc` on `docker run` (verify it does; M1 used plain docker).

---

## Progress log

- **2026-06-22 — Phase 3 + Phase 4 DONE, end-to-end VERIFIED.** executor 2.22.0
  `attach_runtime(sandbox=)` ships; Geny `agent_session_manager` provisions a GAPT
  workspace per session (opt-in `GENY_GAPT_WORKSPACES`, default off) and passes
  `sandbox=` at the attach seam; geny-backend on gapt-net + docker.sock + docker
  CLI. GAPT UI/API/previews exposed via Geny nginx (`/_gapt`, `/preview`).
  **Proven on :2222:** geny-backend → `docker exec -w /workspace gapt-ws-<id>` →
  ran as `ubuntu`, wrote a file, `claude 2.1.185` present inside. Fixes en route:
  vendored-lockfile `.gitignore` drop, Secure-cookie-over-http (manual cookie),
  `ensure()` must run a command (not no-op `/start`) to force the container live.
  Test guide + transplant writeup: [`../operations/gapt-test-guide.md`](../operations/gapt-test-guide.md).
  Remaining polish: GAPT `WorkspaceSandbox` should pass `--runtime=sysbox-runc`
  (workspace currently runc); P5 optional SDK-path tool sandbox.



- **2026-06-22 — Phase 0** design + decisions locked (this report).
- **2026-06-22 — Phase 1 DONE** (executor `2.21.1`, on PyPI). Absorbed the L1
  sandbox-execution primitive: `ContainerCLIRunner` + `SandboxHandle` Protocol +
  `build_container_cli_client` in `geny-executor`; `_make_runner` no longer
  requires the agent binary on the host when a `runner_factory` is set; launcher
  check deferred to runtime (2.21.1). 4362 + 9 tests green.
- **2026-06-22 — Phase 2 (in progress).**
  - GAPT switched to the executor's built-in runner (upstream PR #6, merged
    `d15a592`): deleted `SandboxedCLIProcessRunner`; `WorkspaceSandbox` satisfies
    `SandboxHandle`; pin → `geny-executor>=2.21.1`. GAPT tests green.
  - **Vendored** GAPT into [`Geny/gapt/`](../../gapt/) (copy @ `d15a592`,
    [`UPSTREAM.md`](../../gapt/UPSTREAM.md)); README updated.
  - **sysbox on :2222 DONE** — sysbox-ce 0.7.0 installed + `sysbox-runc`
    enabled (zero-downtime via daemon.json jq-add + `systemctl reload docker`;
    uid-map isolation verified). One outage occurred mid-process from a
    stop-docker attempt (2.3G buildkit cold-read wedged dockerd) — recovered;
    see [[feedback_2222_dockerd_restart_hazard]].
  - **GAPT stack LIVE on :2222** — vendored tunnel compose + `deploy/gapt`
    override (no `tunnel` profile → GAPT cloudflared off; behind Geny nginx).
    gapt-server **healthy**, `/health` 200, admin login 204, alembic migrated,
    `gapt-workspace:latest` image built. Brought up **additively, zero
    disruption** (geny-x stayed 200). Fixed: root `.gitignore` had dropped 181
    vendored files incl. lockfiles → re-included (`!/gapt/**`).
  - **geny-backend wired (P3 infra) + VERIFIED** — backend image gained the
    docker CLI; recreated on `gapt-net` + `/var/run/docker.sock` + GAPT env.
    Verified: backend healthy, `docker` 28.5.2 inside, **backend →
    gapt-server/health 200**.
  - **`GaptClient` + `GaptWorkspaceProvider` + `GaptSandboxHandle`** shipped
    (`backend/service/gapt/`, 6 tests).

- **2026-06-22 — Phase 3 (remaining): the session-build wiring.** Route a Geny
  session through a GAPT workspace at the `attach_runtime` seam
  ([agent_session.py:2564](../../backend/service/executor/agent_session.py)).
  `_build_pipeline` is **sync**, so provisioning (async) must run in the
  async create path and pass a `GaptSandboxHandle` in. **Recommended approach:**
  extend the executor's `attach_runtime(sandbox=…)` so it wraps the resolved
  `claude_code_cli` client with `ContainerCLIRunner` internally — reuses Geny's
  existing CredentialBundle resolution instead of replicating cli kwargs
  ([[feedback_extend_executor_not_adapter_layer]]). Gate behind a per-session
  flag (default OFF) so the live host chat path is untouched until verified.
  Then P4 (UI proxy: nginx `/_gapt` + `/preview` → `gapt-caddy`).

## Appendix — verified seam map

| Concern | File:line |
|---|---|
| Geny session build / attach seam | `Geny/backend/service/executor/agent_session.py:2564` (`attach_runtime`), `:2032` (working_dir), `:2361` (WorkspaceStack) |
| Geny tool dispatch (host) | `Geny/backend/controller/mcp_bridge_controller.py:171-275` |
| Geny session create | `Geny/backend/service/executor/agent_session_manager.py:647-1049` (`:939` instantiate_pipeline) |
| Executor runner seam | `geny-executor/.../llm_client/claude_code.py:165, 254-273` |
| Executor base runner | `geny-executor/.../llm_client/_cli_runtime.py:186-356` (`_spawn` 295-309) |
| Executor tool cwd | `geny-executor/.../tools/base.py:116`; Stage 10 `stages/s10_tool/.../routers.py` |
| GAPT sandboxed runner (to absorb) | `gapt/server/.../agent/sandbox_runner.py:54-165` |
| GAPT container lifecycle | `gapt/server/.../domains/workspace_sandbox/manager.py:313-687` |
| GAPT models | `gapt/server/.../db/models.py` (Workspace/Sandbox/Environment/DeployRun) |
| GAPT REST surface | `gapt/server/.../routers/*` (`/_gapt/api/**`) |
| GAPT MCP (41 tools) | `gapt/mcp/src/tools/*` |
