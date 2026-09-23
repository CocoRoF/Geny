"""E.1 (cycle 20260426_1) — between-turn runtime refresh tests.

Verifies the queue + drain semantics of
``AgentSession.queue_runtime_refresh`` /
``AgentSession._apply_pending_runtime_refresh``. Direct method tests
against a fake Pipeline avoid spinning the full ``initialize`` path.

geny-executor 2.2.0: the drain step now goes through the *public*
``Pipeline.refresh_runtime(**attach_runtime_kwargs)`` instead of the
old private stage-slot setters, so the fakes expose ``refresh_runtime``.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# AgentSession transitively imports pydantic via service.sessions.models.
pytest.importorskip("pydantic")

from service.executor.agent_session import AgentSession  # noqa: E402


def _bare_session(*, initialized: bool = True, with_pipeline: bool = True) -> AgentSession:
    """Construct a minimal AgentSession without going through __init__,
    populating only the attrs the queue/drain helpers read."""
    s = AgentSession.__new__(AgentSession)
    s._session_id = "sx"
    s._initialized = initialized
    s._env_id = None  # _load_permission_host_selection reads this
    s._pipeline = (
        SimpleNamespace(refresh_runtime=MagicMock())
        if with_pipeline
        else None
    )
    s._pending_runtime_refresh = None
    return s


def test_queue_rejects_unknown_scope() -> None:
    s = _bare_session()
    assert s.queue_runtime_refresh("not-a-scope") is False
    assert s._pending_runtime_refresh is None


def test_queue_rejects_uninitialized_session() -> None:
    s = _bare_session(initialized=False)
    assert s.queue_runtime_refresh("permissions") is False


def test_queue_rejects_session_without_pipeline() -> None:
    s = _bare_session(with_pipeline=False)
    assert s.queue_runtime_refresh("permissions") is False


def test_queue_accepts_valid_scope() -> None:
    s = _bare_session()
    assert s.queue_runtime_refresh("permissions") is True
    assert s._pending_runtime_refresh == "permissions"


def test_apply_no_op_when_queue_empty() -> None:
    s = _bare_session()
    # Should not raise even when nothing's queued.
    s._apply_pending_runtime_refresh()
    s._pipeline.refresh_runtime.assert_not_called()


def test_apply_clears_flag_even_on_failure(monkeypatch) -> None:
    """A failed reload must NOT leave the queue stuck — the flag is
    one-shot and clears before the install call."""
    s = _bare_session()
    s.queue_runtime_refresh("permissions")

    # Stub install_permission_rules to raise.
    import service.permission.install as perm_install

    def boom(host_selection=None):
        raise RuntimeError("permission install failed")

    monkeypatch.setattr(perm_install, "install_permission_rules", boom)

    s._apply_pending_runtime_refresh()
    # Flag is cleared regardless of failure.
    assert s._pending_runtime_refresh is None


def test_apply_calls_permissions_setter(monkeypatch) -> None:
    """Happy path — install returns rules+mode; the executor's stage
    setter is called with them."""
    s = _bare_session()
    s.queue_runtime_refresh("permissions")

    import service.permission.install as perm_install

    fake_rules = ["rule1", "rule2"]
    fake_mode = "enforce"
    monkeypatch.setattr(
        perm_install,
        "install_permission_rules",
        lambda host_selection=None: (fake_rules, fake_mode),
    )
    # Identity-map the enforcement-gate coercion so the assert below
    # can pin the exact permission_mode forwarded to the pipeline.
    monkeypatch.setattr(
        perm_install, "_resolve_effective_executor_mode", lambda m: m,
    )

    s._apply_pending_runtime_refresh()

    s._pipeline.refresh_runtime.assert_called_once_with(
        permission_rules=fake_rules,
        permission_mode=fake_mode,
    )


def test_apply_with_scope_all_calls_both_setters(monkeypatch) -> None:
    s = _bare_session()
    s.queue_runtime_refresh("all")

    import service.permission.install as perm_install
    import service.hooks.install as hook_install

    monkeypatch.setattr(
        perm_install,
        "install_permission_rules",
        lambda host_selection=None: ([], "advisory"),
    )
    monkeypatch.setattr(
        hook_install, "install_hook_runner", lambda host_selection=None: object(),
    )

    s._apply_pending_runtime_refresh()
    # One refresh_runtime call per branch: permissions, then hooks.
    assert s._pipeline.refresh_runtime.call_count == 2
    kwarg_sets = [set(c.kwargs) for c in s._pipeline.refresh_runtime.call_args_list]
    assert {"permission_rules", "permission_mode"} in kwarg_sets
    assert {"hook_runner"} in kwarg_sets


def test_apply_skips_hook_when_install_returns_none(monkeypatch) -> None:
    """install_hook_runner returns ``None`` when the env gate is closed
    or no hooks are configured — refresh must skip the setter quietly."""
    s = _bare_session()
    s.queue_runtime_refresh("hooks")

    import service.hooks.install as hook_install

    monkeypatch.setattr(hook_install, "install_hook_runner", lambda host_selection=None: None)

    s._apply_pending_runtime_refresh()
    s._pipeline.refresh_runtime.assert_not_called()


# ── O.1 (cycle 20260426_3) — extended scopes ────────────────────


def _stage(name: str, slot_strategy=None, slot_name="retriever"):
    """Build a fake stage with one strategy slot."""
    slot = SimpleNamespace(strategy=slot_strategy)
    return SimpleNamespace(
        name=name,
        get_strategy_slots=lambda: {slot_name: slot},
    )


def _pipeline_with_stages(stages):
    """Wrap stages in a fake pipeline whose ``_stages.values()`` returns them."""
    p = SimpleNamespace(
        refresh_runtime=MagicMock(),
        _stages=SimpleNamespace(values=lambda: stages),
    )
    return p


def test_memory_tuning_scope_accepted() -> None:
    s = _bare_session()
    assert s.queue_runtime_refresh("memory_tuning") is True
    assert s._pending_runtime_refresh == "memory_tuning"


def test_affect_scope_accepted() -> None:
    s = _bare_session()
    assert s.queue_runtime_refresh("affect") is True
    assert s._pending_runtime_refresh == "affect"


def _tuning(**over):
    base = {
        "max_inject_chars": 10000,
        "recent_turns": 6,
        "enable_vector_search": True,
        "enable_reflection": True,
    }
    base.update(over)
    return lambda *, is_vtuber: dict(base)


def test_memory_tuning_refresh_changes_the_live_hooks(monkeypatch) -> None:
    """The refresh writes onto the ``MemoryHooks`` the provider and the
    Stage 2 retriever both hold — the thing retrieval actually reads.

    It used to write ``_max_inject`` / ``_recent_turns`` onto the retriever
    object, attributes of a class that no longer exists; the old test
    checked those writes on a stand-in that had them, so it passed while
    every real refresh logged "no slots matched" and changed nothing.
    """
    from geny_executor.memory.provider import MemoryHooks

    import service.memory.tuning as mem_cfg

    s = _bare_session()
    s._role = "worker"
    s._memory_config = None
    hooks = MemoryHooks(max_inject_chars=10, recent_turns=2, enable_vector_search=False)
    s._memory_hooks = hooks
    monkeypatch.setattr(
        mem_cfg, "load_memory_tuning",
        _tuning(max_inject_chars=30000, recent_turns=12, enable_vector_search=True),
    )

    s.queue_runtime_refresh("memory_tuning")
    s._apply_pending_runtime_refresh()

    assert s._memory_hooks is hooks, "the refresh must edit the shared instance, not replace it"
    assert (hooks.max_inject_chars, hooks.recent_turns, hooks.enable_vector_search) == (
        30000, 12, True,
    )
    assert "conversations" in hooks.transcript_categories


def test_memory_tuning_refresh_keeps_the_callbacks(monkeypatch) -> None:
    """The archivers hang off the same hooks; a refresh that rebuilt the
    bag would silently stop every conversation archive."""
    from geny_executor.memory.provider import MemoryHooks

    import service.memory.tuning as mem_cfg

    async def _archive(turn, receipt):  # noqa: ANN001
        return None

    s = _bare_session()
    s._role = "worker"
    s._memory_config = None
    hooks = MemoryHooks()
    hooks.after_record_turn = _archive
    s._memory_hooks = hooks
    monkeypatch.setattr(mem_cfg, "load_memory_tuning", _tuning(recent_turns=3))

    s.queue_runtime_refresh("memory_tuning")
    s._apply_pending_runtime_refresh()

    assert hooks.after_record_turn is _archive
    assert hooks.recent_turns == 3


def test_memory_tuning_refresh_honours_this_sessions_overrides(monkeypatch) -> None:
    """Build and refresh resolve tuning through one function, so a
    per-session override survives a refresh instead of being reverted to
    the global value."""
    from geny_executor.memory.provider import MemoryHooks

    import service.memory.tuning as mem_cfg

    s = _bare_session()
    s._role = "worker"
    s._memory_config = {"tuning": {"max_inject_chars": 4242}}
    s._memory_hooks = MemoryHooks()
    monkeypatch.setattr(mem_cfg, "load_memory_tuning", _tuning(max_inject_chars=30000))

    s.queue_runtime_refresh("memory_tuning")
    s._apply_pending_runtime_refresh()

    assert s._memory_hooks.max_inject_chars == 4242


def test_affect_apply_mutates_emitter(monkeypatch) -> None:
    """affect scope finds the AffectTagEmitter on Stage 17 and updates
    its _max_tags_per_turn."""
    s = _bare_session()
    emitter = SimpleNamespace(name="affect_tag", _max_tags_per_turn=1)
    chain = SimpleNamespace(items=[emitter])
    emit_stage = SimpleNamespace(
        name="emit",
        emitters=chain,
        get_strategy_slots=lambda: {},
    )
    s._pipeline = _pipeline_with_stages([emit_stage])

    import service.emit.chain_install as ci

    monkeypatch.setattr(ci, "_resolve_max_tags", lambda _default: 7)

    s.queue_runtime_refresh("affect")
    s._apply_pending_runtime_refresh()

    assert emitter._max_tags_per_turn == 7


def test_affect_apply_no_emitter_is_silent(monkeypatch) -> None:
    """If the chain has no AffectTagEmitter (manifest dropped it), the
    refresh quietly does nothing."""
    s = _bare_session()
    chain = SimpleNamespace(items=[])
    emit_stage = SimpleNamespace(
        name="emit",
        emitters=chain,
        get_strategy_slots=lambda: {},
    )
    s._pipeline = _pipeline_with_stages([emit_stage])

    import service.emit.chain_install as ci

    monkeypatch.setattr(ci, "_resolve_max_tags", lambda _default: 7)

    s.queue_runtime_refresh("affect")
    # Must not raise.
    s._apply_pending_runtime_refresh()


def test_all_scope_includes_new_branches(monkeypatch) -> None:
    """``all`` must touch the new memory/affect branches alongside the
    permissions/hooks ones."""
    from geny_executor.memory.provider import MemoryHooks

    s = _bare_session()
    s._memory_config = None
    s._memory_hooks = MemoryHooks(max_inject_chars=1, recent_turns=1, enable_vector_search=False)
    emitter = SimpleNamespace(name="affect_tag", _max_tags_per_turn=1)
    s._pipeline = _pipeline_with_stages([
        SimpleNamespace(
            name="emit",
            emitters=SimpleNamespace(items=[emitter]),
            get_strategy_slots=lambda: {},
        ),
    ])
    s._role = "worker"

    import service.memory.tuning as mem_cfg
    import service.emit.chain_install as ci
    import service.permission.install as perm_install
    import service.hooks.install as hook_install

    monkeypatch.setattr(
        mem_cfg, "load_memory_tuning",
        lambda *, is_vtuber: {
            "max_inject_chars": 99999,
            "recent_turns": 99,
            "enable_vector_search": True,
            "enable_reflection": True,
        },
    )
    monkeypatch.setattr(ci, "_resolve_max_tags", lambda _default: 42)
    monkeypatch.setattr(
        perm_install,
        "install_permission_rules",
        lambda host_selection=None: ([], "advisory"),
    )
    monkeypatch.setattr(hook_install, "install_hook_runner", lambda host_selection=None: object())

    s.queue_runtime_refresh("all")
    s._apply_pending_runtime_refresh()

    # Memory + affect both updated.
    assert s._memory_hooks.max_inject_chars == 99999
    assert emitter._max_tags_per_turn == 42
    # Permissions + hooks branches each went through refresh_runtime.
    assert s._pipeline.refresh_runtime.call_count == 2
