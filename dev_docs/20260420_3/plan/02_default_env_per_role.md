# Plan 02 — Environment-only session architecture

**Full cutover** to env_id-backed pipelines. No backward
compatibility. After this plan ships:

- Every `AgentSession`, regardless of role or UI entry point, is
  built by `Pipeline.from_manifest_async(manifest, ...)`.
- `_build_pipeline`'s hardcoded `GenyPresets.vtuber` /
  `GenyPresets.worker_adaptive` branches are **deleted** (not
  deprecated — deleted).
- Only two seed environments exist: **WORKER** and **VTUBER**.
  `developer` / `researcher` / `planner` all resolve to WORKER.
- VTuber is a thin conversational persona. Heavy lifting happens
  inside a **bound Worker session** that a VTuber spawns and
  delegates to. That binding becomes a first-class feature; see
  `plan/03_vtuber_worker_binding.md` for the detailed design.

This plan drops the Option 1/2/3 discussion from the prior draft.
The user has picked: **environment-only, no legacy path**. The
remaining design questions are about sequencing — how to get
there without a long broken window — not whether to go.

---

## Target architecture

```
              ┌─────────────────────────────────┐
              │  AgentSessionManager            │
              │  create_agent_session(request)  │
              └─────────────┬───────────────────┘
                            │
                request.env_id OR
                ROLE_DEFAULT_ENV_ID[request.role]
                            │
                            ▼
              ┌─────────────────────────────────┐
              │  EnvironmentService             │
              │  instantiate_pipeline(env_id)   │
              │    → load EnvironmentManifest   │
              │    → from_manifest_async(...)   │
              │    → pipeline.attach_runtime(   │
              │         memory_manager=...,     │
              │         llm_reflect=...,        │
              │         curated_km=...)         │
              └─────────────┬───────────────────┘
                            │
                            ▼
              ┌─────────────────────────────────┐
              │  AgentSession (adopts pipeline) │
              │  — no _build_pipeline path —    │
              └─────────────────────────────────┘

ROLE_DEFAULT_ENV_ID:
  worker     → template-worker-env
  developer  → template-worker-env
  researcher → template-worker-env
  planner    → template-worker-env
  vtuber     → template-vtuber-env
```

VTuber role additionally triggers the VTuber↔Worker binding
routine (Plan/03): a VTuber session auto-spawns a paired session
with role=WORKER and env_id=template-worker-env, stores the
worker's `session_id` in its own `linked_session_id`, and injects
a delegation block into the VTuber's system prompt.

---

## Prerequisites inside the executor

Two dormant pieces of the 20260420_2 cycle need to be activated.
Both were explicitly deferred in PR #140:

### Prerequisite A — Populate manifest stage lists for worker_adaptive / vtuber

`EnvironmentManifest.stages: list[StageManifestEntry]` is the
declarative stage layout that `Pipeline.from_manifest_async`
consumes. Today `build_default_manifest` in
`backend/service/langgraph/default_manifest.py` returns an empty
`stages=[]` list and logs a comment saying "filled in by a later
PR". This plan fills it in.

Reference: `GenyPresets.worker_adaptive` (executor
`src/geny_executor/memory/presets.py:161-238`) pipes through:

```
Input → Context → System → Guard → Cache → Think → API → Token →
Parse → Tool → Evaluate(BinaryClassify) → Loop → Memory → Yield
```

`GenyPresets.vtuber` (`:240-295`):

```
Input → Context → System → Guard → Cache → API → Token → Parse →
Tool → Evaluate → Loop → Memory → Yield
```

The manifest `StageManifestEntry` describes each stage's artifact
name (e.g. `"default"`) and its slot choices (e.g. evaluator
strategy `"binary_classify"` for worker_adaptive, default for
vtuber). Declarative params only — **no runtime objects** (no
`memory_manager`, no callbacks).

### Prerequisite B — `Pipeline.attach_runtime(...)` helper (executor 0.24.0)

The manifest cannot carry runtime objects. After
`from_manifest_async` returns, the host attaches them:

```python
# executor: geny_executor/core/pipeline.py (proposed)

class Pipeline:
    def attach_runtime(
        self,
        *,
        memory_retriever: Optional[MemoryRetriever] = None,
        memory_strategy: Optional[MemoryStrategy] = None,
        memory_persistence: Optional[Persistence] = None,
        llm_reflect: Optional[Callable[..., Awaitable[...]]] = None,
        llm_gate: Optional[Callable[..., Awaitable[bool]]] = None,
        curated_knowledge_manager: Optional[Any] = None,
    ) -> None:
        """Inject runtime objects into stages built from a manifest.

        Idempotent only when called **before** the first run. Calling
        this after a run has started raises RuntimeError; the pipeline
        state may have already captured references to the old values.
        """
        ...
```

Implementation details (executor side):

- Walk `self._stages`. For each known stage type, set the
  corresponding slot or attribute.
- `ContextStage`: assign `self._retriever = memory_retriever`.
- `SystemStage`: no runtime dep (already declarative).
- `MemoryStage`: assign `self._strategy = memory_strategy`,
  `self._persistence = memory_persistence`.
- Wire `llm_reflect` / `llm_gate` / `curated_knowledge_manager`
  into the relevant `GenyMemoryStrategy` / `GenyMemoryRetriever`
  that the host constructs and passes.

The cleanest division of labor: the host **constructs** the
`GenyMemoryRetriever` / `GenyMemoryStrategy` / `GenyPersistence`
instances (those are Geny-specific — they live in
`geny_executor/memory/*` but are parameterized by Geny's
`SessionMemoryManager`), then hands the already-built objects to
`attach_runtime`. The executor's helper just plugs them in.

### Release

- Executor `v0.24.0`: adds `Pipeline.attach_runtime`, populates
  manifest stage support for worker_adaptive / vtuber (the
  executor-side part — the stage templates themselves; Geny
  translates those into `StageManifestEntry` via
  `build_default_manifest`). Minor version bump — additive.

---

## Geny-side steps

### Step 1 — Fill `build_default_manifest.stages` for both presets

`backend/service/langgraph/default_manifest.py` today returns a
manifest with `stages=[]`. This step fills both preset branches
with `StageManifestEntry` objects that mirror
`GenyPresets.worker_adaptive` / `GenyPresets.vtuber`.

Acceptance test: `from_manifest_async` on the resulting manifest
yields a pipeline whose `stage_names` list matches the old
preset's list exactly.

### Step 2 — Seed WORKER and VTUBER environments on first boot

New module: `backend/service/environment/templates.py`. Mirror the
`install_templates` pattern in
`backend/service/tool_preset/templates.py`:

```python
def create_worker_env() -> EnvironmentManifest:
    """Default worker environment.

    Binds to every tool in template-all-tools. Uses worker_adaptive
    stage chain. Model is left unpinned — sessions override per
    request.
    """
    return build_default_manifest(
        preset="worker_adaptive",
        external_tool_names=[...],  # union from template-all-tools
    ).with_metadata(
        id="template-worker-env",
        name="Worker Environment",
        description="Default environment for autonomous worker roles.",
    )


def create_vtuber_env() -> EnvironmentManifest:
    """Default VTuber environment.

    Binds to the three conversation-oriented tools from
    template-vtuber-tools. Uses the vtuber stage chain.
    """
    return build_default_manifest(
        preset="vtuber",
        external_tool_names=["web_search", "news_search", "web_fetch"],
    ).with_metadata(
        id="template-vtuber-env",
        name="VTuber Environment",
        description="Lightweight conversational environment for VTuber persona.",
    )


_TEMPLATE_FACTORIES = [create_worker_env, create_vtuber_env]


def install_environment_templates(store: EnvironmentStore) -> int:
    """Install default environment templates if not already present."""
    installed = 0
    for factory in _TEMPLATE_FACTORIES:
        env = factory()
        if not store.exists(env.metadata.id):
            store.save(env)
            installed += 1
    return installed
```

Invoked from the app bootstrap — the same boot hook that runs
`install_templates` for tool presets.

Design choice confirmed: **seed materialized manifests on boot**
rather than derive on-the-fly. Reasons:

- The seeded env is **inspectable** — users can open the
  environment editor and see what their worker does.
- Edits to the seed env persist in the user's database and are
  picked up on next session create, matching how
  `ToolPresetStore` behaves today.
- Matches the user's directive: the default envs are **the
  environments users see in the UI**, not invisible defaults.

If the user later wants to reset to factory defaults, that's an
explicit "Reset environment" UI button that re-runs the seed.

### Step 3 — `ROLE_DEFAULT_ENV_ID` mapping

New constant in `backend/service/environment/templates.py` (or
`service/environment/role_defaults.py` — see final layout below):

```python
from service.claude_manager.models import SessionRole

ROLE_DEFAULT_ENV_ID: dict[str, str] = {
    SessionRole.WORKER.value:     "template-worker-env",
    SessionRole.DEVELOPER.value:  "template-worker-env",
    SessionRole.RESEARCHER.value: "template-worker-env",
    SessionRole.PLANNER.value:    "template-worker-env",
    SessionRole.VTUBER.value:     "template-vtuber-env",
}


def resolve_env_id(role: SessionRole | str | None, explicit: str | None) -> str:
    """Resolve the env_id a session should use.

    - If the caller passed an explicit env_id, honor it.
    - Otherwise look up the role default.
    - Unknown roles fall back to the worker env (same way unknown
      roles fall back to template-all-tools today).
    """
    if explicit:
        return explicit
    role_value = role.value if hasattr(role, "value") else (role or "")
    return ROLE_DEFAULT_ENV_ID.get(role_value.lower(), "template-worker-env")
```

### Step 4 — Wire role resolution into `create_agent_session`

`agent_session_manager.py:340-500` area. Today the env_id path is
gated on `if env_id:` (line 448). After this step, **every**
session takes the env_id path; `request.env_id` is just one input
to the resolver.

```python
# agent_session_manager.py (proposed, replaces lines 447-475 + whatever feeds _build_pipeline)

from service.environment.role_defaults import resolve_env_id

env_id = resolve_env_id(request.role, request.env_id)
if self._environment_service is None:
    raise RuntimeError(
        "EnvironmentService is required. AgentSessionManager must be "
        "constructed with environment_service= when the app starts."
    )
api_key = _resolve_api_key()
adhoc_providers = []
if self._tool_loader is not None:
    from service.langgraph.geny_tool_provider import GenyToolProvider
    adhoc_providers.append(GenyToolProvider(self._tool_loader))

prebuilt_pipeline = await self._environment_service.instantiate_pipeline(
    env_id,
    api_key=api_key,
    adhoc_providers=adhoc_providers,
    memory_manager=None,  # attached after AgentSession constructs it
    llm_reflect=None,
    curated_knowledge_manager=None,
)
```

Note: runtime objects are **not** passed at instantiate time. The
pipeline is constructed "bare" and the session attaches runtime
objects in its own init. This is because `memory_manager` /
`curated_km` / `llm_reflect` are all session-scoped — they require
the AgentSession to exist first.

### Step 5 — Refactor AgentSession to attach runtime after construction

`agent_session.py:635-758`. **Delete** the entire preset branch
(`GenyPresets.vtuber(...)` / `GenyPresets.worker_adaptive(...)`
call sites). The new `_build_pipeline` is:

```python
# agent_session.py (proposed, replaces lines 635-758)

def _build_pipeline(self):
    """Attach runtime objects to the pre-built manifest pipeline.

    The pipeline itself was built by EnvironmentService.instantiate_pipeline
    before this AgentSession was constructed. This method only injects
    the per-session runtime objects that cannot live in a manifest.
    """
    if self._prebuilt_pipeline is None:
        raise RuntimeError(
            f"[{self._session_id}] No prebuilt pipeline. "
            f"EnvironmentService did not run before AgentSession init — "
            f"check AgentSessionManager.create_agent_session wiring."
        )

    self._pipeline = self._prebuilt_pipeline

    # Build the runtime objects (session-scoped; cannot be serialized).
    api_key = _resolve_api_key()
    retriever = GenyMemoryRetriever(
        self._memory_manager,
        max_inject_chars=self._max_inject_chars,
        enable_vector_search=True,
        curated_knowledge_manager=self._curated_km,
    ) if self._memory_manager else None

    strategy = GenyMemoryStrategy(
        self._memory_manager,
        enable_reflection=True,
        llm_reflect=self._make_llm_reflect_callback(api_key),
        curated_knowledge_manager=self._curated_km,
    ) if self._memory_manager else None

    persistence = GenyPersistence(self._memory_manager) if self._memory_manager else None

    # Attach — requires executor v0.24.0.
    self._pipeline.attach_runtime(
        memory_retriever=retriever,
        memory_strategy=strategy,
        memory_persistence=persistence,
        llm_reflect=self._make_llm_reflect_callback(api_key),
        curated_knowledge_manager=self._curated_km,
    )

    self._preset_name = f"env:{self._env_id}"
```

Hardcoded `GenyPresets.*` imports and the `ReadTool/WriteTool/...`
registrations are removed — those are now declarative in the
manifest. The registry plumbing that `_build_pipeline` used to do
now lives in `from_manifest_async`.

### Step 6 — Delete `request.tool_preset_id` → `geny_tool_registry`
tracking where it is dead code

Today `create_agent_session` still builds a `geny_tool_registry`
from `request.tool_preset_id` and passes it to `AgentSession`.
Once step 5 lands, that registry is unused — the manifest's
`tools.external` list + `adhoc_providers` path owns tool
registration.

This step removes the `geny_tool_registry` plumbing (request
field, constructor arg, AgentSession attribute) entirely. The
tool preset itself stays (`ROLE_DEFAULT_PRESET` is still what
determines *which* tools land in `tools.external`), but the
dual-path divergence goes away.

### Step 7 — VTuber ↔ Worker binding (see Plan/03)

Covered in detail in `plan/03_vtuber_worker_binding.md`. Summary:

- VTuber session spawn: in `create_agent_session`, if the
  resolved role is VTuber, after creating the VTuber session,
  auto-create a paired session with `role=WORKER`,
  `env_id=template-worker-env`,
  `linked_session_id=<vtuber_session_id>`,
  `session_type="cli"`.
- Update VTuber session record with
  `linked_session_id=<worker_session_id>`, `session_type="vtuber"`.
- Inject "Paired Worker Agent" block into VTuber system prompt
  with the Worker's session_id.
- The existing CLI-pairing code (`agent_session_manager.py:587-660`)
  becomes the implementation scaffold — clean it up and rename
  variables from `cli_*` to `bound_worker_*` to match the new
  mental model.

---

## Final layout after this plan

```
backend/service/environment/
├── service.py            # EnvironmentService (unchanged surface, fewer conditionals)
├── store.py              # EnvironmentStore (unchanged)
├── templates.py          # NEW: create_worker_env, create_vtuber_env, install_environment_templates
└── role_defaults.py      # NEW: ROLE_DEFAULT_ENV_ID, resolve_env_id

backend/service/langgraph/
├── default_manifest.py   # stages[...] populated for worker_adaptive & vtuber
├── agent_session.py      # _build_pipeline reduced to attach_runtime
├── agent_session_manager.py  # unconditional env_id path, VTuber↔Worker spawn via plan/03
├── geny_tool_provider.py # unchanged
└── tool_bridge.py        # unchanged after Plan/01 PR I
```

Deleted:
- Preset branching inside `_build_pipeline`.
- `geny_tool_registry` constructor plumbing (moves to manifest).
- Any `if env_id:` conditionals in the session create path (env_id
  is always resolved now).

---

## PR decomposition

| # | Title | Depends on | Executor release |
|---|-------|------------|-----------------|
| 1 | **Executor**: `Pipeline.attach_runtime` + manifest stage templates for worker_adaptive/vtuber | Plan/01 done | v0.24.0 |
| 2 | **Geny**: pin bump to `>=0.24.0,<0.25.0` | PR 1 merged & released | — |
| 3 | **Geny**: populate `build_default_manifest.stages` for both presets + unit tests that assert stage list parity against old `GenyPresets.*` | PR 2 | — |
| 4 | **Geny**: seed `install_environment_templates`, add `ROLE_DEFAULT_ENV_ID`, add `resolve_env_id` | PR 3 | — |
| 5 | **Geny**: `AgentSessionManager` always resolves `env_id`, always takes the manifest path. Delete `if env_id:` gate and the `geny_tool_registry` plumbing | PR 4 | — |
| 6 | **Geny**: `AgentSession._build_pipeline` becomes `attach_runtime` only. Delete `GenyPresets.*` imports and preset branches | PR 5 | — |
| 7 | **Geny**: VTuber↔Worker binding cleanup (see Plan/03 for its own PR decomposition) | PR 6 | — |

Each Geny PR is accompanied by a progress doc in
`dev_docs/20260420_3/progress/`.

---

## What breaks, and how we verify

Because this is a full cutover, the following must be
deliberately re-tested end-to-end before declaring done:

- [ ] Worker session (any of worker/developer/researcher/planner)
      without explicit `env_id` resolves to template-worker-env
      and runs a simple "Read this file" task successfully.
- [ ] VTuber session without explicit `env_id` resolves to
      template-vtuber-env. The VTuber chats; it does **not** run
      code tools directly (by design — its manifest excludes them).
- [ ] VTuber spawns bound Worker. Bound Worker has
      `role=WORKER`, `env_id=template-worker-env`, and
      `linked_session_id` pointing back at the VTuber.
- [ ] `news_search` from the VTuber session succeeds (this is the
      Plan/01 regression guard — must still pass after Plan/02's
      larger surface-area changes).
- [ ] Explicit `request.env_id` is still honored (custom envs
      still work; the resolver gives precedence to explicit).
- [ ] Environment editor UI can open, display, and edit
      `template-worker-env` / `template-vtuber-env` exactly as
      it would a user-created env.

Rollback plan: if a PR in this sequence ships and breaks more
than expected, revert to the last green commit rather than
patching forward. The sequence is intentionally small per-PR so
a single revert restores a working state.

---

## Non-goals

- **No new environment types** beyond WORKER and VTUBER in this
  plan. Users can still create their own envs through the
  existing UI; we just don't seed more than two.
- **No "reset-to-default" UI button** in this plan. It's an
  obvious follow-on but not required for cutover.
- **No changes to MCP server handling.** MCP plumbing was
  finalized in 20260420_2 (PRs #23–#24) and stays put.
- **No renaming of the VTuber role or its prompt.** Role enum
  stays as-is; only the env resolution and pipeline-build path
  change.
