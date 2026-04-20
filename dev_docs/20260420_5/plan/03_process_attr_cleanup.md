# Plan 03 — PR #3: `agent_controller.py` `.process` cleanup

**Branch.** `fix/controller-process-attr`
**Depends on.** independent of #1 / #2; sequenced after.

## Goal

Eliminate the six `agent.process` references that throw
`AttributeError` on modern manifest-backed sessions.

## Change surface — `backend/controller/agent_controller.py`

### Sites 1-3 (lines 307-308, 487-488, 525-528) — pure deletions

Before:

```python
agent._system_prompt = new_prompt
if agent.process:
    agent.process.system_prompt = new_prompt
```

After:

```python
agent._system_prompt = new_prompt
```

The `if agent.process:` branch was writing into a subprocess
`ClaudeProcess` that no longer exists. The assignment above it
already persists through the session layer; the removed block
is dead.

Apply the identical deletion at all three sites.

### Site 4 (lines 915-926) — `list_storage_files`

Before:

```python
process = agent.process
if not process:
    raise HTTPException(status_code=400, detail="AgentSession process not available")
folder = process.storage_path
```

After:

```python
folder = agent.storage_path
if not folder:
    raise HTTPException(
        status_code=400,
        detail="AgentSession storage_path not available",
    )
```

Then the rest of the function (using `folder` to walk files)
continues unchanged. The file-listing logic should switch to
`service.claude_manager.storage_utils.list_storage_files(folder)`
if that helper already exists (I've confirmed
`backend/service/claude_manager/storage_utils.py:186-296`
provides `list_storage_files` / `read_storage_file`). Replace
the inline `os.listdir` + walk with calls to the utility so we
stop duplicating logic — single source of truth.

### Site 5 (lines 942-953) — `read_storage_file`

Same pattern as site 4. Replace `agent.process.storage_path`
with `agent.storage_path`, delegate to
`storage_utils.read_storage_file(folder, path)`.

### Site 6 (lines 970-973) — download folder

Before:

```python
agent = agent_manager.get_agent(session_id)
if agent and agent.process:
    folder = agent.process.storage_path
else:
    store = get_session_store()
    ...
```

After:

```python
agent = agent_manager.get_agent(session_id)
if agent and agent.storage_path:
    folder = agent.storage_path
else:
    store = get_session_store()
    ...
```

## Test — `backend/tests/controller/test_agent_controller_files.py`

New file. Minimal smoke test:

```python
@pytest.mark.asyncio
async def test_list_storage_files_returns_200_for_manifest_session(
    client, seeded_worker_session
):
    response = await client.get(
        f"/sessions/{seeded_worker_session.session_id}/files"
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)

@pytest.mark.asyncio
async def test_read_storage_file_returns_200(client, seeded_worker_session):
    # create a file in the session's storage first
    ...
```

If the test harness doesn't have a `seeded_worker_session`
fixture, wire one: create an `AgentSession` via the manager in
conftest, yield it, tear down. Pattern exists in
`backend/tests/controller/test_*` — follow the closest
neighbour.

## Why this isn't bundled with PR #1/#2

Separation of concerns. PR #1 + #2 are about tool registration
at manifest build time — they touch `default_manifest.py`,
`templates.py`, `main.py`. PR #3 touches controller code. A
revert of either shouldn't force a revert of the other, and
bisecting regressions stays cleaner.

## Verification before merge

1. `pytest backend/tests/controller/test_agent_controller_files.py`
   green.
2. `grep -n "\.process\b" backend/controller/agent_controller.py`
   returns nothing.
3. Start backend, open the UI's file panel on a live session,
   confirm it lists files.

## Rollback

Revert. File endpoints break again; tool-registration fixes
from #1/#2 survive.
