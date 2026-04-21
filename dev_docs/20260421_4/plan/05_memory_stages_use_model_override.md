# Plan 05 — PR-5: Memory stages consume the model-override interface

**Repo.** `/home/geny-workspace/geny-executor`
**Branch.** `feat/memory-stages-use-model-override`
**Depends on.** PR-1 (state helpers), PR-2
(`resolve_model_config`), PR-3 (`state.llm_client` +
`BaseClient` + `ClientRegistry`), PR-4 (s06_api migrated onto
the unified client). Merge order PR-1 → PR-2 → PR-3 → PR-4 →
PR-5.
**Blocks.** PR-6 (Geny host sets the overrides and expects
real consumers).
**Related analysis.**
- Analysis 02 §1 — Geny's `_make_llm_reflect_callback` (the
  prompt replicated by the native path).
- Analysis 02 §5 — SummaryCompactor stub.
- Analysis 03 §8 — `state.llm_client` is an optional slot;
  this PR is where optional becomes useful in practice.

## 1. Goal

Replace two stub/dead memory-side LLM hookpoints with real
calls that use the newly standardized interface:

- **s02 `SummaryCompactor`** — currently emits a static
  placeholder. Replace with a real summarization call that
  reads `resolve_model_config(state)` and uses
  `state.llm_client`, **gated on a non-None override**.
- **`GenyMemoryStrategy._reflect`** — currently invokes an
  injected callback or sets a flag. Add a native reflection
  path that uses `resolve_model_config(state)` +
  `state.llm_client` when *both* the callback is absent *and*
  a model override is configured on the hosting stage. The
  callback path is preserved as a legacy branch.

Both changes respect the **no-cost-by-default** rule from
index.md risk 1: if no override is set, no new LLM call
happens.

## 2. Non-goals

- **No change to s15 provider reflection.** Analysis 02 Site 6
  is the `MemoryProvider.reflect()` layer; it remains stubbed
  (concrete providers return `()`). Geny uses the
  `GenyMemoryStrategy` path instead. Follow-up cycle handles
  the provider path.
- **No LLM gate for retrieval.** Analysis 02 Site 5 stays
  unwired.
- **No new events in the log panel.** Cycle 20260421_3's
  generic `stage.enter/exit` already surfaces stage activity;
  the new domain events below (`memory.compaction.summarized`,
  `memory.reflection.native`) flow into `state.add_event`
  which streams via the listener. The Geny frontend already
  renders unknown event types generically.
- **No config-level toggle.** A stage runs the new path iff a
  `ModelConfig` is set on it via `PipelineMutator.set_stage_model`
  — no `enable_llm_compaction` flag. Config knobs proliferate
  quickly; one signal (the override) is enough.
- **No vendor-specific branching in memory stages.** Memory
  stages call `state.llm_client.create_message(...)`; the
  client's capability flags handle any dropped features.
  `LLMSummaryCompactor` and `GenyMemoryStrategy` never branch
  on `client.provider`.

## 3. Changes

### 3.1 s02 `SummaryCompactor` — real summarization

The compactor lives in
`src/geny_executor/stages/s02_context/artifact/default/compactors.py`.
Today it's a pure function of `state.messages`. For the new
path it needs access to `state.llm_client` and
`resolve_model_config` — but compactors don't currently own a
stage handle.

**Design.** The parent stage (s02 context) already owns the
compactor via a slot. The compactor's `compact(state)` method
stays the same shape, but the compactor class gains two
optional constructor kwargs: a model-config resolver and a
client resolver. Instead of threading the parent stage through,
we pass lambdas that close over the parent.

Add a **new compactor class** `LLMSummaryCompactor` that
subclasses `SummaryCompactor` and overrides `compact`. The old
`SummaryCompactor` stays in place as the non-LLM fallback so no
caller who instantiates it directly breaks.

```python
# src/geny_executor/stages/s02_context/artifact/default/compactors.py

from typing import Any, Awaitable, Callable, Optional

from geny_executor.core.config import ModelConfig
from geny_executor.llm_client import BaseClient


class LLMSummaryCompactor(SummaryCompactor):
    """Summary compactor that calls the shared LLM client when given an
    override. Falls back to the static SummaryCompactor placeholder when
    the override is None, so the no-cost-by-default guarantee holds.

    Args:
        keep_recent: Number of recent messages to keep verbatim.
        summary_text: Optional static fallback; used when resolve_cfg
            returns a plain (non-override) config. Same semantics as
            the parent class.
        resolve_cfg: Callable taking ``state`` and returning the effective
            :class:`ModelConfig`. Typically bound to
            ``lambda s: parent_stage.resolve_model_config(s)`` by the
            enclosing stage.
        has_override: Callable taking nothing and returning True iff the
            enclosing stage has an explicit ``model_override`` set. If
            False we skip the LLM call even though ``resolve_cfg`` would
            return a config built from state defaults.
        client_getter: Callable taking ``state`` and returning the
            :class:`BaseClient` (typically ``lambda s: s.llm_client``).
    """

    def __init__(
        self,
        *,
        keep_recent: int = 10,
        summary_text: str = "",
        resolve_cfg: Optional[Callable[[PipelineState], ModelConfig]] = None,
        has_override: Optional[Callable[[], bool]] = None,
        client_getter: Optional[Callable[[PipelineState], Optional[BaseClient]]] = None,
    ):
        super().__init__(keep_recent=keep_recent, summary_text=summary_text)
        self._resolve_cfg = resolve_cfg
        self._has_override = has_override or (lambda: False)
        self._client_getter = client_getter or (lambda s: getattr(s, "llm_client", None))

    @property
    def name(self) -> str:
        return "llm_summary"

    @property
    def description(self) -> str:
        return "LLM-backed summary compactor (falls back to placeholder when no override is set)"

    async def compact(self, state: PipelineState) -> None:
        if len(state.messages) <= self._keep_recent:
            return

        if not self._has_override() or self._resolve_cfg is None:
            # No override set → preserve the pre-cycle behavior (static placeholder).
            await super().compact(state)
            return

        client = self._client_getter(state)
        if client is None:
            await super().compact(state)
            return

        old_count = len(state.messages) - self._keep_recent
        old_msgs = state.messages[: -self._keep_recent]
        recent = state.messages[-self._keep_recent :]

        # Build a transcript-style prompt.
        transcript_lines = []
        for m in old_msgs:
            role = m.get("role", "")
            content = m.get("content", "")
            if isinstance(content, list):
                text_parts = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                content = "\n".join(text_parts)
            transcript_lines.append(f"{role}: {content}")
        transcript = "\n".join(transcript_lines)[:12000]

        prompt = (
            "Summarize the following conversation transcript so the essential "
            "facts, user requests, decisions, and unresolved items are preserved. "
            "Keep it under ~500 words. Write a flat recap, not a bullet list.\n\n"
            f"<transcript>\n{transcript}\n</transcript>"
        )

        cfg = self._resolve_cfg(state)
        try:
            resp = await client.create_message(
                model_config=cfg,
                messages=[{"role": "user", "content": prompt}],
                purpose="s02.compact",
            )
            summary_text = (resp.text or "").strip()
            if not summary_text:
                summary_text = self._summary_text or (
                    f"[Summary of {old_count} previous messages.]"
                )
        except Exception as exc:
            # Client raised (rate limit, timeout, etc.). Do not block the run —
            # degrade to the static placeholder.
            state.add_event(
                "memory.compaction.llm_failed",
                {"error": str(exc), "compactor": self.name},
            )
            await super().compact(state)
            return

        state.messages = [
            {"role": "user", "content": summary_text},
            {
                "role": "assistant",
                "content": "Understood, I have the context from our previous conversation.",
            },
        ] + recent
        state.add_event(
            "memory.compaction.summarized",
            {
                "model": cfg.model,
                "provider": getattr(client, "provider", ""),
                "old_count": old_count,
                "summary_chars": len(summary_text),
            },
        )
```

**Wiring inside s02 stage.** The parent s02 context stage
constructs the compactor via its slot. Today (analysis 01 §7)
the default is `SummaryCompactor()`. The s02 stage's
`__init__` binds the compactor lambdas so the compactor can
resolve config + client via the parent:

```python
# inside s02_context/artifact/default/stage.py (pseudocode of the diff)

def _make_compactor(self) -> Any:
    return LLMSummaryCompactor(
        keep_recent=self._keep_recent,
        summary_text=self._summary_text,
        resolve_cfg=lambda s: self.resolve_model_config(s),
        has_override=lambda: self._model_override is not None,
        client_getter=lambda s: getattr(s, "llm_client", None),
    )
```

(Exact method name and wiring depend on current stage code —
the audit listed the compactor as a strategy-slot child, so
construction happens at stage init time. The PR implementor
reads the current s02 stage file and adds the binding where
the compactor is instantiated.)

**Backward compatibility.** The default artifact's manifest
currently names `SummaryCompactor` (if any manifest does — none
in the main repo, but externally built manifests might). Keep
`SummaryCompactor` as a class so manifests referencing it by
name still resolve. The stage-level default shifts to
`LLMSummaryCompactor`; consumers who explicitly chose
`SummaryCompactor` via a manifest keep static behavior.

**Local-state use.** Optional but worthwhile: the compactor
stashes the fact that it has summarized *this* iteration under
`self.local_state(state)["last_compacted_iteration"] =
state.iteration` — the parent stage can read that to avoid
double-compacting in a tight loop. If the compactor is a
child of the stage (not a stage itself), it can access
`local_state` via its binding closure — or simply write to
`state.shared["s02.last_compacted_iteration"] = …`. Either is
acceptable; the plan recommends `state.shared` keyed with the
stage-name prefix because the compactor is not a stage.

### 3.2 `GenyMemoryStrategy._reflect` — native LLM path

File: `src/geny_executor/memory/strategy.py`.

Add a constructor kwarg `resolver: Optional[ReflectionResolver] = None`
where `ReflectionResolver` is a small protocol that mirrors the
compactor's closures:

```python
# In geny_executor/memory/strategy.py

from dataclasses import dataclass

from geny_executor.llm_client import BaseClient


@dataclass
class ReflectionResolver:
    """Glue between the strategy and the hosting Memory stage, so the
    strategy can obtain the stage's ModelConfig and the shared
    BaseClient without knowing about the stage class."""

    resolve_cfg: Callable[["PipelineState"], Any]
    has_override: Callable[[], bool]
    client_getter: Callable[["PipelineState"], Optional[BaseClient]] = (
        lambda s: getattr(s, "llm_client", None)
    )
```

Extend `GenyMemoryStrategy.__init__` with:

```python
def __init__(
    self,
    memory_manager: Any,
    *,
    enable_reflection: bool = True,
    llm_reflect: Optional[Callable[[str, str], Awaitable[List[Dict[str, Any]]]]] = None,
    max_insights: int = 3,
    auto_promote_importance: Optional[set] = None,
    curated_knowledge_manager: Any = None,
    resolver: Optional[ReflectionResolver] = None,
) -> None:
    ...
    self._resolver = resolver
```

Update `_reflect`:

```python
async def _reflect(self, state: PipelineState) -> None:
    """Extract reusable insights from execution via LLM.

    Resolution order:
        1. If ``llm_reflect`` callback was provided, use it (legacy path).
        2. Else if a ``ReflectionResolver`` was provided AND the hosting
           stage has an explicit override AND ``state.llm_client`` is
           available → run a native reflection call.
        3. Else set ``state.metadata["needs_reflection"] = True`` and
           emit ``memory.reflection_queued`` (pre-cycle behavior).
    """
    input_text = ""
    for msg in state.messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                input_text = content
            break
    output_text = state.final_text

    if self._llm_reflect is not None:
        if not input_text.strip() or not output_text.strip():
            return
        try:
            insights = await self._llm_reflect(input_text[:2000], output_text[:3000])
        except Exception:
            logger.warning("geny_strategy: callback reflection failed", exc_info=True)
            return
        await self._save_insights(state, insights)
        return

    if self._resolver is None or not self._resolver.has_override():
        state.metadata["needs_reflection"] = True
        state.add_event(
            "memory.reflection_queued",
            {
                "message_count": len(state.messages),
                "iteration": state.iteration,
            },
        )
        return

    client = self._resolver.client_getter(state)
    if client is None:
        state.metadata["needs_reflection"] = True
        state.add_event("memory.reflection_queued", {"reason": "no_llm_client"})
        return

    if not input_text.strip() or not output_text.strip():
        return

    prompt = (
        "Analyze the following execution and extract any reusable knowledge, "
        "decisions, or insights worth remembering for future tasks.\n\n"
        f"<input>\n{input_text[:2000]}\n</input>\n\n"
        f"<output>\n{output_text[:3000]}\n</output>\n\n"
        "Extract concise, reusable insights. Skip trivial/obvious observations.\n\n"
        'Respond with JSON only:\n'
        '{\n'
        '  "learned": [\n'
        '    {\n'
        '      "title": "concise title (3-10 words)",\n'
        '      "content": "what was learned (1-3 sentences)",\n'
        '      "category": "topics|insights|entities|projects",\n'
        '      "tags": ["tag1", "tag2"],\n'
        '      "importance": "low|medium|high"\n'
        '    }\n'
        '  ],\n'
        '  "should_save": true\n'
        '}\n\n'
        'If nothing meaningful was learned, return:\n'
        '{"learned": [], "should_save": false}'
    )

    cfg = self._resolver.resolve_cfg(state)
    try:
        resp = await client.create_message(
            model_config=cfg,
            messages=[{"role": "user", "content": prompt}],
            purpose="s15.reflect",
        )
        text = (resp.text or "").strip()
        if text.startswith("```"):
            # strip optional fenced-json wrapping
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        import json as _json
        data = _json.loads(text)
        if not data.get("should_save"):
            state.add_event(
                "memory.reflection.native",
                {"saved": 0, "model": cfg.model, "provider": getattr(client, "provider", "")},
            )
            return
        insights = data.get("learned") or []
    except Exception as exc:
        state.add_event(
            "memory.reflection.llm_failed",
            {"error": str(exc), "source": "native"},
        )
        return

    await self._save_insights(state, insights, source_label="reflection_native")
    state.add_event(
        "memory.reflection.native",
        {
            "saved": min(len(insights), self._max_insights),
            "model": cfg.model,
            "provider": getattr(client, "provider", ""),
        },
    )
```

And extract the insight-persistence tail of the old method
into a helper `_save_insights` so both paths reuse it:

```python
async def _save_insights(
    self,
    state: PipelineState,
    insights: List[Dict[str, Any]],
    *,
    source_label: str = "reflection",
) -> None:
    if not insights:
        return
    write_note = getattr(self._mgr, "write_note", None)
    if write_note is None:
        return
    saved = 0
    for item in insights[: self._max_insights]:
        try:
            filename = write_note(
                title=item.get("title", "Insight"),
                content=item.get("content", ""),
                category=item.get("category", "insights"),
                tags=item.get("tags", []),
                importance=item.get("importance", "medium"),
                source=source_label,
            )
            if filename:
                saved += 1
                importance = item.get("importance", "medium")
                if importance in self._auto_promote and self._curated:
                    try:
                        self._curated.write_note(
                            title=item.get("title", "Insight"),
                            content=item.get("content", ""),
                            category=item.get("category", "insights"),
                            tags=item.get("tags", []) + ["auto-promoted"],
                            importance=importance,
                            source="promoted",
                        )
                    except Exception:
                        pass
        except Exception:
            logger.debug(
                "geny_strategy: failed to save insight '%s'",
                item.get("title", "?"),
                exc_info=True,
            )
    if saved:
        state.add_event("memory.insights_saved", {"count": saved})
```

### 3.3 s15 stage wires the resolver

File:
`src/geny_executor/stages/s15_memory/artifact/default/stage.py`
(or wherever `GenyMemoryStrategy` is hooked up by default — in
this repo the strategy is usually injected via `attach_runtime`
rather than set as a default, but if a default exists it
needs the resolver too).

When `attach_runtime(memory_strategy=strategy)` is called *and*
the strategy is a `GenyMemoryStrategy`, the s15 stage should
monkey-attach the resolver post-hoc:

```python
# inside MemoryStage.on_enter (first-time hook) or a post-attach init
def _attach_resolver_if_possible(self) -> None:
    strat = self._strategy_slot.strategy  # pseudocode
    if strat is None:
        return
    if not isinstance(strat, GenyMemoryStrategy):
        return  # only the Geny strategy knows about ReflectionResolver
    if strat._resolver is not None:
        return
    strat._resolver = ReflectionResolver(
        resolve_cfg=lambda s: self.resolve_model_config(s),
        has_override=lambda: self._model_override is not None,
        client_getter=lambda s: getattr(s, "llm_client", None),
    )
```

Alternative (cleaner): `Pipeline.attach_runtime` itself is
responsible for binding the resolver when
`memory_strategy` is a `GenyMemoryStrategy`. Documented in
plan/06 — Geny passes the strategy; the pipeline adds the
resolver.

The **simplest** implementation is to let Geny build the
resolver directly:

```python
# in Geny's _build_pipeline (plan/06)
resolver = ReflectionResolver(
    resolve_cfg=lambda s: s15_stage.resolve_model_config(s),
    has_override=lambda: s15_stage._model_override is not None,
    client_getter=lambda s: getattr(s, "llm_client", None),
)
strategy = GenyMemoryStrategy(memory_manager, resolver=resolver, llm_reflect=None)
```

Since Geny already reaches into the pipeline to wire things up
(attach_runtime is the mechanism), adding the resolver at the
same call site is natural. **Plan/05 ships the resolver
plumbing; plan/06 wires it from Geny.**

### 3.4 `StageIntrospection.model_override_supported`

Update s02 context and s15 memory stages to report True for
`model_override_supported` in their introspection surface.
This is the user-facing signal the frontend reads to decide
whether to render a model-picker cell for that stage. Today
(analysis 01 §9) only s06_api is True; after PR-5, s02 and s15
join.

### 3.5 Docstring cleanup

Drop the `SummaryCompactor` docstring's line:

> Note: actual summarization would require an API call. This
> implementation provides the structural framework;
> integration with the API stage would be done at the pipeline level.

Replace with:

> Non-LLM fallback: replaces dropped messages with a static
> placeholder. See :class:`LLMSummaryCompactor` for the real
> summarization path that calls ``state.llm_client``.

## 4. Tests

### 4.1 `tests/stages/s02_context/test_llm_summary_compactor.py`

```python
"""Tests for LLMSummaryCompactor — gated on override + client."""

import pytest

from geny_executor.core.config import ModelConfig
from geny_executor.core.state import PipelineState
from geny_executor.stages.s02_context.artifact.default.compactors import LLMSummaryCompactor
from tests.fixtures.mock_clients import MockClient


def _state_with_messages(n: int) -> PipelineState:
    s = PipelineState()
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        s.messages.append({"role": role, "content": f"msg {i}"})
    return s


@pytest.mark.asyncio
async def test_no_override_falls_back_to_placeholder():
    state = _state_with_messages(25)
    comp = LLMSummaryCompactor(
        keep_recent=10,
        resolve_cfg=lambda s: ModelConfig(model="claude-sonnet-4-6"),
        has_override=lambda: False,  # ← no override
        client_getter=lambda s: MockClient(default_text="LLM SUMMARY"),
    )
    await comp.compact(state)
    assert len(state.messages) == 10 + 2  # 10 recent + 2 placeholder
    assert "[Summary of 15 previous messages" in state.messages[0]["content"]


@pytest.mark.asyncio
async def test_override_and_client_triggers_llm_call():
    state = _state_with_messages(25)
    state.llm_client = MockClient(default_text="REAL SUMMARY")
    comp = LLMSummaryCompactor(
        keep_recent=10,
        resolve_cfg=lambda s: ModelConfig(model="claude-haiku-4-5-20251001", max_tokens=512),
        has_override=lambda: True,
        client_getter=lambda s: s.llm_client,
    )
    await comp.compact(state)
    assert state.messages[0]["content"] == "REAL SUMMARY"
    events = [e for e in state.events if e["type"] == "memory.compaction.summarized"]
    assert len(events) == 1
    assert events[0]["data"]["model"] == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_client_failure_falls_back_to_placeholder():
    class _BoomClient(MockClient):
        async def create_message(self, **kwargs):
            raise RuntimeError("boom")

    state = _state_with_messages(25)
    state.llm_client = _BoomClient()
    comp = LLMSummaryCompactor(
        keep_recent=10,
        resolve_cfg=lambda s: ModelConfig(model="claude-haiku-4-5-20251001"),
        has_override=lambda: True,
        client_getter=lambda s: s.llm_client,
    )
    await comp.compact(state)
    # Fell back — placeholder string is present
    assert "[Summary of 15 previous messages" in state.messages[0]["content"]
    # And the failure was logged as an event
    assert any(e["type"] == "memory.compaction.llm_failed" for e in state.events)


@pytest.mark.asyncio
async def test_below_keep_recent_is_noop():
    state = _state_with_messages(5)
    original = list(state.messages)
    comp = LLMSummaryCompactor(
        keep_recent=10,
        resolve_cfg=lambda s: ModelConfig(model="x"),
        has_override=lambda: True,
        client_getter=lambda s: MockClient(),
    )
    await comp.compact(state)
    assert state.messages == original  # unchanged
```

### 4.2 `tests/memory/test_strategy_native_reflect.py`

```python
"""Tests for GenyMemoryStrategy native reflection path (no callback)."""

import json

import pytest

from geny_executor.core.config import ModelConfig
from geny_executor.core.state import PipelineState, TokenUsage
from geny_executor.llm_client.types import APIResponse, ContentBlock
from geny_executor.memory.strategy import GenyMemoryStrategy, ReflectionResolver
from tests.fixtures.mock_clients import MockClient


class _ScriptedClient(MockClient):
    """Always returns JSON matching the GenyMemoryStrategy native prompt."""

    def __init__(self, payload: dict):
        super().__init__()
        self._payload = payload

    async def create_message(self, *, model_config, messages, system="", tools=None,
                             tool_choice=None, purpose=""):
        self._call_history.append({"model_config": model_config, "messages": messages})
        self._call_count += 1
        text = json.dumps(self._payload)
        return APIResponse(
            content=[ContentBlock(type="text", text=text)],
            stop_reason="end_turn",
            usage=TokenUsage(input_tokens=10, output_tokens=20),
            model=model_config.model,
            message_id="scripted_1",
        )


class _FakeManager:
    def __init__(self):
        self.notes = []

    def write_note(self, **kwargs):
        self.notes.append(kwargs)
        return f"note_{len(self.notes)}.md"


@pytest.mark.asyncio
async def test_native_path_runs_when_callback_missing_and_override_set():
    payload = {
        "learned": [{"title": "T", "content": "C", "category": "insights",
                     "tags": ["a"], "importance": "high"}],
        "should_save": True,
    }
    mgr = _FakeManager()
    state = PipelineState()
    state.messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]
    state.final_text = "world"
    state.llm_client = _ScriptedClient(payload)

    strat = GenyMemoryStrategy(
        mgr,
        llm_reflect=None,
        resolver=ReflectionResolver(
            resolve_cfg=lambda s: ModelConfig(model="claude-haiku-4-5-20251001", max_tokens=1024),
            has_override=lambda: True,
        ),
    )
    await strat._reflect(state)
    assert len(mgr.notes) == 1
    assert mgr.notes[0]["title"] == "T"
    events = [e for e in state.events if e["type"] == "memory.reflection.native"]
    assert len(events) == 1
    assert events[0]["data"]["model"] == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_native_path_skipped_when_no_override():
    mgr = _FakeManager()
    state = PipelineState()
    state.messages = [{"role": "user", "content": "hi"}]
    state.final_text = "out"
    state.llm_client = _ScriptedClient({"learned": [], "should_save": False})
    strat = GenyMemoryStrategy(
        mgr,
        llm_reflect=None,
        resolver=ReflectionResolver(
            resolve_cfg=lambda s: ModelConfig(model="x"),
            has_override=lambda: False,  # ← no override
        ),
    )
    await strat._reflect(state)
    assert mgr.notes == []  # no LLM call, no insights
    assert state.metadata.get("needs_reflection") is True
    assert any(e["type"] == "memory.reflection_queued" for e in state.events)


@pytest.mark.asyncio
async def test_callback_still_wins_when_both_available():
    calls = []
    async def cb(inp, out):
        calls.append((inp, out))
        return [{"title": "cb", "content": "via callback",
                 "category": "insights", "tags": [], "importance": "medium"}]

    mgr = _FakeManager()
    state = PipelineState()
    state.messages = [{"role": "user", "content": "hi"}]
    state.final_text = "out"
    state.llm_client = _ScriptedClient({"learned": [], "should_save": False})
    strat = GenyMemoryStrategy(
        mgr,
        llm_reflect=cb,  # ← callback takes precedence
        resolver=ReflectionResolver(
            resolve_cfg=lambda s: ModelConfig(model="x"),
            has_override=lambda: True,
        ),
    )
    await strat._reflect(state)
    assert len(calls) == 1
    assert mgr.notes and mgr.notes[0]["title"] == "cb"  # via callback, not native
```

### 4.3 Introspection test

Extend whatever introspection test exists for
`model_override_supported` to assert that s02 context and s15
memory now report True.

### 4.4 Capability-drop smoke test

```python
@pytest.mark.asyncio
async def test_compactor_works_when_client_drops_thinking(capsys):
    """Compactor must not crash when the client silently drops unsupported
    fields (e.g. OpenAI/vLLM dropping thinking_enabled). The feature_unsupported
    event goes to the sink; the call still succeeds."""
    # Use a client with supports_thinking=False and a ModelConfig that requests it
    from tests.fixtures.mock_clients import MockClient
    client = MockClient(default_text="ok", capabilities_override={"supports_thinking": False})
    state = _state_with_messages(25)
    state.llm_client = client
    comp = LLMSummaryCompactor(
        keep_recent=10,
        resolve_cfg=lambda s: ModelConfig(model="x", thinking_enabled=True),
        has_override=lambda: True,
        client_getter=lambda s: s.llm_client,
    )
    await comp.compact(state)
    # Summary produced despite dropped thinking field
    assert state.messages[0]["content"] == "ok"
    # The drop event is available for observability
    events = [e for e in state.events if e["type"] == "llm_client.feature_unsupported"]
    assert any(e.get("data", {}).get("field") == "thinking_enabled" for e in events)
```

(The `MockClient` fixture from PR-4's `tests/fixtures/mock_clients.py`
supports a `capabilities_override` kwarg so tests can selectively turn
capability flags on/off without defining a new subclass per scenario.)

## 5. Risks

1. **Silent change of s02 default behavior.** Changing the
   default compactor from `SummaryCompactor` to
   `LLMSummaryCompactor` means existing pipelines without an
   override see no change (LLM path is gated), but a pipeline
   that explicitly sets an s02 override via
   `PipelineMutator.set_stage_model(2, cfg)` now summarizes.
   That is exactly the feature — documented loudly in cycle
   notes.

2. **Double-compaction.** If s02 runs on every iteration and
   the LLM summarization takes long enough for a second
   iteration to queue up, we could double-compact. Mitigated
   by recording `state.shared["s02.last_compacted_iteration"]`
   and skipping if already compacted this turn.

3. **Prompt fidelity.** The native reflection prompt is a
   literal copy of Geny's `_make_llm_reflect_callback` prompt
   (analysis 02 Site 1). If Geny changes their prompt, parity
   drift happens. Acceptable because PR-6 migrates Geny's
   default off the callback anyway — the native path is the
   one that matters going forward.

4. **JSON parse failure from the model.** Haiku-class models
   occasionally return trailing prose. The code strips ```
   fences but not other cruft. On parse failure we emit
   `memory.reflection.llm_failed` and return; no insight is
   lost because none was going to be saved anyway.

5. **Cross-vendor prompt behavior drift.** The same prompt
   under a non-Anthropic client (e.g. OpenAI for memory) may
   produce different JSON shape. Acceptance: memory stages
   use whatever provider the host chose; prompt engineering
   per vendor is out of scope. If a vendor produces
   consistently broken JSON, the operator picks a different
   model via `APIConfig.memory_model` + `APIConfig.provider`.

## 6. Acceptance criteria

- `LLMSummaryCompactor` exists and passes the five
  compaction tests (no-override, override, client-failure,
  below-threshold, capability-drop smoke).
- `GenyMemoryStrategy` accepts a `resolver` kwarg and runs a
  native path when callback is None, override is set, and
  client is present.
- Callback path still works (existing Geny integration tests
  continue to pass).
- No-override path preserves pre-cycle behavior exactly
  (same events emitted, same messages shape).
- `StageIntrospection.model_override_supported` is True for
  s02 context and s15 memory.
- Memory stages never import from
  `geny_executor.stages.s06_api` — only from
  `geny_executor.llm_client` and `geny_executor.core`.

## 7. File map

Files modified:

- `src/geny_executor/stages/s02_context/artifact/default/compactors.py`
  — add `LLMSummaryCompactor`; update `SummaryCompactor`
  docstring.
- `src/geny_executor/stages/s02_context/artifact/default/stage.py`
  — bind `LLMSummaryCompactor` by default (wiring for
  `resolve_cfg`, `has_override`, `client_getter`).
- `src/geny_executor/memory/strategy.py` — add
  `ReflectionResolver`, `_save_insights` helper, reworked
  `_reflect`.
- `src/geny_executor/stages/s15_memory/artifact/default/stage.py`
  — introspection flag flip to True (if the override is
  honored).
- `tests/stages/s02_context/test_llm_summary_compactor.py`
  — new.
- `tests/memory/test_strategy_native_reflect.py` — new.
- Update any `test_introspection.py` that pins the True/False
  matrix per stage.

Files **not** modified:

- s06_api (unchanged from PR-4; memory stages intentionally
  don't import from it).
- `core/pipeline.py`, `core/state.py`, `core/stage.py`,
  `llm_client/*.py` — all established in earlier PRs.
