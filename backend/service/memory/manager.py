"""
Session Memory Manager — unified facade.

Each session gets its own SessionMemoryManager tied to its
``storage_path``. The manager calls the executor's
``MemoryProvider`` directly through inline helper methods —
host-side STM / LTM adapter classes were retired in 1.21.0
(``ShortTermMemory``) and Sprint 3 step 2 (``LongTermMemory``).

It handles:
  - Unified search across STM + LTM + vector
  - Memory injection for prompts (build context string)
  - Memory flush before compaction (save durable facts)
  - Statistics
"""

from __future__ import annotations

import asyncio
import time

from datetime import datetime, timezone, timedelta
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

from service.utils.background import spawn_background
from service.memory.types import (
    CATEGORY_DESCRIPTIONS,
    MemoryEntry,
    MemoryFileInfo,
    MemoryIndex,
    MemorySearchResult,
    MemorySource,
    MemoryStats,
    VectorSearchResult,
)

logger = getLogger(__name__)

# Use configured timezone from GENY_TIMEZONE env var
from service.utils.utils import _configured_tz as _get_tz

# Maximum characters injected from memory into context.
DEFAULT_MAX_INJECT_CHARS = 8_000

# Maximum chars for truncated fields in LTM entries.
_LTM_INPUT_PREVIEW = 300
_LTM_OUTPUT_PREVIEW = 800
_LTM_TODO_RESULT_PREVIEW = 400

# Bound for `_stm_load_all` — same as the legacy `ShortTermMemory`
# adapter used. Keeps memory inspect tools from accidentally pulling
# the entire session history when a session has thousands of turns.
_RECENT_LARGE_N = 5000


def _content_to_text(content: Any) -> str:
    """Render `Turn.content` as a flat string. Mirrors what the
    retired `ShortTermMemory._content_to_text` helper produced."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif block.get("type") == "tool_use":
                    parts.append(f"[tool_use:{block.get('name', '?')}]")
                elif block.get("type") == "tool_result":
                    parts.append(f"[tool_result:{block.get('tool_use_id', '?')}]")
                else:
                    parts.append(str(block))
            else:
                parts.append(str(block))
        return "\n".join(p for p in parts if p)
    try:
        import json as _json

        return _json.dumps(content, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(content)


#: How a recorded execution ended: done, done with failed tool calls, or not.
OUTCOME_MARK = {"ok": "✅", "partial": "⚠️", "failed": "❌"}


def classify_outcome(
    success: bool, *, tool_calls: int = 0, tool_failures: int = 0, last_failed: bool = False
) -> str:
    """``partial`` when the turn finished but its tools did not: it ended on
    a failed call, or at least half of its calls failed. A failure the agent
    worked around (a missing file, then the right one) is not partial."""
    if not success:
        return "failed"
    if tool_failures and (last_failed or tool_failures * 2 >= max(1, tool_calls)):
        return "partial"
    return "ok"


def _outcome_of(success: bool, result_state: Dict[str, Any]) -> str:
    return classify_outcome(
        success,
        tool_calls=int(result_state.get("tool_calls") or 0),
        tool_failures=int(result_state.get("tool_failures") or 0),
        last_failed=bool(result_state.get("tool_last_failed")),
    )


class SessionMemoryManager:
    """Per-session memory facade.

    Usage::

        mgr = SessionMemoryManager(storage_path="/tmp/sessions/abc123")
        mgr.initialize()

        # Record conversation
        mgr.record_message("user", "Fix the login bug")
        mgr.record_message("assistant", "I'll look into auth.py...")

        # Save durable knowledge
        mgr.remember("The login bug was caused by expired JWT tokens.")

        # Search across all memory
        results = mgr.search("JWT token")

        # Build injection block for system prompt
        context = mgr.build_memory_context(query="JWT")
    """

    def __init__(
        self,
        storage_path: str,
        max_inject_chars: int = DEFAULT_MAX_INJECT_CHARS,
        *,
        session_id: str = "",
    ):
        """
        Args:
            storage_path: Session's root storage directory.
            max_inject_chars: Budget for memory injection into context.
            session_id: Logical session id used in archiver filenames
                (``conversations/<sid>__<bucket>.md``) and DB rows.
                Optional for back-compat — when omitted the archivers
                fall back to ``"unknown"`` slugs and the DB writes
                stay disabled until ``set_database`` provides one.
                Cycle 20260503_5 — this used to be ``None`` and only
                set later by ``set_database``, which meant non-DB
                sessions produced ``conversations/unknown__*.md``
                forever.
        """
        self._storage_path = storage_path
        self._max_inject_chars = max_inject_chars

        # STM + LTM both go through the executor `MemoryProvider`
        # directly — the legacy `ShortTermMemory` (retired 1.21.0)
        # and `LongTermMemory` (retired Sprint 3 step 2) adapters
        # are gone. Inline helpers on this class (``_stm_*`` /
        # ``_ltm_*``) wrap the async provider calls in
        # ``run_coro_sync`` so the rest of the manager keeps its
        # synchronous surface.
        self._memory_provider: Optional[Any] = None
        self._transcript_dir = Path(storage_path) / "transcripts"
        self._stm_jsonl = self._transcript_dir / "session.jsonl"
        self._stm_summary_path = self._transcript_dir / "summary.md"
        self._memory_dir = Path(storage_path) / "memory"
        self._ltm_main_file = self._memory_dir / "MEMORY.md"
        # Vector access goes through the provider directly via inline
        # ``_vmm_*`` helpers — no host-side ``VectorMemoryManager``
        # stored on the manager (Sprint 3 step 3 retired it from the
        # session manager). The adapter class itself stays in
        # ``service/memory/vector_memory.py`` for ``curated_knowledge``
        # which constructs its own per-user vector store; that wiring
        # is retired in step 3.5.

        # Structured memory layer (Obsidian-like).
        # The legacy ``MemoryIndexManager`` (Sprint 3 step 4) and
        # ``StructuredMemoryWriter`` (Sprint 3 step 5) adapters were
        # retired from the session manager. Index reads route through
        # ``provider.index()`` via ``_index_*`` helpers; note CRUD
        # routes through ``provider.notes()`` via ``_notes_*`` helpers.

        # Memory v2 — leaf source-of-truth writer (plan §1.5).
        # Auto-archives every record_message into
        # ``memory/conversations/<date>/<id>.md``. Lazy-built in
        # ``initialize()`` so callers that only construct the manager
        # without initialising it (rare; old tests) don't hit disk.
        from service.memory.conversation_archiver import ConversationArchiver  # local
        from service.memory.dm_archiver import DmArchiver
        from service.memory.compaction_archiver import CompactionArchiver
        # Cycle 20260503_6 — DailyJournalWriter retired. ``conversations/``
        # rollup files now carry every turn (with date_first/date_last
        # in frontmatter for chronological filtering), and the
        # standalone ``memory/<YYYY-MM-DD>.md`` headline index was
        # 100% redundant with the conversations sidebar entries.
        self._ConversationArchiver = ConversationArchiver
        self._DmArchiver = DmArchiver
        self._CompactionArchiver = CompactionArchiver
        self._conversation_archiver: Optional[ConversationArchiver] = None
        self._dm_archiver: Optional[DmArchiver] = None
        self._compaction_archiver: Optional[CompactionArchiver] = None

        self._initialized = False
        self._db_manager = None
        # Stored as Optional[str] for back-compat with code paths that
        # checked ``is None``. New construction defaults to "" via the
        # constructor kwarg so archiver filenames carry a real id.
        self._session_id: Optional[str] = session_id or None

    def set_memory_provider(self, provider) -> None:
        """Plug the executor `MemoryProvider` into every layer that
        speaks to it.

        Called by `AgentSession` immediately after the composite
        provider is built. Consumers:

        - `ShortTermMemory`: append / recent / search route through
          `provider.stm()` (GENY-1, path A migration). DB dual-write
          stays as analytics mirror; cosmetic `summary.md` stays as
          direct disk write.
        - `VectorMemoryManager`: vector retrieval + indexing route
          through `provider.vector()`.
        - `StructuredMemoryWriter`: write / update / delete / link /
          read / list route through `provider.notes()`.
        - `ConversationArchiver`: per-session rollup route through
          `provider.notes()` (single-level filename within
          `memory/conversations/`).
        - `CompactionArchiver`: compaction vault writes route
          through `provider.notes()`. The audit copy under
          `transcripts/compactions/` keeps its direct disk path.

        DM archiver intentionally stays on direct atomic-write —
        its `dms/<cp>/<date>.md` layout has a counterpart subdir
        which the executor's flat-category NotesHandle doesn't
        model.
        """
        # Cache the provider on the manager so the inline ``_stm_*`` /
        # ``_ltm_*`` helpers can route every operation through
        # ``provider.stm()`` / ``provider.ltm()`` / ``provider.notes()``.
        self._memory_provider = provider
        if self._compaction_archiver is not None:
            try:
                self._compaction_archiver.set_memory_provider(provider)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "set_memory_provider: compaction wiring skipped",
                    exc_info=True,
                )
        # DM archiver stays on direct atomic-write — its
        # `dms/<cp>/<date>.md` layout has a counterpart subdir which
        # the executor's flat-category NotesHandle doesn't model.
        if self._conversation_archiver is not None and hasattr(
            self._conversation_archiver, "set_memory_provider"
        ):
            try:
                self._conversation_archiver.set_memory_provider(provider)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "set_memory_provider: conversation archiver wiring skipped",
                    exc_info=True,
                )

    def set_database(self, db_manager, session_id: str) -> None:
        """Enable DB-backed persistence for LTM and STM.

        Args:
            db_manager: AppDatabaseManager instance.
            session_id: Session ID for DB queries.
        """
        self._db_manager = db_manager
        self._session_id = session_id
        # GENY-9 — STM/LTM/structured_writer no longer dual-write to
        # the DB analytics mirror; their writes route through
        # `provider.stm()` / `provider.ltm()` / `provider.notes()`
        # exclusively. The manager keeps `_db_manager` because
        # `compute_memory_stats` still aggregates from it for the
        # operator dashboards. Late `set_database` calls now only
        # refresh the archivers' `session_id` (legacy fix from cycle
        # 20260503_5 — archivers used to bind None at init time).
        for archiver_attr in (
            "_conversation_archiver",
            "_dm_archiver",
            "_compaction_archiver",
        ):
            archiver = getattr(self, archiver_attr, None)
            if archiver is None:
                continue
            try:
                archiver.set_session_id(session_id)
            except AttributeError:
                # Older archiver build without setter — leave it alone.
                pass
        logger.info("SessionMemoryManager: DB backend enabled for session %s", session_id)

    # NOTE: the ``long_term`` property was retired in Sprint 3 step 2
    # along with the ``LongTermMemory`` adapter. Callers go through
    # the manager's public LTM surface
    # (``remember`` / ``remember_dated`` / ``remember_topic`` / `search`).

    # NOTE: the ``short_term`` property was retired in 1.21.0 along with
    # the ``ShortTermMemory`` adapter. Callers that previously did
    # ``mgr.short_term.load_all()`` should call ``mgr.load_all_stm()``
    # (kept on the manager as the public read surface).

    # NOTE: the ``vector_memory`` property was retired in Sprint 3
    # step 3 along with the ``VectorMemoryManager`` field on the
    # manager. Inline ``_vector_*`` helpers route through
    # ``provider.vector()``.

    # NOTE: the ``index_manager`` property was retired in Sprint 3
    # step 4 along with the ``MemoryIndexManager`` field on the
    # manager. Inline ``_index_*`` helpers route through
    # ``provider.index()``; callers that previously did
    # ``mgr.index_manager.build_vault_map()`` should call
    # ``mgr.build_vault_map()``.

    # NOTE: the ``structured_writer`` property was retired in Sprint 3
    # step 5 along with the ``StructuredMemoryWriter`` field on the
    # manager. Inline ``_notes_*`` helpers route through
    # ``provider.notes()``; callers that previously reached for
    # ``mgr.structured_writer.X(...)`` should use the manager's
    # public ``write_note`` / ``update_note`` / ``delete_note`` /
    # ``read_note`` / ``list_notes`` / ``link_notes`` surface.

    @property
    def storage_path(self) -> str:
        return self._storage_path

    # ------------------------------------------------------------------
    # STM helpers (1.21.0 — provider direct, no host adapter)
    #
    # Each helper wraps the executor's async ``STMHandle`` in a sync
    # call via ``run_coro_sync`` so the rest of the manager keeps its
    # synchronous surface. Type conversion (Turn → MemoryEntry,
    # Turn → MemorySearchResult) happens inline.
    # ------------------------------------------------------------------

    async def _stm_append_message(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._memory_provider is None:
            return
        from geny_executor.memory.provider import Turn

        turn = Turn(
            role=role,
            content=content,
            timestamp=datetime.now(_get_tz()),
            metadata=dict(metadata) if metadata else {},
        )
        try:
            await self._memory_provider.stm().append(turn)
        except Exception:  # noqa: BLE001
            logger.warning(
                "manager._stm_append_message: provider.stm().append failed",
                exc_info=True,
            )

    async def _stm_append_event(
        self,
        event: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._memory_provider is None:
            return
        try:
            await self._memory_provider.stm().append_event(
                event, dict(data) if data else None
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "manager._stm_append_event: provider.stm().append_event failed",
                exc_info=True,
            )

    async def _stm_get_summary(self) -> Optional[str]:
        if self._memory_provider is None:
            return None
        try:
            text = await self._memory_provider.stm().read_summary()
        except Exception:  # noqa: BLE001
            logger.debug(
                "manager._stm_get_summary: provider.stm().read_summary failed",
                exc_info=True,
            )
            return None
        if not text:
            return None
        return text.strip() or None

    async def _stm_write_summary(self, body: str) -> None:
        if self._memory_provider is None:
            return
        try:
            await self._memory_provider.stm().write_summary(body)
        except Exception:  # noqa: BLE001
            logger.warning(
                "manager._stm_write_summary: provider.stm().write_summary failed",
                exc_info=True,
            )

    async def compact_now(self, *, evergreen: bool = False) -> Optional[str]:
        """Run the semantic memory rollup — the compressed view served first.

        Folds the prior rolling digest + recent raw turns into a fresh
        preservation-focused digest (geny-executor ``MemoryRollup``) and persists
        it to the summary slot the Stage-2 retriever injects at L1 (always-injected
        "압축본 선행"). When ``evergreen=True`` (a slower cadence, and at session
        close), also merges it into the durable L3 evergreen note (a pinned
        ``critical`` note — also always-injected + never compacted). The LLM is the
        offline memory model (``build_memory_llm``). Best-effort: returns the
        rolling digest or ``None``. Replaces the mechanical transcript summary.
        """
        if self._memory_provider is None:
            return None
        try:
            from geny_executor.memory import MemoryRollup
            from service.memory.memory_llm import build_memory_llm
        except Exception:  # noqa: BLE001 — executor too old / import issue
            logger.debug("compact_now: MemoryRollup unavailable", exc_info=True)
            return None

        llm = build_memory_llm()
        if llm is None:
            logger.debug("compact_now: no memory LLM configured — skipping")
            return None

        async def _summarize(instruction: str) -> str:
            return await llm.complete(instruction, purpose="memory.rollup")

        # Structured mode (executor >= 2.46.0): digests/evergreen are
        # schema-bound JSON rendered by code — a conversational reply is a
        # contract violation and leaves previous state untouched.
        structured_kwargs = {}
        if hasattr(llm, "complete_structured"):
            async def _summarize_structured(instruction: str, schema: dict):
                return await llm.complete_structured(
                    instruction, schema, purpose="memory.rollup",
                )

            structured_kwargs["complete_structured"] = _summarize_structured

        # Fact Ledger extraction (executor >= 2.46.0) — runs FIRST so a
        # durable fact stated moments ago is already in the ledger before
        # the narrative tiers compress. Best-effort.
        try:
            from geny_executor.memory import FactExtraction

            if structured_kwargs:
                fact_report = await FactExtraction(
                    self._memory_provider,
                    complete_structured=structured_kwargs["complete_structured"],
                ).run()
                if fact_report.ran and fact_report.changes:
                    self._fact_zero_runs = 0
                    logger.info(
                        "compact_now: fact ledger updated (%d change(s), "
                        "%d active)",
                        fact_report.changes, fact_report.active_facts,
                    )
                elif fact_report.ran:
                    # Starvation watch: extraction that "succeeds" with zero
                    # accrued facts forever is how the ledger silently sat
                    # empty in the field while the persona re-pinned the same
                    # identity by hand. Surface the pattern.
                    self._fact_zero_runs = getattr(self, "_fact_zero_runs", 0) + 1
                    if self._fact_zero_runs >= 5 and not fact_report.active_facts:
                        logger.warning(
                            "compact_now: fact extraction ran %d times with an "
                            "EMPTY ledger — extraction may be ineffective for "
                            "this dialogue source",
                            self._fact_zero_runs,
                        )
        except ImportError:
            pass  # older executor — narrative tiers only
        except Exception:  # noqa: BLE001 — facts are best-effort
            logger.warning("compact_now: fact extraction failed", exc_info=True)

        try:
            rollup = MemoryRollup(
                self._memory_provider, summarize=_summarize, **structured_kwargs,
            )
            digest = await rollup.summarize_segment()
            if digest:
                logger.info(
                    "compact_now: rolling digest written (%d chars)", len(digest)
                )
            # L2 daily digest — idempotent per day (overwrites as the day
            # progresses), giving a date-navigable series of compressed digests.
            try:
                day_key = datetime.now(_get_tz()).strftime("%Y-%m-%d")
                if hasattr(rollup, "rollup_daily"):
                    await rollup.rollup_daily(day=day_key)
            except Exception:  # noqa: BLE001 — daily is best-effort
                logger.debug("compact_now: daily rollup failed", exc_info=True)
            if evergreen:
                try:
                    ever = await rollup.rollup_evergreen()
                    if ever:
                        logger.info(
                            "compact_now: evergreen updated (%d chars)", len(ever)
                        )
                except Exception:  # noqa: BLE001 — evergreen is best-effort
                    logger.warning("compact_now: evergreen failed", exc_info=True)
            return digest
        except Exception:  # noqa: BLE001 — never fatal
            logger.warning("compact_now: rollup failed", exc_info=True)
            return None

    async def _stm_get_recent(self, n: int) -> List[MemoryEntry]:
        if self._memory_provider is None or n <= 0:
            return []
        try:
            turns = await self._memory_provider.stm().recent(n=n)
        except Exception:  # noqa: BLE001
            logger.debug(
                "manager._stm_get_recent: provider.stm().recent failed",
                exc_info=True,
            )
            return []
        return [self._turn_to_entry(turn, idx=i) for i, turn in enumerate(turns)]

    async def _stm_load_all(self) -> List[MemoryEntry]:
        # Bounded large-N read — same shape `ShortTermMemory.load_all`
        # used to return.
        return await self._stm_get_recent(_RECENT_LARGE_N)

    async def _stm_search(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[MemorySearchResult]:
        if not query or not query.strip() or self._memory_provider is None:
            return []
        try:
            turns = await self._memory_provider.stm().search(query, limit=max_results)
        except Exception:  # noqa: BLE001
            logger.debug(
                "manager._stm_search: provider.stm().search failed",
                exc_info=True,
            )
            return []
        results: List[MemorySearchResult] = []
        for turn in turns:
            entry = self._turn_to_entry(turn)
            content = entry.content
            snippet = content[:240] + "..." if len(content) > 240 else content
            results.append(
                MemorySearchResult(
                    entry=entry,
                    score=1.0,
                    snippet=snippet,
                    match_type="keyword",
                )
            )
        return results

    def _turn_to_entry(self, turn: Any, *, idx: int = 0) -> MemoryEntry:
        """Convert an executor `Turn` into the host-side `MemoryEntry`."""
        content_text = _content_to_text(turn.content)
        role = getattr(turn, "role", "user") or "user"
        try:
            transcript_rel = str(self._stm_jsonl.relative_to(self._storage_path))
        except ValueError:
            transcript_rel = "transcripts/session.jsonl"
        return MemoryEntry(
            source=MemorySource.SHORT_TERM,
            content=f"[{role}] {content_text}",
            timestamp=getattr(turn, "timestamp", None),
            filename=transcript_rel,
            line_start=idx + 1,
            line_end=idx + 1,
            metadata={"role": role, **(getattr(turn, "metadata", None) or {})},
        )

    # Public read surface that legacy callers
    # (``memory_inspect_tools._stm_load_all``) can reach for. Keeps
    # the post-1.21.0 surface deliberately small — no parallel
    # ``ShortTermMemory`` object to expose. Sync wrappers; async
    # callers should use ``aload_all_stm`` / ``aget_recent_stm``.
    def load_all_stm(self) -> List[MemoryEntry]:
        from service.memory.sync_async_bridge import run_coro_sync
        return run_coro_sync(self._stm_load_all())

    def get_recent_stm(self, n: int = 20) -> List[MemoryEntry]:
        from service.memory.sync_async_bridge import run_coro_sync
        return run_coro_sync(self._stm_get_recent(n))

    async def aload_all_stm(self) -> List[MemoryEntry]:
        return await self._stm_load_all()

    async def aget_recent_stm(self, n: int = 20) -> List[MemoryEntry]:
        return await self._stm_get_recent(n)

    # ------------------------------------------------------------------
    # LTM helpers (Sprint 3 step 2 — provider direct, no host adapter)
    # ------------------------------------------------------------------

    async def _ltm_append(self, text: str, *, heading: Optional[str] = None) -> None:
        if self._memory_provider is None:
            return
        try:
            await self._memory_provider.ltm().append(text, heading=heading)
        except Exception:  # noqa: BLE001
            logger.warning(
                "manager._ltm_append: provider.ltm().append failed",
                exc_info=True,
            )

    async def _ltm_write_topic(self, topic: str, text: str) -> Optional[Path]:
        if self._memory_provider is None:
            return None
        try:
            ref = await self._memory_provider.ltm().write_topic(topic, text)
        except Exception:  # noqa: BLE001
            logger.warning(
                "manager._ltm_write_topic: provider.ltm().write_topic failed",
                exc_info=True,
            )
            return None
        if ref and ref.filename:
            return self._memory_dir / ref.filename
        return None

    async def _ltm_write_execution(
        self, entry: str, *, date: Optional[datetime] = None
    ) -> Optional[str]:
        """Append an execution-summary line to ``memory/executions/<YYYY-MM-DD>.md``.

        Routed through ``NotesHandle`` (category="executions") — new
        file → ``notes.write``; existing → ``notes.update(append_body=...)``.
        Returns ``"executions/<file>.md"`` on success.
        """
        if self._memory_provider is None:
            return None
        from geny_executor.memory.provider import (
            Importance,
            NoteDraft,
            NotePatch,
            Scope,
        )

        ts = date or datetime.now(_get_tz())
        day = ts.date().isoformat()
        bare_filename = f"{day}.md"
        notes = self._memory_provider.notes()
        try:
            existing = await notes.read(bare_filename)
        except Exception:  # noqa: BLE001
            logger.debug(
                "manager._ltm_write_execution: provider read failed",
                exc_info=True,
            )
            existing = None
        try:
            if existing is None:
                draft = NoteDraft(
                    title=f"Executions {day}",
                    body=entry.rstrip() + "\n",
                    category="executions",
                    tags=["execution"],
                    importance=Importance.MEDIUM,
                    scope=Scope.SESSION,
                    filename=bare_filename,
                    metadata={
                        "geny.kind": "executions_journal",
                        "geny.day": day,
                    },
                )
                await notes.write(draft)
            else:
                patch = NotePatch(append_body=entry.rstrip())
                await notes.update(bare_filename, patch)
        except Exception:  # noqa: BLE001
            logger.warning(
                "manager._ltm_write_execution: provider write/update failed",
                exc_info=True,
            )
            return None
        return f"executions/{bare_filename}"

    async def _ltm_load_main(self) -> Optional[MemoryEntry]:
        if self._memory_provider is None:
            return None
        try:
            text = await self._memory_provider.ltm().read_main()
        except Exception:  # noqa: BLE001
            logger.debug(
                "manager._ltm_load_main: provider read failed",
                exc_info=True,
            )
            return None
        if not text:
            return None
        return MemoryEntry(
            source=MemorySource.LONG_TERM,
            content=text,
            timestamp=None,
            filename="MEMORY.md",
            metadata={"category": "root"},
        )

    async def _ltm_load_pinned(self, *, max_chars: int = 3000) -> Optional[MemoryEntry]:
        if self._memory_provider is None:
            return None
        try:
            body = await self._memory_provider.notes().load_pinned(
                category="critical",
                max_chars=max_chars,
            )
        except Exception:  # noqa: BLE001
            logger.debug(
                "manager._ltm_load_pinned: provider load_pinned failed",
                exc_info=True,
            )
            return None
        if not body:
            return None
        return MemoryEntry(
            source=MemorySource.LONG_TERM,
            content=body,
            timestamp=None,
            filename="critical/",
            category="critical",
            tags=["pinned"],
            importance="critical",
            metadata={"pinned": True},
        )

    async def _ltm_search(
        self, query: str, *, max_results: int = 10
    ) -> List[MemorySearchResult]:
        if not query.strip() or self._memory_provider is None:
            return []
        try:
            chunks = await self._memory_provider.ltm().search(query, limit=max_results)
        except Exception:  # noqa: BLE001
            logger.debug(
                "manager._ltm_search: provider.ltm().search failed",
                exc_info=True,
            )
            return []
        results: List[MemorySearchResult] = []
        for chunk in chunks:
            entry = MemoryEntry(
                source=MemorySource.LONG_TERM,
                content=chunk.content,
                timestamp=None,
                filename=chunk.key,
                metadata=dict(chunk.metadata or {}),
            )
            snippet = (
                chunk.content[:240] + "..." if len(chunk.content) > 240 else chunk.content
            )
            results.append(
                MemorySearchResult(
                    entry=entry,
                    score=float(chunk.relevance_score or 0.0),
                    snippet=snippet,
                    match_type=str(chunk.source or "ltm"),
                )
            )
        return results

    # ------------------------------------------------------------------
    # Vector helpers (Sprint 3 step 3 — provider direct)
    # ------------------------------------------------------------------

    @property
    def _vector_enabled(self) -> bool:
        return (
            self._memory_provider is not None
            and self._memory_provider.vector() is not None
        )

    async def _vector_initialize_and_index(self) -> bool:
        """Bring the vector index level with the notes on disk — INCREMENTALLY.

        New writes are auto-vectored by the executor's
        ``_FilesystemNotesStore.attach_vector_indexer``, so on a healthy
        session this method has nothing to do. It exists for the cases where
        the two drifted: notes written while the index was unavailable, notes
        edited outside the app, and notes DELETED — which the write path has
        no hook for at all.

        It used to answer "did anything drift?" by re-reading every note and
        offering all of them to the engine. On the production vault that was
        5,507 bodies read and 5,507 engine calls, each taking the engine lock
        and re-deriving a digest, to discover that nothing had changed.
        Deletions it could not discover at all — a scan over the files that
        exist never visits the ones that don't, which is why 36% of that
        index was nodes whose notes were long gone.

        Now it diffs metadata both sides already hold: the index's manifest
        (node id → indexed-at, digest) against the notes' own timestamps.
        Bodies are read only for what the diff says changed. Measured on that
        vault: 56 ms → 6 ms with nothing to do, and the 3,210 orphans became
        visible for the first time.
        """
        if not self._vector_enabled or self._memory_provider is None:
            return False
        notes_handle = self._memory_provider.notes()
        vector_handle = self._memory_provider.vector()
        # Older/alternate vector stores don't offer the manifest. Fall back to
        # the full offer rather than skipping reconciliation entirely — slow
        # is recoverable, a silently un-indexed vault is not.
        if not hasattr(vector_handle, "manifest"):
            return await self._vector_full_reindex(notes_handle, vector_handle)
        try:
            # Before diffing: if the WRITE contract moved (this handle now
            # sends the engine metadata it used to drop), blank the digests
            # once so the diff below sees the vault as stale and re-offers
            # it with the full row. Without this the richer write path would
            # only ever reach notes edited after the deploy.
            upgrade = getattr(vector_handle, "ensure_write_contract", None)
            if upgrade is not None:
                invalidated = await upgrade()
                if invalidated:
                    logger.info(
                        "memory: write contract advanced — %d rows queued for "
                        "re-index with full note metadata", invalidated,
                    )
            manifest = await vector_handle.manifest()
            metas = await notes_handle.list()

            on_disk: set = set()
            stale: List = []
            for meta in metas:
                node_id = vector_handle.node_id_for(meta.ref)
                on_disk.add(node_id)
                indexed_at, digest = manifest.get(node_id, (None, ""))
                if indexed_at is None:
                    stale.append(meta)          # never indexed
                    continue
                if not digest:
                    # "indexed, derived state unknown" — the engine says its
                    # tokenizer or embedding geometry moved, so these rows
                    # were derived a way that no longer matches how queries
                    # are analysed. Timestamps say nothing about that.
                    stale.append(meta)
                    continue
                # The index records when IT wrote, which is always at or after
                # the note's own timestamp. So a note whose timestamp has moved
                # past that has been edited since. Equality is not drift.
                updated_at = getattr(meta, "updated_at", None)
                ts = getattr(updated_at, "timestamp", None)
                # A DISAGREEMENT in either direction, not just "newer". The
                # index used to record its own write time, so after a full
                # re-index every row reads as more recent than its note and
                # "newer" would never fire — the dates would stay wrong
                # forever. Correcting one costs a batched touch, not a
                # re-index, because the content digest still matches.
                if ts is not None and abs(ts() - float(indexed_at)) > 1.0:
                    stale.append(meta)

            orphans = [n for n in manifest if n not in on_disk]

            # A tokenizer or embedding-geometry change invalidates EVERY
            # note at once, so `stale` is occasionally the whole vault. The
            # warm-up that calls this is bounded at 90s: applying thousands
            # inline means it is cancelled every boot, memory never reports
            # ready, and the session runs blind. Do a bounded slice here so
            # the common case (a handful of notes) still finishes before the
            # gate, and hand the rest to a background task that runs with
            # the session already live.
            # A stale set larger than the inline budget is not drift — it is
            # a conversion (a tokenizer or geometry change invalidating the
            # whole vault). Doing ANY of it inline just gets the warm-up
            # cancelled at its 90s budget before the first chunk commits, so
            # the conversion never starts. Hand the lot to the background,
            # where it has no deadline, and let the warm-up finish now.
            if len(stale) > self._RECONCILE_INLINE:
                head, tail = [], stale
            else:
                head, tail = stale, []
            items = await self._read_bodies(notes_handle, head)
            if items:
                await vector_handle.index_batch(items)
            if orphans and hasattr(vector_handle, "remove_many"):
                await vector_handle.remove_many(orphans)
            if tail:
                logger.info(
                    "memory reconcile: %d more notes queued in the background",
                    len(tail),
                )
                spawn_background(
                    self._reconcile_tail(notes_handle, vector_handle, tail),
                    name=f"memory.reconcile-tail:{len(tail)}",
                    key=f"memory.reconcile:{id(self)}",
                )
            if items or orphans:
                logger.info(
                    "memory reconcile: %d indexed, %d orphans reaped "
                    "(%d notes on disk, %d already indexed)",
                    len(items), len(orphans), len(on_disk), len(manifest),
                )
        except Exception:  # noqa: BLE001
            logger.warning(
                "manager._vector_initialize_and_index failed",
                exc_info=True,
            )
            return False
        return True

    #: Pause between background re-index chunks — see `_reconcile_tail`.
    _CHUNK_PAUSE_S = 0.5

    #: How many stale notes the BOOT path re-indexes before handing over. Big
    #: enough that an ordinary drift (a few edits) finishes inline; small
    #: enough that a full-vault invalidation cannot blow the warm-up budget.
    _RECONCILE_INLINE = 200

    async def _read_bodies(self, notes_handle, metas) -> List:
        """(ref, body, note_timestamp) for each readable note.

        The timestamp is the NOTE's, not the moment we happen to index it —
        otherwise a full re-index stamps the whole vault with one date and
        anything that groups by day (the browser's day buckets) sees a
        single bucket.
        """
        items: List = []
        for meta in metas:
            note = await notes_handle.read(meta.ref.filename)
            if note is None or not note.body:
                continue
            stamp = getattr(meta, "updated_at", None)
            ts = stamp.timestamp() if hasattr(stamp, "timestamp") else None
            # The NOTE rides along, not just its body: title, tags and
            # importance are what four of the index's fourteen ranking
            # features are computed from, and dropping them here is what
            # left every node in production at importance=1.0, pinned=0,
            # with no tags and no title.
            items.append((note.ref, note.body, ts, note))
        return items

    async def _reconcile_tail(self, notes_handle, vector_handle, metas) -> None:
        """Finish a large re-index with the session already answering.

        Chunked and yielding, for the same reason the retention sweep is: a
        delete or an index is a write, and holding the memory engine for the
        length of a backlog is the failure this whole area keeps producing.
        """
        done = 0
        try:
            for start in range(0, len(metas), 200):
                chunk = metas[start:start + 200]
                items = await self._read_bodies(notes_handle, chunk)
                if items:
                    done += await vector_handle.index_batch(items)
                # Breathe between chunks. This runs while the session is
                # answering, and a full-vault rebuild is thousands of writes
                # — enough to make everything else feel wedged if it is
                # allowed to run flat out.
                await asyncio.sleep(self._CHUNK_PAUSE_S)
            logger.info("memory reconcile: background pass indexed %d", done)
        except Exception:  # noqa: BLE001 — the session is already live
            logger.warning(
                "memory reconcile: background pass stopped after %d", done,
                exc_info=True,
            )

    async def prune_expired_notes(self) -> int:
        """Delete autonomous notes that have aged out. Returns how many.

        Goes through the notes store rather than unlinking files, so the
        vector index and the sidecars follow. Deliberately capped per call:
        a vault that has never been pruned presents thousands at once, and a
        delete is a write — holding the memory engine for an unbounded
        stretch is the exact failure the rest of this work removes.

        Never raises: retention is housekeeping, and a session must not fail
        to start because a sweep hit a bad file.
        """
        if self._memory_provider is None:
            return 0
        from service.memory import note_retention

        days = note_retention.retention_days()
        keep = note_retention.max_per_category()
        if days <= 0 and keep <= 0:
            return 0
        notes_handle = self._memory_provider.notes()
        try:
            metas = await notes_handle.list()
            expired = note_retention.select_expired(
                metas,
                now=datetime.now(timezone.utc),
                days=days,
                limit=note_retention.max_per_sweep(),
                keep_per_category=note_retention.max_per_category(),
            )
            removed = 0
            deadline = time.monotonic() + note_retention.max_seconds()
            for item in expired:
                try:
                    if await notes_handle.delete(item.filename):
                        removed += 1
                except Exception:  # noqa: BLE001 — one bad file, not the sweep
                    logger.debug(
                        "note retention: %s could not be deleted",
                        item.filename, exc_info=True,
                    )
                # Each delete is a write against the notes store AND the
                # index. Yield between them so a turn asking for either is
                # not queued behind the whole backlog, and stop on the clock
                # rather than the count — the next sweep resumes.
                await asyncio.sleep(0)
                if time.monotonic() > deadline:
                    logger.info(
                        "note retention: stopping at %d/%d (time budget)",
                        removed, len(expired),
                    )
                    break
            if removed:
                logger.info(
                    "note retention: %d autonomous notes older than %dd "
                    "removed (%d candidates)",
                    removed, days, len(expired),
                )
            return removed
        except Exception:  # noqa: BLE001
            logger.warning("note retention sweep failed", exc_info=True)
            return 0

    async def _vector_full_reindex(self, notes_handle, vector_handle) -> bool:
        """The pre-incremental path, kept for stores without a manifest."""
        try:
            metas = await notes_handle.list()
            items: List = []
            for m in metas:
                note = await notes_handle.read(m.ref.filename)
                if note is None or not note.body:
                    continue
                items.append((note.ref, note.body))
            if items:
                await vector_handle.index_batch(items)
        except Exception:  # noqa: BLE001
            logger.warning("manager._vector_full_reindex failed", exc_info=True)
            return False
        return True

    async def _vector_index_text(self, text: str, source_filename: str) -> int:
        if not self._vector_enabled or self._memory_provider is None or not text:
            return 0
        from geny_executor.memory.provider import NoteRef, Scope

        ref = NoteRef(
            filename=source_filename,
            scope=Scope.SESSION,
            backend="filesystem",
        )
        try:
            return await self._memory_provider.vector().index(ref, text)
        except Exception:  # noqa: BLE001
            logger.warning(
                "manager._vector_index_text failed (source=%s)",
                source_filename, exc_info=True,
            )
            return 0

    async def _vector_search(
        self, query: str, *, top_k: int = 6
    ) -> List["VectorSearchResult"]:
        if not self._vector_enabled or self._memory_provider is None or not query:
            return []
        try:
            chunks = await self._memory_provider.vector().search(query, top_k=top_k)
        except Exception:  # noqa: BLE001
            logger.warning("manager._vector_search failed", exc_info=True)
            return []
        out: List[VectorSearchResult] = []
        for chunk in chunks:
            meta = dict(chunk.metadata or {})
            out.append(
                VectorSearchResult(
                    text=chunk.content,
                    source_file=chunk.key,
                    score=float(chunk.relevance_score),
                    chunk_index=int(meta.get("chunk_index", 0)),
                    metadata=meta,
                )
            )
        return out

    @staticmethod
    def _vector_build_context(
        results: List["VectorSearchResult"],
        *,
        max_chars: int = 5000,
    ) -> str:
        """Render vector hits as the XML block the prompt builder
        injects (was ``VectorMemoryManager.build_vector_context``)."""
        if not results:
            return ""
        parts: List[str] = []
        total = 0
        for r in results:
            block = (
                f'<vector-memory source="{r.source_file}" '
                f'score="{r.score:.3f}" chunk="{r.chunk_index}">\n'
                f"{r.text}\n"
                f"</vector-memory>"
            )
            if total + len(block) > max_chars and parts:
                break
            parts.append(block)
            total += len(block)
        return "\n\n".join(parts)

    def _ltm_load_all(self) -> List[MemoryEntry]:
        """Load every LTM markdown file. Used by compaction.

        Reads ``memory/`` directly since the executor's `LTMHandle`
        doesn't expose a dump-everything call (out of scope for the
        protocol) — and the on-disk layout is shared with the executor.
        """
        entries: List[MemoryEntry] = []
        if not self._memory_dir.exists():
            return entries
        for path in sorted(self._memory_dir.rglob("*.md")):
            if path.name in ("_index.json", "_vault_map.json"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if not text.strip():
                continue
            try:
                rel = str(path.relative_to(self._memory_dir))
            except ValueError:
                rel = path.name
            entries.append(
                MemoryEntry(
                    source=MemorySource.LONG_TERM,
                    content=text,
                    timestamp=None,
                    filename=rel,
                    metadata={"path": str(path)},
                )
            )
        return entries

    # ------------------------------------------------------------------
    # Index helpers (Sprint 3 step 4 — provider direct, no host adapter)
    #
    # ``MemoryIndexManager`` was retired; index reads route through
    # ``provider.index()`` directly. Helpers are async-native; sync
    # public methods (``get_memory_index``, etc.) wrap with one
    # ``run_coro_sync`` per call. Snapshot payloads are rehydrated
    # into ``MemoryIndex`` / ``MemoryFileInfo`` so callers (memory API,
    # opsidian routes, memory_inspect tools) keep their existing shape.
    # ------------------------------------------------------------------

    async def _index_snapshot(self) -> MemoryIndex:
        """Lazy snapshot of the executor's IndexHandle, merged with a
        host-side scan of ``memory/dms/`` (the executor's flat
        ``glob("*.md")`` cannot see the 2-level ``dms/<cp>/<date>.md``
        layout, so we splice those rows in here).

        Returns an empty `MemoryIndex` when no provider is attached.
        """
        if self._memory_provider is None:
            return MemoryIndex()
        from service.memory.note_utils import aget_index_snapshot_with_dms

        try:
            payload = await aget_index_snapshot_with_dms(
                self._memory_provider, self._memory_dir,
            )
        except Exception:  # noqa: BLE001
            logger.debug("manager._index_snapshot: snapshot failed", exc_info=True)
            return MemoryIndex()

        files: Dict[str, MemoryFileInfo] = {}
        for fname, entry in (payload.get("files") or {}).items():
            files[fname] = MemoryFileInfo.from_dict(entry)
        tag_map: Dict[str, List[str]] = {
            tag: list(names) for tag, names in (payload.get("tag_map") or {}).items()
        }
        link_graph: Dict[str, List[str]] = {
            src: list(targets)
            for src, targets in (payload.get("link_graph") or {}).items()
        }
        return MemoryIndex(
            files=files,
            tag_map=tag_map,
            link_graph=link_graph,
            last_rebuilt=str(payload.get("last_rebuilt", "")),
            total_chars=int(payload.get("total_chars", 0) or 0),
            total_files=int(payload.get("total_files", len(files)) or len(files)),
        )

    async def _index_rebuild(self) -> int:
        """Force a fresh index rebuild on the executor side.
        Returns the post-rebuild total_files count (0 if no provider).
        """
        if self._memory_provider is None:
            return 0
        try:
            await self._memory_provider.index().rebuild()
        except Exception:  # noqa: BLE001
            logger.debug("manager._index_rebuild: provider rebuild failed", exc_info=True)
        snapshot = await self._index_snapshot()
        return snapshot.total_files

    async def _index_build_vault_map(self) -> Dict[str, Any]:
        """Build the vault map payload (categories, top tags, recently
        modified, MEMORY.md preview). Geny's category descriptions are
        injected so the executor's render matches the legacy
        operator-prompt layout. Returns an empty payload when the
        provider isn't attached.
        """
        if self._memory_provider is None:
            return {
                "categories": {},
                "top_tags": [],
                "recently_modified": [],
                "memory_md_preview": "",
                "total_files": 0,
                "generated_at": datetime.now(_get_tz()).isoformat(),
            }
        try:
            return await self._memory_provider.index().build_vault_map(
                category_descriptions=CATEGORY_DESCRIPTIONS,
            )
        except Exception:  # noqa: BLE001
            logger.debug(
                "manager._index_build_vault_map: provider call failed",
                exc_info=True,
            )
            return {
                "categories": {},
                "top_tags": [],
                "recently_modified": [],
                "memory_md_preview": "",
                "total_files": 0,
                "generated_at": datetime.now(_get_tz()).isoformat(),
            }

    def build_vault_map(self) -> Dict[str, Any]:
        """Public sync surface for the vault map render.

        Replaces the retired ``mgr.index_manager.build_vault_map()``
        call site. Memory tools (`memory_categories`) and any other
        operator-facing surface that previously reached for the index
        manager should call this method instead. Async callers should
        use :meth:`abuild_vault_map`.
        """
        from service.memory.sync_async_bridge import run_coro_sync
        return run_coro_sync(self._index_build_vault_map())

    async def abuild_vault_map(self) -> Dict[str, Any]:
        return await self._index_build_vault_map()

    # ------------------------------------------------------------------
    # Notes helpers (Sprint 3 step 5 — provider direct, no host adapter)
    #
    # ``StructuredMemoryWriter`` was retired from the session manager;
    # write/update/delete/read/list/link route through
    # ``provider.notes()`` directly. The writer module stays alive as a
    # multi-tenant helper for ``GlobalMemoryManager`` /
    # ``CuratedKnowledgeManager`` / ``UserOpsidianManager``, which all
    # share the same Geny-shape (slug + frontmatter passthrough +
    # backlink propagation) but live outside the session lifecycle.
    # ------------------------------------------------------------------

    async def _notes_write(
        self,
        *,
        title: str,
        content: str,
        category: str,
        tags: Optional[List[str]],
        importance: str,
        source: str,
        links_to: Optional[List[str]],
        filename_override: Optional[str] = None,
    ) -> Optional[str]:
        if self._memory_provider is None:
            return None
        from geny_executor.memory.provider import (
            Importance as _ExecutorImportance,
            NoteDraft,
            Scope,
        )
        from service.memory.note_utils import (
            VALID_CATEGORIES,
            _slugify,
            extract_wikilinks,
            apropagate_linked_from,
        )

        cat = category if category in VALID_CATEGORIES else "topics"
        tag_list = [t.lower().strip() for t in (tags or []) if t.strip()]
        auto_links = extract_wikilinks(content)
        all_links = list(set(auto_links + (links_to or [])))

        try:
            importance_enum = _ExecutorImportance(importance)
        except ValueError:
            importance_enum = _ExecutorImportance.MEDIUM

        if filename_override:
            bare_filename = Path(filename_override).name
        else:
            slug = _slugify(title)
            bare_filename = f"{slug}.md"
            cat_dir = self._memory_dir if cat == "root" else self._memory_dir / cat
            candidate = cat_dir / bare_filename
            if candidate.exists():
                counter = 1
                while (cat_dir / f"{slug}-{counter}.md").exists():
                    counter += 1
                bare_filename = f"{slug}-{counter}.md"

        passthrough: Dict[str, Any] = {
            "aliases": [],
            "source": source,
            "session_id": self._session_id or "",
            "linked_from": [],
            "links_to": list(all_links),
        }
        draft = NoteDraft(
            title=title,
            body=content,
            category=cat,
            tags=list(tag_list),
            importance=importance_enum,
            scope=Scope.SESSION,
            filename=bare_filename,
            frontmatter=passthrough,
        )
        try:
            meta = await self._memory_provider.notes().write(draft)
        except Exception:  # noqa: BLE001
            logger.warning(
                "manager._notes_write: provider write failed", exc_info=True,
            )
            return None
        bare_returned = meta.ref.filename or bare_filename
        relative_path = (
            bare_returned if cat == "root" else f"{cat}/{bare_returned}"
        )

        try:
            from service.memory.event_emitter import emit_memory_event

            emit_memory_event(
                self._session_id or "",
                event_type="note_written",
                source="Memory",
                layer="notes",
                category=cat,
                importance=importance,
                path=relative_path,
                chars=len(content),
                message=(
                    f"note_written: {relative_path} "
                    f"({len(content)} chars, importance={importance})"
                ),
                extra={"tags": list(tag_list)} if tag_list else None,
            )
        except Exception:  # noqa: BLE001
            logger.debug(
                "manager._notes_write: memory_event emit skipped", exc_info=True,
            )

        try:
            await apropagate_linked_from(self._memory_provider, relative_path, all_links)
        except Exception:  # noqa: BLE001
            logger.debug(
                "manager._notes_write: linked_from propagation failed",
                exc_info=True,
            )

        logger.info(
            "manager._notes_write: created %s (%d chars, %d tags)",
            relative_path, len(content), len(tag_list),
        )
        return relative_path

    async def _notes_update(
        self,
        filename: str,
        *,
        body: Optional[str] = None,
        tags: Optional[List[str]] = None,
        importance: Optional[str] = None,
        category: Optional[str] = None,
        append: bool = False,
    ) -> bool:
        if self._memory_provider is None:
            return False
        from geny_executor.memory.provider import (
            Importance as _ExecutorImportance,
            NotePatch,
        )

        bare = Path(filename).name
        notes = self._memory_provider.notes()
        try:
            existing = await notes.read(bare)
        except Exception:  # noqa: BLE001
            logger.warning(
                "manager._notes_update: read failed for %s", filename,
                exc_info=True,
            )
            return False
        if existing is None:
            logger.warning("manager._notes_update: file not found: %s", filename)
            return False

        merged_tags: Optional[List[str]] = None
        if tags:
            merged = set(existing.tags or [])
            merged.update(t.lower().strip() for t in tags if t.strip())
            merged_tags = sorted(merged)

        importance_enum = None
        if importance:
            try:
                importance_enum = _ExecutorImportance(importance)
            except ValueError:
                importance_enum = None

        body_replace = body if (body is not None and not append) else None
        body_append = body if (body is not None and append) else None

        patch = NotePatch(
            body=body_replace,
            append_body=body_append,
            tags=merged_tags,
            importance=importance_enum,
            category=category,
        )
        try:
            await notes.update(bare, patch)
        except KeyError:
            logger.warning("manager._notes_update: provider missing %s", filename)
            return False
        except Exception:  # noqa: BLE001
            logger.warning(
                "manager._notes_update: provider write failed for %s", filename,
                exc_info=True,
            )
            return False
        logger.debug("manager._notes_update: updated %s (via provider)", filename)
        return True

    async def _notes_delete(self, filename: str) -> bool:
        if self._memory_provider is None:
            return False
        bare = Path(filename).name
        try:
            ok = await self._memory_provider.notes().delete(bare)
        except Exception:  # noqa: BLE001
            logger.warning(
                "manager._notes_delete: provider delete failed for %s", filename,
                exc_info=True,
            )
            return False
        if not ok:
            return False
        logger.info("manager._notes_delete: removed %s (via provider)", filename)
        return True

    async def _notes_read(self, filename: str) -> Optional[Dict[str, Any]]:
        if self._memory_provider is None:
            return None
        bare = Path(filename).name
        try:
            note = await self._memory_provider.notes().read(bare)
        except Exception:  # noqa: BLE001
            logger.debug(
                "manager._notes_read(%s): provider read failed", filename,
                exc_info=True,
            )
            return None
        if note is None:
            return None
        metadata = {
            "title": note.title,
            "tags": list(note.tags),
            "category": note.category,
            "importance": note.importance.value,
            "links_to": list(note.links_out),
            "linked_from": list(note.links_in),
            **(note.frontmatter or {}),
        }
        return {
            "filename": filename,
            "title": note.title,
            "metadata": metadata,
            "body": note.body,
            "raw": "",
            "links_to": list(note.links_out),
            "linked_from": list(note.links_in),
        }

    async def _notes_list(
        self,
        *,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        importance: Optional[str] = None,
    ) -> List[MemoryFileInfo]:
        if self._memory_provider is None:
            return []
        from geny_executor.memory.provider import Importance as _ExecutorImportance

        importance_filter = None
        if importance:
            try:
                importance_filter = _ExecutorImportance(importance)
            except ValueError:
                importance_filter = None
        try:
            metas = await self._memory_provider.notes().list(
                category=category,
                tag=tag,
                importance=importance_filter,
            )
        except Exception:  # noqa: BLE001
            logger.debug("manager._notes_list: provider list failed", exc_info=True)
            metas = []
        results: List[MemoryFileInfo] = []
        for m in metas:
            cat = m.category or "root"
            bare = m.ref.filename
            display_filename = bare if cat == "root" else f"{cat}/{bare}"
            results.append(
                MemoryFileInfo(
                    filename=display_filename,
                    title=m.title or bare,
                    category=cat,
                    tags=list(m.tags),
                    importance=m.importance.value,
                    created=m.created_at.isoformat() if m.created_at else "",
                    modified=m.updated_at.isoformat() if m.updated_at else "",
                    source="system",
                    char_count=m.size_bytes,
                    links_to=[],
                    linked_from=[],
                )
            )
        results.sort(key=lambda f: f.modified, reverse=True)
        return results

    async def _notes_link(self, source_file: str, target_file: str) -> bool:
        if self._memory_provider is None:
            return False
        from geny_executor.memory.provider import NotePatch

        target_stem = Path(target_file).stem
        bare_source = Path(source_file).name
        notes = self._memory_provider.notes()

        try:
            existing = await notes.read(bare_source)
        except Exception:  # noqa: BLE001
            logger.warning(
                "manager._notes_link: read failed for %s", source_file,
                exc_info=True,
            )
            return False
        if existing is None:
            return False

        marker = f"[[{target_stem}]]"
        if marker.lower() in existing.body.lower():
            return True
        if target_stem in (existing.links_out or []):
            return True

        patch = NotePatch(append_body=f"> See also: {marker}")
        try:
            await notes.update(bare_source, patch)
        except KeyError:
            return False
        except Exception:  # noqa: BLE001
            logger.warning(
                "manager._notes_link: provider update failed for %s → %s",
                source_file, target_stem, exc_info=True,
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Set up directory structure for both memory stores."""
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        (self._memory_dir / "topics").mkdir(parents=True, exist_ok=True)
        # transcripts/ dir is created by the executor's STM store on
        # the first append; nothing to do here.
        self._transcript_dir.mkdir(parents=True, exist_ok=True)

        # Initialize structured memory layer.
        # Sprint 3 step 4 — ``MemoryIndexManager`` retired; writers no
        # longer receive a host-side index handle.
        # Sprint 3 step 5 — ``StructuredMemoryWriter`` retired from the
        # manager; note CRUD routes through ``provider.notes()`` via
        # the inline ``_notes_*`` helpers above.
        memory_dir = self._memory_dir
        self._conversation_archiver = self._ConversationArchiver(
            str(memory_dir),
            session_id=self._session_id or "",
        )
        self._dm_archiver = self._DmArchiver(
            str(memory_dir),
            session_id=self._session_id or "",
        )
        # PR 8 — compaction archiver. Takes the session storage_path
        # (not memory_dir) because it writes to two locations:
        # ``transcripts/compactions/`` (audit) and
        # ``memory/compactions/`` (vault).
        self._compaction_archiver = self._CompactionArchiver(
            self._storage_path,
            session_id=self._session_id or "",
        )
        # GENY-7b/8 — `StructuredMemoryWriter` no longer has a DB
        # dual-write path; the disk via `provider.notes()` is the
        # single truth. STM/LTM keep their analytics mirrors for now
        # (revisited in GENY-9).

        # Path-A migration GENY-7c — `MemoryMigrator` retired. The
        # plan explicitly opted out of legacy-data migration; new
        # sessions land in the executor-owned layout from the start.

        self._initialized = True
        logger.info("SessionMemoryManager initialized at %s", self._storage_path)

    async def _seed_identity_ledger_if_empty(self) -> None:
        """Promote hand-pinned identity notes into an EMPTY fact ledger.

        Selection is purely structural: critical CATEGORY + critical
        IMPORTANCE (the author's own never-forget declaration). Seeded rows
        carry ``importance=critical`` so the identity card includes them
        regardless of kind. Statements are whitespace-normalized bodies;
        ids derive from filenames so re-runs stay idempotent even if the
        emptiness guard were ever bypassed.
        """
        if self._memory_provider is None:
            return
        from geny_executor.memory.facts import Fact, FactLedger

        ledger = FactLedger(self._memory_provider)
        state = await ledger.load()
        if any(f.status == "active" for f in state.facts):
            return
        notes = self._memory_provider.notes()
        metas = await notes.list(category="critical")
        seeded = 0
        for m in metas:
            fname = m.ref.filename
            if fname.startswith("__"):  # ledger/evergreen themselves
                continue
            # Structural selection only: a hand-pinned note in the critical
            # category with critical importance IS the author's declaration
            # of a never-forget fact — no tag or text heuristics.
            imp = getattr(m, "importance", None)
            if (getattr(imp, "value", str(imp)) if imp is not None else "") != "critical":
                continue
            note = await notes.read(fname)
            body = " ".join(((note.body if note else "") or "").split())
            if not body:
                continue
            state.facts.append(
                Fact(
                    id=f"seed-{fname.rsplit('.', 1)[0]}"[:64],
                    kind="knowledge",
                    statement=body[:400],
                    importance="critical",
                )
            )
            seeded += 1
        if seeded:
            if await ledger.save(state):
                logger.info(
                    "identity ledger seeded from %d pinned note(s)", seeded
                )

    async def initialize_vector_memory(self) -> bool:
        """Initialise the FAISS vector memory layer (async).

        Called separately from :meth:`initialize` because it requires
        async I/O for config loading and initial indexing.

        Returns:
            ``True`` if vector memory was enabled and initialised.
        """
        try:
            # One-time ledger seed BEFORE indexing: the fact ledger is the
            # identity card's primary source, and in the field it sat empty
            # (extraction accrues nothing) while the persona hand-pinned
            # identity notes — promote those into the ledger so identity
            # survives independent of extraction health. Idempotent: only
            # runs while the ledger has zero active facts.
            try:
                await self._seed_identity_ledger_if_empty()
            except Exception:  # noqa: BLE001 — seed is best-effort
                logger.debug("identity ledger seed failed", exc_info=True)
            return await self._vector_initialize_and_index()
        except Exception:
            logger.warning(
                "initialize_vector_memory failed (non-critical)",
                exc_info=True,
            )
            return False

    # ------------------------------------------------------------------
    # Write operations (convenience wrappers)
    # ------------------------------------------------------------------

    def record_message(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        """Record a conversation message to short-term memory.

        Cycle 20260430_2 added the canonical *InteractionEvent* schema
        (``service.memory.interaction_event.make_event_metadata``).
        Callers pass the helper's output as ``metadata=...``; the legacy
        variadic ``**extra`` form is kept as a backwards-compat tail
        for the very small number of pre-cycle call sites that pass
        bare kwargs (none in current code, but the door stays open).
        Both forms merge into a single dict; ``extra`` losers ties on
        key collisions so explicit ``metadata`` always wins.

        The cycle-20260430_3 ``entities/<sanitized>.md`` auto-bootstrap
        was retired in Memory v2 (post-1.11): counterpart info now
        lives entirely under ``dms/<cp>/<date>.md`` (per-counterpart-
        per-day index) plus the StreamTab UI, and ``memory_distill``
        writes to ``insights/counterpart-<id>.md`` on demand.

        Args:
            role: "user" | "assistant" | "system" | "internal_trigger"
                | "assistant_dm" — see ``_classify_input_role``.
            content: Message content.
            metadata: Optional structured metadata dict (e.g. the output
                of ``make_event_metadata``).
            **extra: Legacy variadic metadata kwargs.
        """
        meta: Dict[str, Any] = {}
        if extra:
            meta.update(extra)
        if metadata:
            meta.update(metadata)
        out_meta: Optional[Dict[str, Any]] = meta if meta else None

        # Path-A GENY-5/6 — `_maybe_archive_conversation` /
        # `_maybe_archive_dm` are no longer called from here. The
        # executor's `after_record_turn` hook (installed by
        # `AgentSession._install_memory_hooks`) drives both archivers
        # for every STM append, which now includes both the stage 18
        # `_drive_provider` path *and* this synchronous
        # `record_message` (agent-DM tool, internal triggers, etc.)
        # — both call `provider.stm().append`, which fires the hook.
        from service.memory.sync_async_bridge import run_coro_sync
        run_coro_sync(self._stm_append_message(role, content, out_meta))

    def _maybe_archive_conversation(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]],
    ):
        """Best-effort hand-off to ConversationArchiver.

        Returns the ``ArchivedConversation`` result on success, or
        ``None`` for any reason that means "skip" (legacy metadata,
        archiver not built yet, transient write error). Never raises
        — record_message is a hot path and must not fail because of
        a leaf-archive side-effect.

        See plan §4.2 (record_message hook chain).
        """
        if self._conversation_archiver is None:
            return None
        try:
            return self._conversation_archiver.archive(role, content, metadata)
        except Exception:
            logger.debug(
                "conversation archive hook failed — non-critical",
                exc_info=True,
            )
            return None

    def _maybe_archive_dm(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]],
        conversation_ref: Optional[str],
    ):
        """Best-effort hand-off to DmArchiver. PR 4.

        DmArchiver itself filters by kind / counterpart so this
        wrapper just guards initialisation + exception swallow.
        """
        if self._dm_archiver is None:
            return None
        try:
            return self._dm_archiver.append(
                role, content, metadata, conversation_ref=conversation_ref,
            )
        except Exception:
            logger.debug(
                "dm archive hook failed — non-critical", exc_info=True,
            )
            return None


    def record_event(self, event: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Record a non-message event (tool call, state change, etc.)."""
        from service.memory.sync_async_bridge import run_coro_sync
        run_coro_sync(self._stm_append_event(event, data))

    def record_compaction(
        self,
        summary: str,
        *,
        replaced_count: int,
        ts: Optional[Any] = None,
        strategy: str = "",
        saved_tokens: Optional[int] = None,
    ) -> Optional[Any]:
        """Persist a compaction snapshot to both the audit log
        (``transcripts/compactions/<ts>.md``) and the vault
        (``memory/compactions/<sid>__<ts>.md``).

        Memory v2 PR 8 — closes plan §2.2 (compaction must survive
        the process so the next session can ``memory_search`` it).

        Best-effort. Returns the ``ArchivedCompaction`` dataclass on
        success, ``None`` on any write failure (logged at debug).
        """
        if self._compaction_archiver is None:
            return None
        try:
            return self._compaction_archiver.archive(
                summary,
                replaced_count=replaced_count,
                ts=ts,
                strategy=strategy,
                saved_tokens=saved_tokens,
            )
        except Exception:
            logger.debug(
                "record_compaction failed — non-critical",
                exc_info=True,
            )
            return None

    def remember(self, text: str, *, heading: Optional[str] = None) -> None:
        """Write durable knowledge to long-term memory.

        This appends to MEMORY.md. For dated entries use remember_dated().

        Args:
            text: The knowledge to persist.
            heading: Optional markdown heading.
        """
        from service.memory.sync_async_bridge import run_coro_sync
        run_coro_sync(self._ltm_append(text, heading=heading))

    def remember_dated(self, text: str) -> None:
        """Write an execution-summary block to today's executions file.

        Cycle 20260503_5 — the call surface stays the same (every
        existing strategy still calls ``mgr.remember_dated(...)``)
        but the on-disk target changed from
        ``memory/<YYYY-MM-DD>.md`` (which was being shared with
        ``DailyJournalWriter``) to ``memory/executions/<YYYY-MM-DD>.md``
        so the two streams no longer collide on one file.
        """
        from service.memory.sync_async_bridge import run_coro_sync
        run_coro_sync(self._ltm_write_execution(text))

    def remember_topic(self, topic: str, text: str) -> None:
        """Write knowledge to a topic-specific long-term memory file."""
        from service.memory.sync_async_bridge import run_coro_sync
        run_coro_sync(self._ltm_write_topic(topic, text))

    # ------------------------------------------------------------------
    # Structured memory operations (Obsidian-like)
    # ------------------------------------------------------------------

    def write_note(
        self,
        title: str,
        content: str,
        *,
        category: str = "topics",
        tags: Optional[List[str]] = None,
        importance: str = "medium",
        source: str = "system",
        links_to: Optional[List[str]] = None,
        filename_override: Optional[str] = None,
    ) -> Optional[str]:
        """Write a structured memory note with frontmatter.

        Returns the filename of the created note, or None on failure.
        Sync wrapper; async callers should use :meth:`awrite_note`.
        """
        if self._memory_provider is None:
            # Fallback to legacy write
            from service.memory.sync_async_bridge import run_coro_sync
            run_coro_sync(self._ltm_write_topic(title, content))
            return None
        from service.memory.sync_async_bridge import run_coro_sync
        return run_coro_sync(self._notes_write(
            title=title,
            content=content,
            category=category,
            tags=tags,
            importance=importance,
            source=source,
            links_to=links_to,
            filename_override=filename_override,
        ))

    async def awrite_note(
        self,
        title: str,
        content: str,
        *,
        category: str = "topics",
        tags: Optional[List[str]] = None,
        importance: str = "medium",
        source: str = "system",
        links_to: Optional[List[str]] = None,
        filename_override: Optional[str] = None,
    ) -> Optional[str]:
        if self._memory_provider is None:
            await self._ltm_write_topic(title, content)
            return None
        return await self._notes_write(
            title=title,
            content=content,
            category=category,
            tags=tags,
            importance=importance,
            source=source,
            links_to=links_to,
            filename_override=filename_override,
        )

    def update_note(
        self,
        filename: str,
        *,
        body: Optional[str] = None,
        tags: Optional[List[str]] = None,
        importance: Optional[str] = None,
    ) -> bool:
        """Update an existing structured memory note.

        Returns True if updated successfully.
        """
        from service.memory.sync_async_bridge import run_coro_sync
        return run_coro_sync(self._notes_update(
            filename, body=body, tags=tags, importance=importance,
        ))

    async def aupdate_note(
        self,
        filename: str,
        *,
        body: Optional[str] = None,
        tags: Optional[List[str]] = None,
        importance: Optional[str] = None,
    ) -> bool:
        return await self._notes_update(
            filename, body=body, tags=tags, importance=importance,
        )

    def delete_note(self, filename: str) -> bool:
        """Delete a structured memory note.

        Returns True if deleted successfully.
        """
        from service.memory.sync_async_bridge import run_coro_sync
        return run_coro_sync(self._notes_delete(filename))

    async def adelete_note(self, filename: str) -> bool:
        return await self._notes_delete(filename)

    def read_note(self, filename: str) -> Optional[Dict[str, Any]]:
        """Read a structured memory note and return its metadata + body.

        Returns dict with keys: metadata, body, filename. None if not found.
        """
        from service.memory.sync_async_bridge import run_coro_sync
        return run_coro_sync(self._notes_read(filename))

    async def aread_note(self, filename: str) -> Optional[Dict[str, Any]]:
        return await self._notes_read(filename)

    def list_notes(
        self,
        *,
        category: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List memory notes with optional category/tag filters.

        Returns list of note info dicts.
        """
        from service.memory.sync_async_bridge import run_coro_sync
        notes = run_coro_sync(self._notes_list(category=category, tag=tag))
        return [self._file_info_to_dict(n) for n in notes]

    async def alist_notes(
        self,
        *,
        category: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        notes = await self._notes_list(category=category, tag=tag)
        return [self._file_info_to_dict(n) for n in notes]

    def link_notes(self, source_filename: str, target_filename: str) -> bool:
        """Create a wikilink between two notes.

        Returns True if link was created successfully.
        """
        from service.memory.sync_async_bridge import run_coro_sync
        return run_coro_sync(self._notes_link(source_filename, target_filename))

    async def alink_notes(
        self, source_filename: str, target_filename: str
    ) -> bool:
        return await self._notes_link(source_filename, target_filename)

    def get_memory_index(self) -> Optional[Dict[str, Any]]:
        """Get the full memory index for API responses."""
        if self._memory_provider is None:
            return None
        from service.memory.sync_async_bridge import run_coro_sync
        idx = run_coro_sync(self._index_snapshot())
        return {
            "files": {k: self._file_info_to_dict(v) for k, v in idx.files.items()},
            "tag_map": idx.tag_map,
            "total_files": idx.total_files,
            "total_chars": idx.total_chars,
        }

    def get_memory_tags(self) -> Dict[str, int]:
        """Get tag counts from the index."""
        if self._memory_provider is None:
            return {}
        from service.memory.sync_async_bridge import run_coro_sync
        idx = run_coro_sync(self._index_snapshot())
        tag_counts: Dict[str, int] = {}
        for tag, filenames in idx.tag_map.items():
            tag_counts[tag] = len(filenames)
        return tag_counts

    def get_memory_graph(self) -> Dict[str, Any]:
        """Get link graph data for visualization (enhanced with tag edges + metadata)."""
        if self._memory_provider is None:
            return {"nodes": [], "edges": []}
        from service.memory.sync_async_bridge import run_coro_sync
        idx = run_coro_sync(self._index_snapshot())
        nodes = []
        edges = []
        edge_set: set = set()
        tag_to_files: Dict[str, list] = {}
        files_set = set(idx.files.keys())

        for fn, info in idx.files.items():
            nodes.append({
                "id": fn,
                "label": info.title or fn.replace(".md", ""),
                "category": info.category,
                "importance": info.importance,
                "tags": info.tags,
                "connectionCount": len(info.links_to) + len(info.linked_from),
                "summary": info.summary or "",
                "charCount": info.char_count,
            })

            # Wikilink edges (with target existence filter)
            for target in info.links_to:
                if target in files_set:
                    key = (fn, target)
                    if key not in edge_set:
                        edge_set.add(key)
                        edges.append({
                            "source": fn,
                            "target": target,
                            "type": "wikilink",
                            "weight": 1.0,
                        })

            # Build tag map
            for tag in info.tags:
                tag_to_files.setdefault(tag, []).append(fn)

        # Tag-based edges
        for tag, fns in tag_to_files.items():
            if len(fns) < 2:
                continue
            for i in range(len(fns)):
                for j in range(i + 1, len(fns)):
                    a, b = fns[i], fns[j]
                    if (a, b) not in edge_set and (b, a) not in edge_set:
                        edge_set.add((a, b))
                        edges.append({
                            "source": a,
                            "target": b,
                            "type": "tag",
                            "weight": 0.5,
                            "label": tag,
                        })

        return {"nodes": nodes, "edges": edges}

    def reindex_memory(self) -> int:
        """Force a full rebuild of the memory index.

        Returns total number of indexed files.
        """
        from service.memory.sync_async_bridge import run_coro_sync
        return run_coro_sync(self._index_rebuild())

    async def areindex_memory(self) -> int:
        return await self._index_rebuild()

    @staticmethod
    def _file_info_to_dict(info) -> Dict[str, Any]:
        """Convert MemoryFileInfo to dict."""
        return {
            "filename": info.filename,
            "title": info.title,
            "category": info.category,
            "tags": info.tags,
            "importance": info.importance,
            "created": info.created,
            "modified": info.modified,
            "source": info.source,
            "char_count": info.char_count,
            "links_to": info.links_to,
            "linked_from": info.linked_from,
            "summary": info.summary,
        }

    async def record_execution(
        self,
        *,
        input_text: str,
        result_state: Dict[str, Any],
        duration_ms: int,
        execution_number: int = 0,
        success: bool = True,
        media: Optional[List[str]] = None,
    ) -> None:
        """Record a structured execution summary to long-term memory.

        Called after each graph invoke/astream to persist a concise,
        structured record of work done — modeled after WORK_LOG.md's
        methodology but designed for long-term memory recall.

        Writes to ``memory/YYYY-MM-DD.md`` with structured sections.
        When the vector memory layer is enabled, the entry is also
        indexed into FAISS (awaited to prevent race conditions with
        ``auto_flush`` / ``vmm.save()``).

        File/DB recording is always active regardless of LTM config.
        Only vector indexing (FAISS) requires LTM to be enabled.

        Args:
            input_text: The user's input prompt.
            result_state: The final AutonomousState dict from the graph.
            duration_ms: Total execution wall-time in milliseconds.
            execution_number: Sequential execution counter for this session.
            success: Whether execution completed without errors.
            media: Bare filenames of screen frames USED by this turn
                (already persisted under ``memory/attachments/`` by
                ``promote_used_frames``) — embedded into the record so
                the conversation is complete with what the persona saw.
        """
        try:
            from service.memory.note_utils import is_silent_reply

            final_output_for_silence = (
                result_state.get("final_answer", "")
                or result_state.get("answer", "")
                or result_state.get("last_output", "")
                or ""
            )
            silent = is_silent_reply(final_output_for_silence)

            entry = self._build_execution_entry(
                input_text=input_text,
                result_state=result_state,
                duration_ms=duration_ms,
                execution_number=execution_number,
                success=success,
                media=media,
            )
            # Cycle 20260503_5 — execution summaries land in
            # ``memory/executions/<YYYY-MM-DD>.md`` instead of the
            # daily-journal root file. The structured-note dual
            # write below still goes to ``memory/daily/`` so the
            # human-friendly card surface keeps working.
            await self._ltm_write_execution(entry)
            logger.info(
                "record_execution: #%d (%d chars) → executions/",
                execution_number, len(entry),
            )
            try:
                from service.memory.event_emitter import emit_memory_event

                emit_memory_event(
                    self._session_id,
                    event_type="execution_recorded",
                    source="Memory",
                    layer="ltm",
                    chars=len(entry),
                    extra={
                        "execution_number": execution_number,
                        "success": bool(success),
                    },
                    message=(
                        f"execution_recorded: #{execution_number} "
                        f"({len(entry)} chars, success={success})"
                    ),
                )
            except Exception:  # noqa: BLE001
                logger.debug(
                    "record_execution: memory_event emit skipped",
                    exc_info=True,
                )

            # ── Structured note (dual-write) ─────────────────────────
            if self._memory_provider is not None:
                try:
                    auto_tags = self._extract_execution_tags(
                        input_text, result_state,
                    )
                    outcome = _outcome_of(success, result_state)
                    status_tag = {"ok": "success", "partial": "partial"}.get(outcome, "failure")
                    all_tags = ["execution", status_tag] + auto_tags
                    imp = "medium" if outcome == "ok" else "high"
                    title = (
                        f"Execution #{execution_number} — "
                        f"{input_text[:60].strip()}"
                    )
                    if silent:
                        # No-response turns are kept for audit but must be
                        # visually distinct AND inert: tagged (graph
                        # projection + retention sweep key off it),
                        # low-importance, and title-marked.
                        all_tags.append("silent")
                        imp = "low"
                        title += " \u00b7 silent"
                    await self._notes_write(
                        title=title,
                        content=entry,
                        category="daily",
                        tags=all_tags,
                        importance=imp,
                        source="execution",
                        links_to=None,
                    )
                except Exception:
                    logger.debug(
                        "record_execution: structured write failed (non-critical)",
                        exc_info=True,
                    )

            # Index into vector DB (only when LTM config is enabled)
            from service.config.sub_config.general.ltm_config import LTMConfig

            if LTMConfig.is_enabled() and self._vector_enabled and not silent:
                try:
                    date_str = datetime.now(_get_tz()).strftime("%Y-%m-%d")
                    source = f"memory/{date_str}.md"
                    await self._vector_index_text(entry, source)
                except Exception:
                    logger.debug(
                        "record_execution: vector indexing failed (non-critical)",
                        exc_info=True,
                    )

        except Exception:
            logger.warning(
                "record_execution: failed to write (non-critical)",
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Execution entry builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_execution_entry(
        *,
        input_text: str,
        result_state: Dict[str, Any],
        duration_ms: int,
        execution_number: int,
        success: bool,
        media: Optional[List[str]] = None,
    ) -> str:
        """Build a structured markdown entry for one graph execution.

        Format:
            ### [✅/❌] Execution #N — <difficulty> path
            > **Task:** <truncated user input>
            > **Duration:** X.Xs | **Iterations:** N/max

            **Result:**
            <truncated final output>

            **TODOs:** (hard path only)
            - ✅ Task title
            - ⬜ Task title

            **Review:** approved/rejected (medium path only)

        Returns:
            Formatted markdown string.
        """
        outcome = _outcome_of(success, result_state)
        status_icon = OUTCOME_MARK[outcome]

        # --- Extract fields from state ---
        difficulty = result_state.get("difficulty", "unknown")
        iteration = result_state.get("iteration", 0)
        max_iterations = result_state.get("max_iterations", 0)
        error = result_state.get("error")
        completion_signal = result_state.get("completion_signal", "")
        completion_detail = result_state.get("completion_detail", "")

        # Best output: final_answer > answer > last_output
        final_output = (
            result_state.get("final_answer", "")
            or result_state.get("answer", "")
            or result_state.get("last_output", "")
            or ""
        )

        # Truncate for readability
        input_preview = input_text[:_LTM_INPUT_PREVIEW]
        if len(input_text) > _LTM_INPUT_PREVIEW:
            input_preview += "..."

        output_preview = final_output[:_LTM_OUTPUT_PREVIEW]
        if len(final_output) > _LTM_OUTPUT_PREVIEW:
            output_preview += "..."

        # Duration formatting
        if duration_ms >= 60_000:
            duration_str = f"{duration_ms / 60_000:.1f}m"
        elif duration_ms >= 1_000:
            duration_str = f"{duration_ms / 1_000:.1f}s"
        else:
            duration_str = f"{duration_ms}ms"

        # --- Build markdown ---
        lines: list[str] = []

        # Header
        lines.append(
            f"### [{status_icon}] Execution #{execution_number}"
            f" — {difficulty} path"
        )
        lines.append("")

        # Task & metrics
        lines.append(f"> **Task:** {input_preview}")
        lines.append(
            f"> **Duration:** {duration_str}"
            f" | **Iterations:** {iteration}/{max_iterations}"
        )
        tool_calls = int(result_state.get("tool_calls") or 0)
        if tool_calls:
            failures = int(result_state.get("tool_failures") or 0)
            tools_line = f"> **Tools:** {tool_calls} call(s)"
            if failures:
                tools_line += f" · {failures} failed"
            lines.append(tools_line)
        if outcome == "partial":
            # A ✅ on a turn whose tools failed later read, from memory, as
            # "that was done" — XGEN saw an agent believe a tool it never
            # built existed.
            lines.append(
                "> **Outcome:** partial — some tool calls failed; do not treat the task as done"
            )
        lines.append("")

        # Screen frames the persona saw during this turn (promoted to the
        # permanent memory/attachments/ bucket — embed by bare name, the
        # attachment endpoint resolves it anywhere in the memory tree).
        if media:
            lines.append("**Screen:**")
            for name in media:
                lines.append(f"![[{name}]]")
            lines.append("")

        # TODO list (hard path)
        todos = result_state.get("todos") or []
        if todos and difficulty == "hard":
            lines.append("**TODOs:**")
            for todo in todos:
                title = todo.get("title", "Untitled")
                status = todo.get("status", "pending")
                if status in ("completed",):
                    icon = "✅"
                elif status in ("in_progress",):
                    icon = "🔄"
                elif status in ("failed",):
                    icon = "❌"
                else:
                    icon = "⬜"

                result_text = todo.get("result", "")
                if result_text:
                    result_text = result_text[:_LTM_TODO_RESULT_PREVIEW]
                    if len(todo.get("result", "")) > _LTM_TODO_RESULT_PREVIEW:
                        result_text += "..."
                    lines.append(f"- {icon} **{title}** → {result_text}")
                else:
                    lines.append(f"- {icon} **{title}**")
            lines.append("")

        # Review feedback (medium path)
        review_result = result_state.get("review_result")
        review_feedback = result_state.get("review_feedback")
        if review_result and difficulty == "medium":
            feedback_preview = ""
            if review_feedback:
                feedback_preview = f" — {review_feedback[:200]}"
                if len(review_feedback) > 200:
                    feedback_preview += "..."
            lines.append(f"**Review:** {review_result}{feedback_preview}")
            lines.append("")

        # Completion signal
        if completion_signal and completion_signal not in ("none", "continue"):
            detail = f" ({completion_detail})" if completion_detail else ""
            lines.append(f"**Signal:** {completion_signal}{detail}")
            lines.append("")

        # Error
        if error:
            lines.append(f"**Error:** {error[:300]}")
            lines.append("")

        # Result output
        if output_preview:
            lines.append("**Result:**")
            lines.append(output_preview)
            lines.append("")

        # Fallback info
        fallback = result_state.get("fallback")
        if fallback and fallback.get("degraded"):
            lines.append(
                f"**Model Fallback:** {fallback.get('original_model', '?')}"
                f" → {fallback.get('current_model', '?')}"
                f" (attempts: {fallback.get('attempts', 0)})"
            )
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _extract_execution_tags(
        input_text: str,
        result_state: Dict[str, Any],
    ) -> List[str]:
        """Extract auto-tags from execution input and state."""
        tags: List[str] = []
        difficulty = result_state.get("difficulty")
        if difficulty:
            tags.append(difficulty)
        if result_state.get("todos"):
            tags.append("todos")
        if result_state.get("review_result"):
            tags.append("reviewed")
        # Extract simple keyword tags from input
        text = input_text.lower()
        keyword_tags = {
            "debug": "debug",
            "fix": "fix",
            "error": "error",
            "test": "test",
            "deploy": "deploy",
            "build": "build",
            "refactor": "refactor",
            "design": "design",
            "analyze": "analysis",
            "review": "review",
        }
        for keyword, tag in keyword_tags.items():
            if keyword in text and tag not in tags:
                tags.append(tag)
        return tags[:10]  # cap at 10

    # ------------------------------------------------------------------
    # Pinned facts (Memory v2 PR 12 / T1 tier)
    # ------------------------------------------------------------------

    def load_pinned(self, *, max_chars: int = 3000):
        """Return the always-inject pinned-facts surface.

        Reads ``memory/critical/*.md`` via the executor's
        ``NotesHandle.load_pinned`` and packs the bodies (frontmatter
        stripped) into one ``MemoryEntry``. Sync wrapper; async
        callers should use :meth:`aload_pinned`.
        """
        from service.memory.sync_async_bridge import run_coro_sync
        return run_coro_sync(self._ltm_load_pinned(max_chars=max_chars))

    async def aload_pinned(self, *, max_chars: int = 3000):
        return await self._ltm_load_pinned(max_chars=max_chars)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        sources: Optional[List[MemorySource]] = None,
    ) -> List[MemorySearchResult]:
        """Search across all memory stores.

        Results from long-term memory are weighted higher (1.2x)
        than short-term memory.

        Args:
            query: Search string.
            max_results: Maximum total results.
            sources: Filter to specific sources. None = all.
        """
        from service.memory.sync_async_bridge import run_coro_sync

        results: list[MemorySearchResult] = []

        if sources is None or MemorySource.LONG_TERM in sources:
            ltm_results = run_coro_sync(
                self._ltm_search(query, max_results=max_results)
            )
            for r in ltm_results:
                r.score *= 1.2  # Long-term memory relevance boost
            results.extend(ltm_results)

        if sources is None or MemorySource.SHORT_TERM in sources:
            stm_results = run_coro_sync(self._stm_search(query, max_results))
            results.extend(stm_results)

        # Sort by combined score, deduplicate if needed
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:max_results]

    async def search_async(
        self,
        query: str,
        *,
        max_results: int = 10,
        sources: Optional[List[MemorySource]] = None,
    ) -> List[MemorySearchResult]:
        """Async sibling of :meth:`search` that also blends vector results.

        Memory v2 PR 12 — restores the vector fallback that was lost
        when ``build_memory_context_async`` was deprecated. The
        agent's ``memory_search`` tool routes here via its async
        path (``MemorySearchTool.arun``) so a Korean query still
        finds an English-titled note via embedding similarity even
        when the keyword-density signal is zero.

        Result merging:
          1. Run :meth:`search` for the keyword + STM portion.
          2. Run :meth:`VectorMemoryManager.search` if enabled.
          3. Wrap vector hits as :class:`MemorySearchResult` carrying
             ``match_type='vector'``.
          4. Deduplicate by filename — keep the highest-scoring entry.
          5. Sort by score desc and slice ``max_results``.
        """
        # 1) Sync keyword path. ``search`` is fast enough to call
        #    inline; running it in a thread would be overkill for
        #    typical session sizes.
        keyword_results = self.search(
            query, max_results=max_results, sources=sources,
        )

        # 2) Vector path — only when the host has wired the layer
        #    AND when the caller did not narrow ``sources`` to
        #    something that excludes long-term memory (vector hits
        #    are by definition LTM-derived).
        vector_results: list[MemorySearchResult] = []
        if sources is None or MemorySource.LONG_TERM in sources:
            if self._vector_enabled:
                try:
                    v_hits = await self._vector_search(query, top_k=max_results)
                except Exception:
                    logger.debug(
                        "search_async: vector search failed", exc_info=True,
                    )
                    v_hits = []
            else:
                v_hits = []
                for vr in v_hits or []:
                    text = getattr(vr, "text", "") or ""
                    if not text.strip():
                        continue
                    source_file = getattr(vr, "source_file", "vector")
                    score = float(getattr(vr, "score", 0.0))
                    entry = MemoryEntry(
                        source=MemorySource.LONG_TERM,
                        content=text,
                        filename=source_file,
                        metadata={
                            "match_type": "vector",
                            "chunk_index": getattr(vr, "chunk_index", 0),
                        },
                    )
                    vector_results.append(
                        MemorySearchResult(
                            entry=entry,
                            score=score,
                            snippet=text[:240],
                            match_type="vector",
                        )
                    )

        # 3) Merge with filename-level dedup. Vector hits boost an
        #    existing keyword hit instead of duplicating it; pure
        #    vector hits land at the bottom of their score band but
        #    still surface when keyword density was zero.
        by_filename: Dict[str, MemorySearchResult] = {}
        for r in keyword_results:
            fn = (r.entry.filename or "") if r.entry else ""
            by_filename[fn or f"_kw_{id(r)}"] = r
        for r in vector_results:
            fn = (r.entry.filename or "") if r.entry else ""
            key = fn or f"_vec_{id(r)}"
            if key in by_filename:
                # Combine: keep the higher-density score, mark
                # ``match_type`` as a hybrid for downstream filters.
                existing = by_filename[key]
                if r.score > existing.score:
                    existing.score = r.score
                existing.match_type = "hybrid"
            else:
                by_filename[key] = r

        merged = list(by_filename.values())
        merged.sort(key=lambda r: r.score, reverse=True)
        return merged[:max_results]

    # ------------------------------------------------------------------
    # Context injection
    # ------------------------------------------------------------------

    def build_memory_context(
        self,
        query: Optional[str] = None,
        *,
        include_summary: bool = True,
        include_recent: int = 0,
        max_chars: Optional[int] = None,
    ) -> Optional[str]:
        """Build a memory context block for system prompt injection.

        .. deprecated:: Memory v2 PR 11
            Path A is retired (plan §5.1). System prompts no longer
            statically inject memory; the s02 ContextStage's
            ``GenyMemoryRetriever`` (slim mode) handles per-turn
            retrieval and the agent's ``memory_*`` tool ladder
            handles deep-dive bodies. Kept here for callers in
            transition; will be removed in a follow-up cycle.

        This was called before each agent turn to inject relevant
        memory into the conversation context.

        Args:
            query: Optional query to search for relevant memories.
            include_summary: Include session summary if available.
            include_recent: Number of recent messages to include (0 = none).
            max_chars: Character budget (default: self._max_inject_chars).

        Returns:
            Formatted memory context string, or None if nothing to inject.
        """
        budget = max_chars or self._max_inject_chars
        parts: list[str] = []
        total_chars = 0

        from service.memory.sync_async_bridge import run_coro_sync

        # 1. Session summary (if available)
        if include_summary:
            summary = run_coro_sync(self._stm_get_summary())
            if summary and (total_chars + len(summary)) <= budget:
                parts.append(f"<session-summary>\n{summary}\n</session-summary>")
                total_chars += len(summary)

        # 2. Long-term memory: main MEMORY.md
        main_mem = run_coro_sync(self._ltm_load_main())
        if main_mem and (total_chars + main_mem.char_count) <= budget:
            parts.append(
                f"<long-term-memory source=\"{main_mem.filename}\">\n"
                f"{main_mem.content}\n"
                f"</long-term-memory>"
            )
            total_chars += main_mem.char_count

        # 3. Query-based memory retrieval
        if query:
            search_results = self.search(query, max_results=5)
            for result in search_results:
                chunk = (
                    f"<memory-recall source=\"{result.entry.filename}\" "
                    f"score=\"{result.score:.2f}\">\n"
                    f"{result.snippet}\n"
                    f"</memory-recall>"
                )
                if (total_chars + len(chunk)) > budget:
                    break
                parts.append(chunk)
                total_chars += len(chunk)

        # 4. Recent transcript messages
        if include_recent > 0:
            recent = run_coro_sync(self._stm_get_recent(include_recent))
            for entry in recent:
                if (total_chars + entry.char_count) > budget:
                    break
                parts.append(
                    f"<recent-message>\n{entry.content}\n</recent-message>"
                )
                total_chars += entry.char_count

        if not parts:
            return None

        header = "## Recalled Memory\n"
        body = "\n\n".join(parts)
        return f"{header}\n{body}"

    async def build_memory_context_async(
        self,
        query: Optional[str] = None,
        *,
        include_summary: bool = True,
        include_recent: int = 0,
        max_chars: Optional[int] = None,
    ) -> Optional[str]:
        """Async version of ``build_memory_context`` with vector search.

        .. deprecated:: Memory v2 PR 11
            Same rationale as :meth:`build_memory_context` —
            production never wired this method (review.md P10) and
            v2 routes retrieval through ``GenyMemoryRetriever``
            instead.

        Includes FAISS vector search results when the vector memory
        layer is enabled, in addition to keyword search and file-based
        retrieval.

        Args:
            query: Optional query to search for relevant memories.
            include_summary: Include session summary if available.
            include_recent: Number of recent messages to include.
            max_chars: Character budget.

        Returns:
            Formatted memory context string, or None.
        """
        budget = max_chars or self._max_inject_chars
        parts: list[str] = []
        total_chars = 0

        # 1. Session summary
        if include_summary:
            summary = await self._stm_get_summary()
            if summary and (total_chars + len(summary)) <= budget:
                parts.append(f"<session-summary>\n{summary}\n</session-summary>")
                total_chars += len(summary)

        # 2. Main MEMORY.md
        main_mem = await self._ltm_load_main()
        if main_mem and (total_chars + main_mem.char_count) <= budget:
            parts.append(
                f"<long-term-memory source=\"{main_mem.filename}\">\n"
                f"{main_mem.content}\n"
                f"</long-term-memory>"
            )
            total_chars += main_mem.char_count

        # 3. Vector semantic search (if enabled)
        if query and self._vector_enabled:
            try:
                v_results = await self._vector_search(query)
                v_context = self._vector_build_context(
                    v_results, max_chars=budget - total_chars
                )
                if v_context:
                    parts.append(v_context)
                    total_chars += len(v_context)
            except Exception:
                logger.debug(
                    "build_memory_context_async: vector search failed",
                    exc_info=True,
                )

        # 4. Keyword-based memory recall (complementary)
        if query:
            remaining_budget = budget - total_chars
            if remaining_budget > 200:
                search_results = self.search(query, max_results=5)
                for result in search_results:
                    chunk = (
                        f"<memory-recall source=\"{result.entry.filename}\" "
                        f"score=\"{result.score:.2f}\">\n"
                        f"{result.snippet}\n"
                        f"</memory-recall>"
                    )
                    if (total_chars + len(chunk)) > budget:
                        break
                    parts.append(chunk)
                    total_chars += len(chunk)

        # 5. Recent transcript messages
        if include_recent > 0:
            recent = await self._stm_get_recent(include_recent)
            for entry in recent:
                if (total_chars + entry.char_count) > budget:
                    break
                parts.append(
                    f"<recent-message>\n{entry.content}\n</recent-message>"
                )
                total_chars += entry.char_count

        if not parts:
            return None

        header = "## Recalled Memory\n"
        body = "\n\n".join(parts)
        return f"{header}\n{body}"

    # ------------------------------------------------------------------
    # Memory flush (pre-compaction)
    # ------------------------------------------------------------------

    def flush_to_long_term(
        self,
        content: str,
        *,
        heading: str = "Session Memory Flush",
    ) -> None:
        """Flush important information from short-term to long-term memory.

        Called before context compaction to preserve durable facts.

        Args:
            content: Text to persist.
            heading: Section heading in MEMORY.md.
        """
        from service.memory.sync_async_bridge import run_coro_sync
        run_coro_sync(self._ltm_append(content, heading=heading))
        logger.info(
            "Memory flush: %d chars saved to long-term memory", len(content)
        )

    def auto_flush(self, recent_n: int = 30) -> Optional[str]:
        """Generate a structured session-end summary for long-term storage.

        Called during session cleanup. Instead of dumping raw transcript,
        produces a concise session summary with conversation statistics
        that is useful for future memory recall.

        Skipped entirely when LTM is disabled in config.

        Args:
            recent_n: Number of recent messages to include excerpts from.

        Returns:
            The flushed text, or None if nothing to flush.
        """
        # Guard: skip when long-term memory is disabled in config
        from service.config.sub_config.general.ltm_config import LTMConfig

        if not LTMConfig.is_enabled():
            logger.debug("auto_flush: LTM disabled by config — skipping")
            return None

        from service.memory.sync_async_bridge import run_coro_sync

        now = datetime.now(_get_tz())
        all_entries = run_coro_sync(self._stm_load_all())
        if not all_entries:
            return None

        # --- Gather statistics ---
        user_msgs = [e for e in all_entries if "[user]" in e.content.lower()]
        assistant_msgs = [e for e in all_entries if "[assistant]" in e.content.lower()]
        total_chars = sum(e.char_count for e in all_entries)

        # First and last timestamps
        timestamps = [e.timestamp for e in all_entries if e.timestamp]
        first_ts = min(timestamps) if timestamps else None
        last_ts = max(timestamps) if timestamps else None

        duration_str = ""
        if first_ts and last_ts:
            delta = last_ts - first_ts
            total_minutes = int(delta.total_seconds() / 60)
            if total_minutes >= 60:
                duration_str = f"{total_minutes // 60}h {total_minutes % 60}m"
            else:
                duration_str = f"{total_minutes}m"

        # --- Build summary ---
        lines: list[str] = []
        lines.append("### 📋 Session End Summary")
        lines.append("")

        metrics = [f"**Messages:** {len(all_entries)} total"]
        metrics.append(
            f"({len(user_msgs)} user, {len(assistant_msgs)} assistant)"
        )
        if duration_str:
            metrics.append(f"| **Duration:** {duration_str}")
        metrics.append(f"| **Total chars:** {total_chars:,}")
        lines.append(" ".join(metrics))
        lines.append("")

        # Conversation flow: list user requests as bullet points
        if user_msgs:
            lines.append("**Conversation Flow:**")
            for i, entry in enumerate(user_msgs, 1):
                # Extract just the content (strip [user] prefix)
                content = entry.content
                if content.lower().startswith("[user] "):
                    content = content[7:]
                preview = content[:150]
                if len(content) > 150:
                    preview += "..."
                ts_str = ""
                if entry.timestamp:
                    ts_str = f"[{entry.timestamp.strftime('%H:%M')}] "
                lines.append(f"{i}. {ts_str}{preview}")

                # Limit to 20 entries for readability
                if i >= 20:
                    remaining = len(user_msgs) - 20
                    if remaining > 0:
                        lines.append(f"   ... +{remaining} more requests")
                    break
            lines.append("")

        summary_text = "\n".join(lines)

        if len(summary_text) < 50:
            return None  # Too short to bother

        # Save to today's executions file (was the daily-journal
        # root file pre-cycle-20260503_5 — same content shape, new
        # location to keep daily-journal index pure).
        run_coro_sync(self._ltm_write_execution(summary_text))

        # The L1 injection slot (read_summary) now gets the SEMANTIC rolling digest
        # (compressed-first), NOT this mechanical transcript list. At session close
        # we also fold the durable L3 evergreen. The mechanical text still lands in
        # the executions LTM archive above for the raw record.
        run_coro_sync(self.compact_now(evergreen=True))

        # Vector store flushes on every write (executor file backend);
        # nothing extra to do here on auto_flush.

        logger.info(
            "auto_flush: mechanical archive + semantic rolling digest (%d messages)",
            len(all_entries),
        )
        return summary_text

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> MemoryStats:
        """Compute memory statistics.

        Uses DB aggregation when available for efficiency;
        falls back to loading all entries from file.
        """
        from service.memory.sync_async_bridge import run_coro_sync

        # Try lightweight DB aggregation first
        if self._db_manager is not None and self._session_id is not None:
            try:
                from service.database.memory_db_helper import db_memory_stats

                db_stats = db_memory_stats(self._db_manager, self._session_id)
                if db_stats is not None:
                    last_write = None
                    ts_str = db_stats.get("last_write")
                    if ts_str:
                        try:
                            last_write = datetime.fromisoformat(ts_str)
                        except (ValueError, TypeError):
                            pass

                    # Add structured stats from index
                    categories: Dict[str, int] = {}
                    total_tags = 0
                    total_links = 0
                    if self._memory_provider is not None:
                        idx = run_coro_sync(self._index_snapshot())
                        for info in idx.files.values():
                            cat = info.category or "root"
                            categories[cat] = categories.get(cat, 0) + 1
                        total_tags = len(idx.tag_map)
                        total_links = sum(
                            len(info.links_to) for info in idx.files.values()
                        )

                    return MemoryStats(
                        long_term_entries=db_stats.get("long_term_entries", 0),
                        short_term_entries=db_stats.get("short_term_entries", 0),
                        long_term_chars=db_stats.get("long_term_chars", 0),
                        short_term_chars=db_stats.get("short_term_chars", 0),
                        total_files=db_stats.get("total_files", 0),
                        last_write=last_write,
                        categories=categories,
                        total_tags=total_tags,
                        total_links=total_links,
                    )
            except Exception:
                pass

        # Fallback: load all entries from file system
        ltm_entries = self._ltm_load_all()
        stm_entries = run_coro_sync(self._stm_load_all())

        ltm_chars = sum(e.char_count for e in ltm_entries)
        stm_chars = sum(e.char_count for e in stm_entries)

        all_timestamps = [
            e.timestamp for e in ltm_entries + stm_entries
            if e.timestamp is not None
        ]
        last_write = max(all_timestamps) if all_timestamps else None

        # Structured stats from index
        categories: Dict[str, int] = {}
        total_tags = 0
        total_links = 0
        if self._memory_provider is not None:
            idx = run_coro_sync(self._index_snapshot())
            for info in idx.files.values():
                cat = info.category or "root"
                categories[cat] = categories.get(cat, 0) + 1
            total_tags = len(idx.tag_map)
            total_links = sum(len(info.links_to) for info in idx.files.values())

        return MemoryStats(
            long_term_entries=len(ltm_entries),
            short_term_entries=len(stm_entries),
            long_term_chars=ltm_chars,
            short_term_chars=stm_chars,
            total_files=len(ltm_entries),
            last_write=last_write,
            categories=categories,
            total_tags=total_tags,
            total_links=total_links,
        )


# ─────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────


