# 01 — Postgres backends for TaskRegistryStore + CronJobStore

**Phase:** 3 (after frontend completion + ops validation)
**PRs:** 4
**Risk:** medium — needs Geny SQLAlchemy session model audit before
the first migration ships.

---

## Why deferred from cycles A+B

InMemory + FileBacked impls cover dev / single-host prod. Postgres
backend is needed when:

1. multiple backend instances need a shared task / cron view
2. operators want to query task history with SQL
3. the file backend's `registry.jsonl` is hitting size limits
   (typically ~100k tasks)

None of those were blocking for cycle A+B prod cutover, so the
backends were deferred to keep the executor releases minimal.

---

## Pre-flight (before any code)

Audit Geny's existing SQLAlchemy session model:

1. **Read** `backend/service/database/` — find the session factory
   pattern in use (typically `async_sessionmaker` from
   sqlalchemy.ext.asyncio).
2. **Inspect** `backend/database/models.py` (or equivalent) for the
   declarative `Base` and existing migrations.
3. **Check** `backend/migrations/` for the Alembic config —
   we need to add two new tables (`background_tasks` + `cron_jobs`)
   with their own revision.
4. **Locate** how `app.state.app_db` (or equivalent) is plumbed into
   controllers — the new stores need the same session source.

The audit doc lives at `followup/01_pre_flight_audit.md` and gates
any of the PRs below.

---

## PR-D.1.1 — feat(service): PostgresTaskRegistryStore

### Files

- `backend/service/tasks/store_postgres.py` (new, ~250 lines)
- `backend/migrations/versions/<rev>_add_background_tasks_table.py`
  (new — Alembic revision)
- `backend/tests/service/tasks/test_postgres_store.py` (new,
  ~15 tests)

### Schema

```python
class BackgroundTaskRow(Base):
    __tablename__ = "background_tasks"
    id            = Column(String(64), primary_key=True)  # task_id
    kind          = Column(String(32), nullable=False, index=True)
    payload       = Column(JSONB, nullable=False, default=dict)
    status        = Column(String(16), nullable=False, index=True)
    created_at    = Column(DateTime(timezone=True), nullable=False, index=True)
    started_at    = Column(DateTime(timezone=True))
    completed_at  = Column(DateTime(timezone=True))
    error         = Column(Text)
    output_path   = Column(String(512))
    output_bytes  = Column(LargeBinary, nullable=False, default=b"")
                  # — small in-band buffer for short outputs;
                  # large outputs spill to output_path on disk
    iteration_seen = Column(Integer, nullable=False, default=0)
```

Indexes: `(status, created_at desc)` for `list_filtered` queries
under load.

### Implementation contract

Implements `geny_executor.stages.s13_task_registry.TaskRegistryStore`
ABC. Every method (`register / get / list_filtered / update_status /
remove / append_output / read_output / stream_output`) hits Postgres
through the host's session factory.

Streaming (`stream_output`):
- Postgres backend uses LISTEN/NOTIFY on the `background_tasks` table
  for terminal-status changes; output deltas use a polling loop
  with 500ms cadence (matches typical user-perceived latency).
- Falls back to pure polling when LISTEN/NOTIFY isn't available.

### Tests

`backend/tests/service/tasks/test_postgres_store.py`

Use the existing test Postgres fixture (find in
`backend/tests/conftest.py` or equivalent). Mark every test
`pytest.importorskip("sqlalchemy")` so devs without postgres
locally can still run the rest of the suite.

Coverage:
- round-trip register → get
- list_filtered by status / kind / created_after / limit
- update_status terminal transition stamps completed_at
- remove cascades output cleanup
- concurrent appends (asyncio.gather of 5 writers) preserve order
- stream_output yields bytes appended after consumer attached
- output_path overflow path (when buffer > 1MB, write to disk)

### Acceptance criteria

- [ ] every TaskRegistryStore ABC method covered
- [ ] every test passes against the test Postgres
- [ ] alembic upgrade head runs cleanly + downgrade is reversible
- [ ] `backend/service/tasks/install.py` learns the `postgres`
      backend choice (`GENY_TASK_BACKEND=postgres`)

### Risk + mitigation

| Risk | Mitigation |
|---|---|
| LISTEN/NOTIFY behavior varies by Postgres version | Default to polling; LISTEN/NOTIFY is opt-in via `GENY_TASK_USE_NOTIFY=1` |
| Large output payloads (>10MB) blowing the LargeBinary column | Auto-spill to disk at 1MB, store path in `output_path`, in-band buffer empty |
| Migration runs on a live db | New table only; no ALTER on existing tables; zero-downtime |

---

## PR-D.1.2 — feat(service): PostgresCronJobStore

### Files

- `backend/service/cron/store_postgres.py` (new, ~150 lines)
- `backend/migrations/versions/<rev>_add_cron_jobs_table.py` (new)
- `backend/tests/service/cron/test_postgres_store.py` (new)

### Schema

```python
class CronJobRow(Base):
    __tablename__ = "cron_jobs"
    name           = Column(String(64), primary_key=True)
    cron_expr      = Column(String(64), nullable=False)
    target_kind    = Column(String(32), nullable=False)
    payload        = Column(JSONB, nullable=False, default=dict)
    description    = Column(Text)
    status         = Column(String(16), nullable=False, default="enabled", index=True)
    created_at     = Column(DateTime(timezone=True), nullable=False)
    last_fired_at  = Column(DateTime(timezone=True))
    last_task_id   = Column(String(64))
```

### Implementation contract

Implements `geny_executor.cron.CronJobStore`. All async methods.

Idempotency: `mark_fired` uses `INSERT ... ON CONFLICT DO UPDATE`
so a CronRunner restart that re-fires the same job within the
same minute doesn't create a duplicate row. The runner's "no
catch-up" semantics from PR-A.4.3 still apply at the daemon
layer.

### Tests

- round-trip put → get
- list with `only_enabled` filter
- delete returns False for missing
- mark_fired upserts last_fired_at + last_task_id
- update_status changes enabled ↔ disabled

### Acceptance criteria

- [ ] CronJobStore ABC fully covered
- [ ] alembic upgrade/downgrade clean
- [ ] `backend/service/cron/install.py` learns `postgres` backend

---

## PR-D.1.3 — feat(infra): backend selector wiring

### Files

- `backend/service/tasks/install.py` (modify)
- `backend/service/cron/install.py` (modify)

### Change

Currently `_build_registry()` / `_build_store()` accept
`memory|file`. Add `postgres`:

```python
backend = os.getenv("GENY_TASK_BACKEND", "memory").lower()
if backend == "postgres":
    from service.tasks.store_postgres import PostgresTaskRegistryStore
    return PostgresTaskRegistryStore(session_factory=app_state.async_session_factory)
```

The session factory is the same one the rest of Geny uses (auth,
config, etc.) — no new pool, no separate engine. install_*
gains the `app_state` parameter so it can grab the factory.

### Acceptance criteria

- [ ] `GENY_TASK_BACKEND=postgres` boots successfully
- [ ] same for `GENY_CRON_BACKEND=postgres`
- [ ] startup log line shows which backend each runtime selected
- [ ] empty / missing `app_state.async_session_factory` falls back
      to `memory` with a warning (graceful degrade)

### Risk + mitigation

| Risk | Mitigation |
|---|---|
| Session factory not available at lifespan time | install_* runs after the db setup phase; verify the order in `main.py` |
| Postgres connection pool exhausted by background runner | Reuse Geny's existing pool; don't open a separate pool |

---

## PR-D.1.4 — chore(release): Geny pyproject + ops doc

### Scope

- bump `backend/pyproject.toml` if any new dep was needed (none
  expected — uses existing SQLAlchemy / asyncpg)
- update `06_cycle_ab_completion_report.md` "Operational deployment"
  section with the postgres backend env vars + alembic upgrade
  command
- add a one-line "Cycle D closeout" entry naming PR-D.1.1 ~ D.1.3

### Acceptance criteria

- [ ] documentation reflects the new env knobs
- [ ] no new top-level deps in pyproject.toml
- [ ] migration command documented for ops:
      `alembic upgrade head` (or whatever Geny's wrapper is)
