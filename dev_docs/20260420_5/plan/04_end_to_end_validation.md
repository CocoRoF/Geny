# Plan 04 — PR #4: End-to-end validation

**Branch.** `test/tool-use-e2e-validation`
**Depends on.** PR #1, #2, #3 all merged.

## Goal

Lock the fixes in with a regression harness that would have
caught every defect in this cycle, had it existed.

## New tests

### 1. Registry roster parity (unit)

`backend/tests/service/environment/test_tool_registry_roster.py`

```python
@pytest.mark.asyncio
async def test_worker_env_registry_contains_platform_tools(api_key):
    loader = get_tool_loader()
    manifest = create_worker_env(
        external_tool_names=loader.get_all_names()
    )
    # Persist, then instantiate through the real service path
    service = EnvironmentService(storage_path=<tmp>)
    service._write_manifest(WORKER_ENV_ID, manifest)
    provider = GenyToolProvider(loader)
    pipeline = await service.instantiate_pipeline(
        WORKER_ENV_ID, api_key=api_key, adhoc_providers=[provider]
    )
    registered = set(pipeline.tool_registry.list_names())
    assert "geny_send_direct_message" in registered
    assert "memory_read" in registered
    assert "knowledge_search" in registered
    assert "web_search" in registered


@pytest.mark.asyncio
async def test_vtuber_env_registry_excludes_browser(api_key):
    loader = get_tool_loader()
    manifest = create_vtuber_env(
        all_tool_names=loader.get_all_names()
    )
    ...
    registered = set(pipeline.tool_registry.list_names())
    assert "geny_send_direct_message" in registered
    for name in registered:
        assert not name.startswith("browser_"), name
```

These tests run against the real pipeline construction path —
so they catch regressions whether the bug lives in the manifest
factory, the provider, the executor, or the service layer.

### 2. SystemStage state.tools parity (unit)

`backend/tests/service/environment/test_system_stage_tools.py`

After `from_manifest_async`, walk to SystemStage and assert
it's holding the same registry object the pipeline exposes on
`pipeline.tool_registry` — the invariant v0.26.1 established
for the SystemStage side and v0.26.2 for the ToolStage side.
Mirrors upstream's `test_*_sees_populated_registry_after_*`
tests but at the Geny layer, so a future executor upgrade that
breaks the invariant is caught locally.

### 3. VTuber → Sub-Worker delegation (integration)

`backend/tests/integration/test_vtuber_dm_delegation.py`

```python
@pytest.mark.asyncio
async def test_vtuber_can_dm_sub_worker(live_backend, api_key):
    # Create a VTuber + Sub-Worker pair
    vtuber = await live_backend.create_session(role="vtuber", ...)
    sub_worker = vtuber.linked_session

    # Send a prompt that should trigger geny_send_direct_message
    result = await live_backend.execute(
        session_id=vtuber.session_id,
        prompt="Worker에게 '안녕'이라고 DM 보내줘.",
    )

    # Verify the tool was called successfully (no ERROR in event stream)
    tool_events = [e for e in result.events if e.type == "tool.execute_complete"]
    dm_event = next(
        e for e in tool_events
        if e.data.get("tool_name") == "geny_send_direct_message"
    )
    assert dm_event.data["errors"] == 0

    # Verify the message actually landed in the sub-worker's inbox
    inbox = _get_inbox_manager()
    messages = inbox.get_messages(sub_worker.session_id)
    assert any("안녕" in m["content"] for m in messages)
```

This test is gated on `ANTHROPIC_API_KEY` being available; it
should be marked `@pytest.mark.live` or similar so CI without
keys skips it. Local dev + nightly CI runs it.

## Progress doc

After the harness is green, write
`progress/14_tool_registration_architecture.md` (or next
available number in the sequence) documenting:

1. The dead-metadata defect (analysis 01).
2. The 4-PR resolution.
3. The regression tests and what each guards.
4. Pointer back to v0.26.1 / v0.26.2 progress docs so future
   readers see the complete arc: routing-layer fixes then
   roster-content fixes.

## Verification before merge

1. All three new test modules green locally.
2. Live VTuber → Sub-Worker chat: DM lands, file endpoints
   work, knowledge tools reachable.
3. Logs show `Environment templates installed: 2` with the
   expected external-tool count (≈ 15-20 depending on how many
   tools the current tree ships).

## Rollback

The harness itself is pure tests — rolling it back removes
coverage but breaks nothing. The functional fixes live in #1-#3
and are independent.
