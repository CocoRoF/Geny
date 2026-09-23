"""Conversation archiver — counterpart-aware session-rollup writer.

Cycle 20260503_5 (Memory v2 PR 13 → PR 14 follow-up).

The archiver originally wrote **one file per turn** which produced
hundreds of files per session. PR 13 collapsed that to **one file
per session**. That fixed the file count but mixed three different
kinds of content — user_chat, agent reflection, and (eventually)
sub-worker DMs — into a single rollup, which violated the
operator's mental model ("conversations are split by who you talked
to") and made search results confusingly mix the user's own words
with the agent's internal monologue.

This revision ships **counterpart-aware rollup**: each session
produces *one file per (kind-bucket × counterpart)* under

    memory/conversations/<sid>__user__<title_slug>.md   ← user_chat
    memory/conversations/<sid>__reflection.md           ← reflection / internal_trigger
    memory/conversations/<sid>__dm__<cp_safe>.md        ← DM-class kinds, one per counterpart
    memory/conversations/<sid>__system.md               ← system_note

and every recorded turn becomes an H2 anchor inside the matching
file::

    ---
    title: ...
    category: conversations
    session_id: <id>
    date_first: 2026-05-03
    date_last: 2026-05-03
    turn_count: 7
    event_ids: [eid8, eid8, ...]
    kinds: [user_chat, assistant_chat, reflection]
    counterparts: [owner:gkfua00]
    importance_max: high
    tags: [conversation, user_chat, assistant_chat, ...]
    links_to: [2026-05-03, dms/owner_gkfua00/2026-05-03]
    linked_from: []
    ---

    # <title>

    ## turn-0e1c4dff

    <!--meta
    event_id: 0e1c4dff-...
    ts: 2026-05-03T08:48:49+09:00
    kind: user_chat
    direction: in
    counterpart: owner:gkfua00
    counterpart_role: user
    role: user_chat
    importance: medium
    content_chars: 12
    linked_event_id:
    -->

    [body verbatim — same render as the legacy per-turn file]

    ---

    ## turn-a8d9d03e
    ...

The wikilink target consumer (``dm_archiver``) keeps working
unchanged: its ``.md``-strip is now a no-op because
:attr:`ArchivedConversation.relative_path` already returns the
wikilink-friendly form ``conversations/<sid>__<bucket>#turn-<eid8>``
(no extension, anchor included). Operators clicking the link in
Obsidian/Opsidian land exactly on the per-turn heading.

Cycle 20260503_6 — the legacy ``daily_journal_writer`` has been
retired; the conversations rollup files carry every turn with
``date_first/date_last`` in frontmatter, so the standalone
``memory/<YYYY-MM-DD>.md`` headline index was redundant.

Concrete invariants the rest of Memory v2 depends on:

  1. **One session = one file.** Subsequent turns *append* an H2
     anchor; the file's frontmatter is updated atomically (read →
     mutate → write-tempfile-then-rename) so concurrent writers in
     the same session can't interleave half-written blocks.
  2. **Filename is fixed at first archive.** The ``title_slug`` is
     derived from the first user-side body (or falls back to the
     session-id prefix) and never changes after — keeps the
     wikilink target stable across the session lifetime.
  3. **Body never truncates.** The whole content survives as-is in
     the per-turn block; the STM jsonl mirror still applies its
     own cap independently.
  4. **Importance is computed, not asked** (unchanged from the
     per-turn era — see :func:`compute_importance`).
  5. **Frontmatter is roll-up.** The session-level keys aggregate
     across turns: ``importance_max`` is the max across all turns,
     ``kinds``/``counterparts``/``tags``/``event_ids`` are deduped
     unions, ``date_last`` is the latest turn ts, ``turn_count``
     is the running count.

The legacy per-turn helpers (``filename_for``, ``build_title``,
``build_frontmatter``, ``build_body``) are kept as **module-level
exports for the migration script and tests** — their logic feeds
the per-turn block renderer. Direct callers that want the legacy
layout should pin geny / scripts to before this change.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from service.memory.interaction_event import (
    Direction,
    InteractionEventView,
    Kind,
    parse_event_metadata,
)
from service.utils.utils import _configured_tz as _get_tz

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────

#: Top-level category slug. Must match the entry in
#: ``service.memory.structured_writer.VALID_CATEGORIES``.
CATEGORY = "conversations"

#: Default short-event-id width for anchor ids. 8 hex chars give
#: ~4 billion combinations per session — collisions are theoretically
#: possible but in practice never materialise within one session.
EID_WIDTH_DEFAULT = 8
EID_WIDTH_MAX = 32  # full uuid hex

#: Counterpart ids that don't represent an external party — wikilinks
#: to ``dms/<x>`` are not generated for these.
_SELF_LIKE_COUNTERPARTS = frozenset({"self", "system", "", "unknown"})

#: Kinds that warrant a ``dms/<cp>/<date>`` wikilink in
#: ``links_to``. Mirrors the kind set the dm_archiver uses for
#: per-counterpart-per-day index bundling.
_DM_KINDS = frozenset({
    Kind.DM.value,
    Kind.TASK_REQUEST.value,
    Kind.TASK_RESULT.value,
    Kind.TOOL_RUN_SUMMARY.value,
})

#: A rotated archive's stem: ``<live stem>.<NNN>.archive`` (possibly nested
#: by the pre-fix rotation bug). See ``_locate_or_initialise``.
_ARCHIVE_STEM = re.compile(r"\.\d{3}\.archive(?:\.|$)")

#: Sanitiser for path / filename components.
_PATH_SAFE_RE = re.compile(r"[^A-Za-z0-9_\-]")

#: Heuristic thresholds for :func:`compute_importance`.
LONG_BODY_THRESHOLD = 5_000
SHORT_BODY_THRESHOLD = 50

#: Title prefix length for non-payload kinds. Body's first non-empty
#: line is summarised down to this many chars in the per-turn meta
#: block.
TITLE_PREFIX_CHARS = 80

#: Maximum number of characters the *session title* slug consumes.
#: Tight enough that the on-disk filename remains comfortably under
#: 255 bytes after combining with the session-id slug.
SESSION_TITLE_SLUG_MAX = 60

#: Maximum number of characters the *session id slug* consumes.
SESSION_ID_SLUG_MAX = 24

#: Importance ladder for ``importance_max`` aggregation. Higher
#: index = more critical.
_IMPORTANCE_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_IMPORTANCE_NAME = {v: k for k, v in _IMPORTANCE_RANK.items()}

#: Per-turn meta block delimiters. HTML comments so Obsidian /
#: vault rendering ignores them while machine consumers (the
#: migration helper, future inspection tools) can still parse.
_TURN_META_OPEN = "<!--meta"
_TURN_META_CLOSE = "-->"

#: Regex used by the migration script (and tests) to enumerate
#: turn blocks inside a rollup file.
_TURN_BLOCK_RE = re.compile(
    r"^## turn-(?P<eid>[0-9a-f]+)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────
# Public dataclass
# ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ArchivedConversation:
    """Result of a successful :meth:`ConversationArchiver.archive` call.

    Returned to callers (``record_message``) so they can stamp
    ``payload.conversation_ref`` on the STM jsonl line — this is
    the pointer the Stream tab follows when an operator clicks an
    event row.

    With session rollup, ``relative_path`` carries the **wikilink
    target** form (no ``.md`` suffix, anchor included), e.g.
    ``conversations/sid_xxx__title#turn-0e1c4dff``. The
    ``absolute_path`` is the on-disk markdown file (with ``.md``).
    """

    relative_path: str   # e.g. "conversations/sid_xxx__title#turn-0e1c4dff"
    absolute_path: str   # e.g. "/.../memory/conversations/sid_xxx__title.md"
    importance: str
    event_id: str


# ─────────────────────────────────────────────────────────────────
# Importance heuristic
# ─────────────────────────────────────────────────────────────────


def compute_importance(
    *,
    kind: str,
    content_chars: int,
    payload: Optional[Dict[str, Any]],
) -> str:
    """Map a turn to ``low | medium | high | critical``.

    Same rules as the per-turn era so importance values round-trip
    across the migration:

      * ``critical`` — ``kind == system_note`` AND payload reports
        at least one error.
      * ``high``     — ``kind == task_result`` AND files_written≥1,
                      OR content_chars > 5000,
                      OR payload reports errors.
      * ``low``      — ``kind ∈ {reflection, internal_trigger}`` or
                      content_chars < 50.
      * ``medium``   — anything else.
    """
    payload = payload or {}
    errors = payload.get("errors") or []
    files_written = payload.get("files_written") or []
    has_errors = bool(errors)

    if kind == Kind.SYSTEM_NOTE.value and has_errors:
        return "critical"

    if kind == Kind.TASK_RESULT.value and len(files_written) >= 1:
        return "high"
    if content_chars > LONG_BODY_THRESHOLD:
        return "high"
    if has_errors:
        return "high"

    if kind in (Kind.REFLECTION.value, "internal_trigger"):
        return "low"
    if content_chars < SHORT_BODY_THRESHOLD:
        return "low"

    return "medium"


# ─────────────────────────────────────────────────────────────────
# Slug / filename helpers
# ─────────────────────────────────────────────────────────────────


def sanitize_counterpart(counterpart_id: str) -> str:
    """Strip a counterpart id to a path-safe slug.

    Owner ids like ``owner:gkfua00`` collapse to ``owner_gkfua00``;
    UUIDs stay intact.
    """
    cleaned = _PATH_SAFE_RE.sub("_", counterpart_id or "unknown")
    return cleaned[:80] or "unknown"


def short_event_id(event_id: str, *, width: int = EID_WIDTH_DEFAULT) -> str:
    """Truncate a uuid hex to ``width`` chars. ``width`` is clamped
    to ``[1, EID_WIDTH_MAX]``.
    """
    eid = (event_id or "").strip()
    if not eid:
        eid = "00000000"
    return eid[: max(1, min(EID_WIDTH_MAX, width))]


def _slug_for_session_id(session_id: str) -> str:
    """Compress a session id into a filename component.

    Session ids in Geny look like UUIDs; the leading 24 hex chars
    are uniqueness-sufficient and keep the filename short. Empty
    input degrades to ``unknown`` so the writer never produces an
    empty slug.
    """
    cleaned = _PATH_SAFE_RE.sub("_", session_id or "unknown")
    cleaned = cleaned[:SESSION_ID_SLUG_MAX] or "unknown"
    return cleaned


def _slug_for_title(title: str) -> str:
    """Convert a free-form title into a filename component.

    Lowercases Latin scripts, keeps Hangul + digits + ``-_``, collapses
    runs of whitespace/underscore to ``-``, caps at
    ``SESSION_TITLE_SLUG_MAX``.
    """
    if not title:
        return ""
    raw = title.lower().strip()
    raw = re.sub(r"[^a-z0-9가-힣\s_-]", "", raw)
    raw = re.sub(r"[\s_]+", "-", raw)
    raw = raw.strip("-")
    return raw[:SESSION_TITLE_SLUG_MAX]


def session_filename_for(
    *,
    session_id: str,
    bucket_path: str,
) -> str:
    """Return the relative path for a session rollup file.

    Shape: ``conversations/<sid_slug>__<bucket_path>.md``.

    ``bucket_path`` is the bucket-specific suffix produced by
    :func:`bucket_path_for`. Examples::

        sid_abc__user__안녕               # user_chat with title slug
        sid_abc__user                      # user_chat with no usable title
        sid_abc__reflection                # reflection / internal_trigger
        sid_abc__dm__owner_gkfua00         # DM with one counterpart
        sid_abc__system                    # system_note
    """
    sid = _slug_for_session_id(session_id)
    return f"{CATEGORY}/{sid}__{bucket_path}.md"


# ─────────────────────────────────────────────────────────────────
# Bucket resolution (Memory v2 PR 14 — counterpart-aware split)
# ─────────────────────────────────────────────────────────────────

#: Bucket discriminator returned by :func:`resolve_bucket`. Used as
#: a stable key for file caching and bucket-aware policy (titles,
#: importance ladders, …).
class Bucket:
    USER = "user"
    REFLECTION = "reflection"
    DM = "dm"
    SYSTEM = "system"


def resolve_bucket(
    *,
    kind: str,
    counterpart_id: Optional[str],
) -> Tuple[str, str]:
    """Map a turn's ``(kind, counterpart_id)`` to ``(bucket, base_slug)``.

    ``base_slug`` is the bucket-specific portion of the filename
    BEFORE any title slug is appended. The user bucket appends
    ``__<title_slug>`` later (when one can be derived); the others
    keep the base alone.
    """
    if kind in (Kind.REFLECTION.value, "internal_trigger"):
        return Bucket.REFLECTION, "reflection"
    if kind == Kind.SYSTEM_NOTE.value:
        return Bucket.SYSTEM, "system"
    if kind in _DM_KINDS:
        cp = (counterpart_id or "").strip()
        if not cp or cp in _SELF_LIKE_COUNTERPARTS:
            # DM-shaped kind without an external counterpart — bucket
            # it under "system" so it doesn't blow up "dm__unknown"
            # files.
            return Bucket.SYSTEM, "system"
        return Bucket.DM, f"dm__{sanitize_counterpart(cp)}"
    # Default: anything not explicitly bucketed is treated as user
    # chat. This includes ``user_chat`` (the common case) and any
    # future kind we forget to enumerate — better to land in the
    # user bucket than to silently lose the turn.
    return Bucket.USER, "user"


def bucket_path_for(
    *,
    bucket: str,
    base_slug: str,
    title_slug: str,
) -> str:
    """Compose the final bucket-specific filename suffix.

    Only the user bucket carries an optional title slug; the rest
    use ``base_slug`` alone so their filenames stay stable across
    the session lifetime.
    """
    if bucket == Bucket.USER and title_slug:
        return f"{base_slug}__{title_slug}"
    return base_slug


# ── Legacy per-turn helpers (kept for migration + tests) ──────────


def filename_for(
    *,
    ts: datetime,
    role: str,
    event_id: str,
    eid_width: int = EID_WIDTH_DEFAULT,
) -> Tuple[str, str]:
    """Legacy per-turn filename layout.

    .. deprecated:: PR 13 — session rollup is now the default. This
        helper survives so the migration script can recompute
        legacy paths when walking old vaults; new writes do not
        call it.
    """
    safe_role = _PATH_SAFE_RE.sub("_", role or "unknown") or "unknown"
    date = ts.date().isoformat()
    name = (
        f"{ts.strftime('%H-%M-%S')}__{safe_role}__"
        f"{short_event_id(event_id, width=eid_width)}.md"
    )
    return date, name


# ─────────────────────────────────────────────────────────────────
# Body / heading builders
# ─────────────────────────────────────────────────────────────────


def build_title(
    *,
    kind: str,
    direction: str,
    counterpart_id: Optional[str],
    content: str,
) -> str:
    """Compose a one-line title for the per-turn meta block.

    Same shape as the legacy per-turn frontmatter title — keeps the
    StreamTab event row excerpt and the migration round-trip
    bit-for-bit identical.
    """
    arrow = _direction_arrow(direction)
    cp_short = (counterpart_id or "")[:8] if counterpart_id else ""
    cp_part = f" {arrow} {cp_short}" if cp_short else ""
    prefix = f"[{kind}{cp_part}]"

    body_head = ""
    for line in (content or "").splitlines():
        line = line.strip()
        if line:
            body_head = line[:TITLE_PREFIX_CHARS]
            if len(line) > TITLE_PREFIX_CHARS:
                body_head = body_head.rstrip() + "…"
            break

    if body_head:
        return f"{prefix} {body_head}"
    return prefix


def _direction_arrow(direction: str) -> str:
    if direction == Direction.OUT.value:
        return "→"
    if direction == Direction.IN.value:
        return "←"
    return "·"


def build_links_to(
    *,
    kind: str,
    counterpart_id: Optional[str],
    date: str,
) -> List[str]:
    """Compute the standard wikilink targets for a conversations note.

    Cycle 20260503_6 — the daily-journal target was retired alongside
    ``DailyJournalWriter`` (the per-day file was a redundant
    headline index). DM-class kinds still link out to the
    per-counterpart bundle so dm vault navigation keeps working.
    Non-DM turns now have an empty ``links_to`` — the rollup file
    is self-contained and the chronological lookup happens via the
    index manager's ``date_first/date_last`` aggregates.
    """
    out: List[str] = []
    cp_id = (counterpart_id or "").strip()
    if cp_id and cp_id not in _SELF_LIKE_COUNTERPARTS:
        cp_safe = sanitize_counterpart(cp_id)
        if kind in _DM_KINDS:
            out.append(f"dms/{cp_safe}/{date}")
    return out


def build_tags(*, kind: str, counterpart_role: Optional[str]) -> List[str]:
    """Standard tag set: ``conversation`` always, then kind, then
    counterpart_role (if any).
    """
    tags = ["conversation", kind]
    if counterpart_role:
        tags.append(counterpart_role)
    return [t.lower() for t in tags if t]


def build_frontmatter(
    *,
    title: str,
    ts: datetime,
    event_id: str,
    role: str,
    kind: str,
    direction: str,
    counterpart_id: Optional[str],
    counterpart_role: Optional[str],
    linked_event_id: Optional[str],
    session_id: str,
    content_chars: int,
    importance: str,
    tags: Iterable[str],
    links_to: Iterable[str],
) -> Dict[str, Any]:
    """Produce the legacy 17-key per-turn frontmatter dict.

    .. deprecated:: PR 13 — session rollup uses
        :func:`build_session_frontmatter` and per-turn HTML comment
        meta blocks. This helper survives for migration tests that
        re-read legacy per-turn files.
    """
    return {
        "title": title,
        "category": CATEGORY,
        "date": ts.date().isoformat(),
        "ts": ts.isoformat(),
        "event_id": event_id,
        "role": role,
        "kind": kind,
        "direction": direction,
        "counterpart": counterpart_id or "",
        "counterpart_role": counterpart_role or "",
        "linked_event_id": linked_event_id or "",
        "session_id": session_id,
        "content_chars": int(content_chars),
        "tags": list(tags),
        "importance": importance,
        "links_to": list(links_to),
        "linked_from": [],
    }


def build_session_frontmatter(
    *,
    session_id: str,
    title: str,
    date_first: str,
    date_last: str,
    turn_count: int,
    event_ids: Iterable[str],
    kinds: Iterable[str],
    counterparts: Iterable[str],
    importance_max: str,
    tags: Iterable[str],
    links_to: Iterable[str],
) -> Dict[str, Any]:
    """Produce the session-level frontmatter dict used by the
    rollup file. Stable across a session's lifetime — the title is
    set on first archive and never changes; the rest is recomputed
    every append from the union of turn blocks.
    """
    return {
        "title": title,
        "category": CATEGORY,
        "session_id": session_id,
        "date_first": date_first,
        "date_last": date_last,
        "turn_count": int(turn_count),
        "event_ids": list(event_ids),
        "kinds": list(kinds),
        "counterparts": list(counterparts),
        "importance_max": importance_max,
        "tags": list(tags),
        "links_to": list(links_to),
        "linked_from": [],
    }


def build_body(
    *,
    kind: str,
    direction: str,
    counterpart_id: Optional[str],
    counterpart_role: Optional[str],
    content: str,
    payload: Optional[Dict[str, Any]],
    linked_event_id: Optional[str],
    links_to: List[str],
) -> str:
    """Render the per-turn body — shape is unchanged from the legacy
    per-turn era so users reading either form see the same prose.

    Two shapes:

      * ``tool_run_summary`` / ``task_result`` with payload — a
        structured block (status, tools, files, duration, cost) plus
        the raw body and a JSON-fenced payload dump.
      * everything else — heading + raw content.
    """
    arrow = _direction_arrow(direction)
    cp_short = (counterpart_id or "")[:8] if counterpart_id else ""
    role_part = f" ({counterpart_role})" if counterpart_role else ""
    heading_target = f" {arrow} {cp_short}{role_part}" if cp_short else f"{role_part}"
    heading = f"### {kind}{heading_target}"

    parts: List[str] = [heading, ""]

    if payload and kind in (Kind.TOOL_RUN_SUMMARY.value, Kind.TASK_RESULT.value):
        parts.extend(_render_tool_block(payload))
        parts.append("#### Body")
        parts.append("")
        parts.append(content.rstrip("\n"))
        parts.append("")
        parts.append("#### Raw payload")
        parts.append("```json")
        parts.append(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        parts.append("```")
    else:
        parts.append(content.rstrip("\n"))

    if linked_event_id:
        parts.append("")
        parts.append(f"_↳ Linked event: `{linked_event_id}`_")

    return "\n".join(parts).rstrip() + "\n"


def _render_tool_block(payload: Dict[str, Any]) -> List[str]:
    """One-page summary of a tool run payload."""
    status = payload.get("status", "?")
    tools_used = payload.get("tools_used") or []
    files_written = payload.get("files_written") or []
    files_read = payload.get("files_read") or []
    bash_commands = payload.get("bash_commands") or []
    web_fetches = payload.get("web_fetches") or []
    errors = payload.get("errors") or []
    duration_ms = payload.get("duration_ms")
    cost_usd = payload.get("cost_usd")
    total_calls = payload.get("total_calls")
    ok_calls = payload.get("ok_calls")
    failed_calls = payload.get("failed_calls")

    out: List[str] = []
    out.append(f"**Status:** {status}")
    if tools_used:
        tool_summary = ", ".join(sorted(set(tools_used)))
        if total_calls is not None and ok_calls is not None and failed_calls is not None:
            out.append(
                f"**Tools:** {tool_summary} "
                f"({total_calls} call{'s' if total_calls != 1 else ''} · "
                f"{ok_calls} ok / {failed_calls} failed)"
            )
        else:
            out.append(f"**Tools:** {tool_summary}")
    if files_written:
        out.append("**Files written:**")
        for f in files_written:
            out.append(f"- `{f}`")
    if files_read:
        out.append("**Files read:**")
        for f in files_read:
            out.append(f"- `{f}`")
    if bash_commands:
        out.append(f"**Bash commands:** {len(bash_commands)}")
    if web_fetches:
        out.append(f"**Web fetches:** {len(web_fetches)}")
    if errors:
        out.append(f"**Errors:** {len(errors)}")
        for e in errors[:3]:
            out.append(f"- `{e}`")
    if duration_ms is not None:
        out.append(f"**Duration:** {int(duration_ms) / 1000:.1f}s")
    if cost_usd is not None:
        out.append(f"**Cost:** ${float(cost_usd):.4f}")
    out.append("")
    return out


# ─────────────────────────────────────────────────────────────────
# Per-turn anchor rendering
# ─────────────────────────────────────────────────────────────────


def _render_meta_block(
    *,
    event_id: str,
    ts: datetime,
    role: str,
    kind: str,
    direction: str,
    counterpart_id: Optional[str],
    counterpart_role: Optional[str],
    importance: str,
    content_chars: int,
    linked_event_id: Optional[str],
) -> str:
    """Render the per-turn ``<!--meta ... -->`` block.

    The block carries the same dimensions the legacy per-turn
    frontmatter exposed; downstream tools (Stream tab inspector,
    memory_event lookup) can parse it line-by-line. Hidden from
    Obsidian preview because HTML comments don't render.
    """
    lines = [
        _TURN_META_OPEN,
        f"event_id: {event_id}",
        f"ts: {ts.isoformat()}",
        f"kind: {kind}",
        f"direction: {direction}",
        f"counterpart: {counterpart_id or ''}",
        f"counterpart_role: {counterpart_role or ''}",
        f"role: {role}",
        f"importance: {importance}",
        f"content_chars: {int(content_chars)}",
        f"linked_event_id: {linked_event_id or ''}",
        _TURN_META_CLOSE,
    ]
    return "\n".join(lines)


def render_turn_block(
    *,
    eid8: str,
    event_id: str,
    ts: datetime,
    role: str,
    kind: str,
    direction: str,
    counterpart_id: Optional[str],
    counterpart_role: Optional[str],
    importance: str,
    content_chars: int,
    linked_event_id: Optional[str],
    body: str,
) -> str:
    """Compose one anchored block: ``## turn-<eid8>`` + meta + body.

    Always trailing-separator-friendly so ``"\\n\\n".join(blocks)``
    produces a valid roll-up document.
    """
    parts = [
        f"## turn-{eid8}",
        "",
        _render_meta_block(
            event_id=event_id,
            ts=ts,
            role=role,
            kind=kind,
            direction=direction,
            counterpart_id=counterpart_id,
            counterpart_role=counterpart_role,
            importance=importance,
            content_chars=content_chars,
            linked_event_id=linked_event_id,
        ),
        "",
        body.rstrip(),
    ]
    return "\n".join(parts).rstrip() + "\n"


# ─────────────────────────────────────────────────────────────────
# Title resolution (chosen on first archive, then frozen)
# ─────────────────────────────────────────────────────────────────


_MD_HEADING_RE = re.compile(r"^#+\s")


def _first_meaningful_line(content: str) -> str:
    """Return the first non-empty, non-markdown-heading line of
    ``content`` capped at the session-title length. Used to seed
    the session title from a turn body.
    """
    for raw in (content or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if _MD_HEADING_RE.match(line):
            # Body's structural heading — not the session intent.
            continue
        return line[:SESSION_TITLE_SLUG_MAX].rstrip()
    return ""


def derive_session_title(
    *,
    bucket: str,
    counterpart_id: Optional[str],
    counterpart_role: Optional[str],
    content: str,
) -> str:
    """Pick the human-readable title for the bucket's rollup file.

    Per-bucket policy:

      - ``user``       — first non-heading line of the body. The
        operator's first message is the most informative label.
      - ``reflection`` — fixed empty (the writer uses the bare
        ``__reflection`` filename). A trigger like
        ``[THINKING_TRIGGER:time_evening]`` would slugify to noise.
      - ``dm``         — counterpart role + short id. The role
        ("paired_subworker") is more recognisable than the UUID.
      - ``system``     — fixed empty.
    """
    if bucket == Bucket.USER:
        return _first_meaningful_line(content)
    if bucket == Bucket.DM:
        cp = (counterpart_id or "").strip()
        role = (counterpart_role or "").strip()
        if role and cp:
            return f"{role} {cp[:8]}"
        return cp[:24] if cp else ""
    # reflection / system / unknown
    return ""


# ─────────────────────────────────────────────────────────────────
# The archiver
# ─────────────────────────────────────────────────────────────────


class ConversationArchiver:
    """Session-rollup writer for ``memory/conversations/<sid>__<title>.md``.

    Construct one per session::

        archiver = ConversationArchiver(memory_dir, session_id="...")
        result = archiver.archive(role, content, metadata)

    The first ``archive`` call materialises the file with a
    session-level frontmatter and one anchored block. Subsequent
    calls append a new block and update the frontmatter aggregates.
    All disk mutations go through a per-session :class:`threading.RLock`
    so concurrent archive calls never interleave each other's
    payloads.
    """

    CATEGORY = CATEGORY  # re-exposed for callers

    def __init__(
        self,
        memory_dir: str,
        *,
        session_id: str = "",
        tz: Optional[tzinfo] = None,
        memory_provider=None,
    ) -> None:
        self._memory_dir = Path(memory_dir)
        self._session_id = session_id
        self._tz = tz or _get_tz()
        # Lock guards the read-mutate-write critical section so two
        # concurrent ``archive`` calls in the same session can't
        # produce torn files.
        import threading  # local import — keeps the eager import set lean
        self._lock = threading.RLock()
        # Sprint 3 step 4 — host-side index_manager parameter retired;
        # the executor's IndexHandle refreshes ``_index.json`` and the
        # per-category shards automatically on every NotesHandle.write
        # (1.20.0 EXEC-5).
        self._provider = memory_provider
        # Bucket → cached relative path. PR 14 split conversations by
        # ``(kind, counterpart)`` so each session can own up to one
        # ``user``, one ``reflection``, one ``system``, and N ``dm``
        # files. The cache key is the bucket's *base_slug* (i.e.
        # ``user`` / ``reflection`` / ``system`` / ``dm__<cp>``);
        # within ``user`` the title slug is appended once on first
        # archive so subsequent calls hit the cache directly.
        #
        # Initialised HERE, not in set_memory_provider: an archiver used
        # without a provider — or one whose wiring failed, which is
        # swallowed at the call site — would otherwise raise
        # AttributeError from archive() and set_session_id(), long after
        # construction and with nothing pointing back at the cause.
        self._cached_rel: Dict[str, str] = {}

    def set_memory_provider(self, provider) -> None:
        """Plug the executor `MemoryProvider` post-construction.

        With a provider attached, `_merge_to_disk` runs as a
        `NotesHandle.read → mutate frontmatter+body in memory →
        NotesHandle.write/update` round trip. The legacy direct
        atomic-write path stays as a provider-less fallback.
        """
        self._provider = provider
        # A provider change invalidates where files live.
        self._cached_rel.clear()

    def set_session_id(self, session_id: str) -> None:
        """Late-binding setter — used by ``SessionMemoryManager.
        set_database`` when a deployment surfaces the canonical
        session_id only after construction. Drops the cached file
        paths so the next archive picks the correct slug.
        """
        self._session_id = session_id or ""
        self._cached_rel.clear()

    @property
    def memory_dir(self) -> Path:
        return self._memory_dir

    @property
    def conversations_dir(self) -> Path:
        return self._memory_dir / CATEGORY

    # ── public API ───────────────────────────────────────────────

    def archive(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]],
    ) -> Optional[ArchivedConversation]:
        """Append one turn to the session rollup file.

        Returns ``None`` for legacy metadata (missing the canonical
        InteractionEvent keys) — caller should treat it as
        "skip; the STM jsonl line stands alone".
        """
        view = parse_event_metadata(metadata)
        if view is None:
            return None
        return self._archive_view(role, content, view)

    # ── internal ─────────────────────────────────────────────────

    def _archive_view(
        self,
        role: str,
        content: str,
        view: InteractionEventView,
    ) -> Optional[ArchivedConversation]:
        ts = self._resolve_ts(view.metadata)
        content = content if isinstance(content, str) else ""
        content_chars = len(content)
        payload = view.payload or None

        importance = compute_importance(
            kind=view.kind, content_chars=content_chars, payload=payload,
        )
        date_iso = ts.date().isoformat()
        links_to_for_turn = build_links_to(
            kind=view.kind, counterpart_id=view.counterpart_id, date=date_iso,
        )
        tags_for_turn = build_tags(
            kind=view.kind, counterpart_role=view.counterpart_role,
        )

        body = build_body(
            kind=view.kind,
            direction=view.direction,
            counterpart_id=view.counterpart_id,
            counterpart_role=view.counterpart_role,
            content=content,
            payload=payload,
            linked_event_id=view.linked_event_id,
            links_to=links_to_for_turn,
        )

        eid8 = short_event_id(view.event_id, width=EID_WIDTH_DEFAULT)
        turn_block = render_turn_block(
            eid8=eid8,
            event_id=view.event_id,
            ts=ts,
            role=role,
            kind=view.kind,
            direction=view.direction,
            counterpart_id=view.counterpart_id,
            counterpart_role=view.counterpart_role,
            importance=importance,
            content_chars=content_chars,
            linked_event_id=view.linked_event_id,
            body=body,
        )

        # Bucket routing — kind + counterpart pick the rollup file.
        bucket, base_slug = resolve_bucket(
            kind=view.kind, counterpart_id=view.counterpart_id,
        )

        # Title only seeds the user bucket's filename; other buckets
        # use ``base_slug`` alone (see ``bucket_path_for``).
        derived_title = derive_session_title(
            bucket=bucket,
            counterpart_id=view.counterpart_id,
            counterpart_role=view.counterpart_role,
            content=content,
        )

        rel_md = self._merge_to_disk(
            ts=ts,
            view=view,
            tags_for_turn=tags_for_turn,
            links_for_turn=links_to_for_turn,
            importance=importance,
            eid8=eid8,
            bucket=bucket,
            base_slug=base_slug,
            derived_title_seed=derived_title,
            turn_block=turn_block,
        )
        if rel_md is None:
            return None

        # Wikilink target carries the anchor and drops the .md ext.
        rel_no_ext = rel_md[:-3] if rel_md.endswith(".md") else rel_md
        rel_with_anchor = f"{rel_no_ext}#turn-{eid8}"
        return ArchivedConversation(
            relative_path=rel_with_anchor,
            absolute_path=str(self._memory_dir / rel_md),
            importance=importance,
            event_id=view.event_id,
        )

    def _resolve_ts(self, metadata: Dict[str, Any]) -> datetime:
        """Pick a timestamp for the turn (prefer event-supplied)."""
        raw = metadata.get("ts")
        if isinstance(raw, str) and raw:
            try:
                parsed = datetime.fromisoformat(raw)
                return parsed.astimezone(self._tz) if parsed.tzinfo else parsed.replace(tzinfo=self._tz)
            except ValueError:
                pass
        return datetime.now(self._tz)

    # ── disk merge ───────────────────────────────────────────────

    def _merge_to_disk(
        self,
        *,
        ts: datetime,
        view: InteractionEventView,
        tags_for_turn: List[str],
        links_for_turn: List[str],
        importance: str,
        eid8: str,
        bucket: str,
        base_slug: str,
        derived_title_seed: str,
        turn_block: str,
    ) -> Optional[str]:
        """Read the existing rollup file for this bucket (if any),
        append the new turn block, recompute the session-level
        frontmatter, and write atomically. Returns the relative
        ``.md`` path on success.
        """
        try:
            self.conversations_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "conversation_archiver: mkdir failed for %s: %s",
                self.conversations_dir, exc,
            )
            return None

        with self._lock:
            target_rel, target_abs, existing_meta, existing_body = (
                self._locate_or_initialise(
                    bucket=bucket,
                    base_slug=base_slug,
                    derived_title_seed=derived_title_seed,
                )
            )
            if target_rel is None:
                return None

            new_body = _append_turn_block(existing_body, eid8, turn_block)

            # Idempotency: if the anchor already lived inside
            # ``existing_body``, ``_append_turn_block`` is a no-op
            # and we must not bump ``turn_count`` / ``event_ids``
            # / aggregates in the frontmatter — re-archiving the
            # same event is supposed to be a literal no-op on disk
            # so a crash-restart that replays a turn doesn't
            # double-count.
            if new_body == (existing_body or ""):
                return target_rel

            new_meta = self._merge_frontmatter(
                existing_meta=existing_meta,
                bucket=bucket,
                derived_title_seed=derived_title_seed,
                ts=ts,
                view=view,
                tags_for_turn=tags_for_turn,
                links_for_turn=links_for_turn,
                importance=importance,
                eid8=eid8,
            )

            if self._provider is None:
                logger.warning(
                    "conversation_archiver: no MemoryProvider attached; "
                    "skipping rollup write for %s",
                    target_rel,
                )
                return None
            if not self._write_via_provider(
                target_rel=target_rel,
                target_abs=target_abs,
                new_meta=new_meta,
                new_body=new_body,
                is_new_file=(not existing_body and not existing_meta),
            ):
                return None
            # Sprint 3 step 4 — index update is owned by the executor's
            # IndexHandle and fires inside ``NotesStore.write``.
            return target_rel

    def _write_via_provider(
        self,
        *,
        target_rel: str,
        target_abs: str,
        new_meta: Dict[str, Any],
        new_body: str,
        is_new_file: bool,
    ) -> bool:
        """Write the merged frontmatter+body via NotesHandle.

        - ``is_new_file=True``: NoteDraft via `notes.write`.
        - else: NotePatch via `notes.update`.

        Returns True on success, False on routing failure (logged at
        WARNING). Geny's bucket / filename / merge logic stays
        authoritative — this method only translates the resulting
        meta dict + body string into NoteDraft/NotePatch shape.
        """
        try:
            from geny_executor.memory.provider import (
                Importance as _Importance,
                NoteDraft,
                NotePatch,
                Scope,
            )
            from service.memory.sync_async_bridge import run_coro_sync

            notes = self._provider.notes()

            # Archive rotation: when a rollup file outgrows the cap, move its
            # older half to a numbered archive note (raw preserved — "원본 보관")
            # and keep only the recent tail live. Bounds the file Opsidian renders
            # + the executor reads; the rolling digest already holds the gist.
            new_body = self._maybe_rotate_body(
                notes=notes,
                run_coro_sync=run_coro_sync,
                target_rel=target_rel,
                new_meta=new_meta,
                new_body=new_body,
            )

            try:
                importance_enum = _Importance(
                    new_meta.get("importance_max")
                    or new_meta.get("importance", "medium")
                )
            except ValueError:
                importance_enum = _Importance.MEDIUM

            extra_fm = {
                k: v for k, v in new_meta.items()
                if k not in {"title", "tags", "category", "importance"}
            }

            # Executor's NotesHandle keys notes by bare basename
            # within the category dir — ``conversations/<sid>__<bucket>.md``
            # → ``<sid>__<bucket>.md`` once the executor places it
            # under ``memory/conversations/``.
            bare_filename = Path(target_rel).name

            if is_new_file:
                draft = NoteDraft(
                    title=new_meta.get("title", target_rel),
                    body=new_body,
                    category=new_meta.get("category", CATEGORY),
                    tags=list(new_meta.get("tags") or []),
                    importance=importance_enum,
                    scope=Scope.SESSION,
                    filename=bare_filename,
                    frontmatter=extra_fm,
                )
                run_coro_sync(notes.write(draft))
            else:
                patch = NotePatch(
                    body=new_body,
                    tags=list(new_meta.get("tags") or []),
                    importance=importance_enum,
                    category=new_meta.get("category", CATEGORY),
                    frontmatter=extra_fm,
                )
                run_coro_sync(notes.update(bare_filename, patch))
            return True
        except Exception:  # noqa: BLE001
            logger.warning(
                "conversation_archiver: provider write failed for %s",
                target_rel, exc_info=True,
            )
            return False

    #: Rotate a conversations rollup once it crosses this size; keep ~this much
    #: of the most-recent tail live and archive the older head.
    _ROTATE_CAP_BYTES = 256 * 1024
    _ROTATE_KEEP_TAIL_BYTES = 96 * 1024

    def _maybe_rotate_body(
        self, *, notes, run_coro_sync, target_rel: str,
        new_meta: Dict[str, Any], new_body: str,
    ) -> str:
        """Archive the older half of an oversized rollup; return the body to keep
        live (the recent tail). Raw is preserved in a numbered archive note, never
        deleted. Best-effort — on any issue the full body is returned unchanged."""
        try:
            if len(new_body.encode("utf-8")) <= self._ROTATE_CAP_BYTES:
                return new_body
            import re as _re

            anchors = [m.start() for m in _re.finditer(r"(?m)^## ", new_body)]
            if len(anchors) < 4:
                return new_body  # too few turns to split safely
            split = None
            for a in anchors[1:]:
                if len(new_body[a:].encode("utf-8")) <= self._ROTATE_KEEP_TAIL_BYTES:
                    split = a
                    break
            if split is None:
                split = anchors[len(anchors) // 2]
            head = new_body[:split].rstrip()
            tail = new_body[split:].lstrip("\n")
            if not head.strip() or not tail.strip():
                return new_body

            from geny_executor.memory.provider import (
                Importance as _Imp,
                NoteDraft,
                Scope,
            )

            base = Path(target_rel).name
            base = base[:-3] if base.endswith(".md") else base
            existing = run_coro_sync(notes.list(category=CATEGORY)) or []
            seq = 1 + sum(
                1 for n in existing
                if getattr(n, "filename", "").startswith(f"{base}.")
                and ".archive." in getattr(n, "filename", "")
            )
            archive_name = f"{base}.{seq:03d}.archive.md"
            run_coro_sync(notes.write(NoteDraft(
                title=f"{new_meta.get('title', base)} (archive {seq})",
                body=head,
                category=CATEGORY,
                tags=list(new_meta.get("tags") or []) + ["archive"],
                importance=_Imp.LOW,
                scope=Scope.SESSION,
                filename=archive_name,
                frontmatter={"archived": True, "archive_seq": seq},
            )))
            logger.info(
                "conversation_archiver: rotated %s → %s (%d bytes archived, %d kept)",
                target_rel, archive_name, len(head), len(tail),
            )
            return tail
        except Exception:  # noqa: BLE001 — rotation must never break archiving
            logger.warning(
                "conversation_archiver: rotation failed for %s",
                target_rel, exc_info=True,
            )
            return new_body

    def _locate_or_initialise(
        self,
        *,
        bucket: str,
        base_slug: str,
        derived_title_seed: str,
    ) -> Tuple[Optional[str], Optional[str], Dict[str, Any], str]:
        """Resolve the on-disk rollup file for this ``(session, bucket)``.

        Returns ``(relative_path, absolute_path, existing_meta,
        existing_body)``. Both ``existing_meta`` and ``existing_body``
        are empty when the file is being created. Returns
        ``(None, None, {}, "")`` only on a hard error.

        Filename resolution per bucket:

          1. If the bucket already has a cached rel, reuse it and
             read the existing rollup via ``NotesHandle.read``.
          2. Otherwise list the ``conversations/`` directory directly —
             non-user buckets match the stem exactly, the user bucket
             matches the prefix. A directory answers this without the
             notes store's lock or its cold-start full-vault scan.
          3. Otherwise create a new file using
             :func:`bucket_path_for` to compose the suffix.
        """
        from service.memory.frontmatter import parse_frontmatter
        from service.memory.sync_async_bridge import run_coro_sync

        notes = self._provider.notes() if self._provider is not None else None

        def _read_meta_body(rel: str) -> Tuple[Dict[str, Any], str]:
            """The existing rollup's frontmatter + body, read from disk.

            This is the file THIS archiver wrote, in a directory it
            already addresses, so reading it is a file read — while
            ``notes.read()`` takes the notes store's process-wide lock
            and, on a cold store, triggers the full-vault scan first
            (every note read and frontmatter-parsed). Doing that from a
            nested event loop on the single side-effect worker is how
            this path kept blowing its 120s budget while the main loop's
            own memory writes queued behind the same lock — the same
            contention the directory listing below was already moved off.

            The notes store parses this identical file with the same
            parser, so nothing about the result changes.
            """
            path = self._memory_dir / rel
            try:
                raw = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return {}, ""
            except OSError:
                logger.debug(
                    "conversation_archiver: could not read %s", rel, exc_info=True,
                )
                return {}, ""
            meta, body = parse_frontmatter(raw)
            meta = dict(meta or {})
            meta.setdefault("category", CATEGORY)
            return meta, body

        cached = self._cached_rel.get(base_slug)
        if cached:
            meta, body = _read_meta_body(cached)
            return cached, str(self._memory_dir / cached), meta, body

        sid_slug = _slug_for_session_id(self._session_id)
        exact_stem = f"{sid_slug}__{base_slug}"
        prefix_stem = f"{exact_stem}__"

        # "Does this session's rollup file exist?" is a DIRECTORY question,
        # and it used to be answered through the notes store:
        # ``notes.list(category=...)`` takes the store's LoopAgnosticLock
        # and, on a cold store, triggers the full-vault scan — every note
        # read and frontmatter-parsed (~19s at 6.2k notes) — with this
        # side-effect worker holding the lock the whole time while the
        # main loop's own memory writes queue behind it. That contention
        # is where the 2026-08-11 wedge parked. The notes store reads from
        # this same directory, so listing it directly answers the same
        # question with no lock and no parsing; the matched file's
        # meta/body still comes from the provider (one bounded read), so
        # frontmatter interpretation stays in one place.
        candidates: list[str] = []
        try:
            for entry in sorted(os.listdir(self._memory_dir / CATEGORY)):
                if not entry.endswith(".md"):
                    continue
                stem = entry[:-3]
                if _ARCHIVE_STEM.search(stem):
                    # A rotated archive shares the live file's prefix and
                    # sorts BEFORE it ("….001.archive" < "….md"), so after
                    # a restart cleared the cache it was picked as the live
                    # rollup — and rotated again into "….001.archive.001.
                    # archive", one level deeper per restart (ten deep in
                    # production). Archives are never the live file.
                    continue
                if stem == exact_stem or (
                    bucket == Bucket.USER and stem.startswith(prefix_stem)
                ):
                    candidates.append(entry)
        except FileNotFoundError:
            pass  # no conversations dir yet — first archive creates it
        except OSError:
            logger.debug(
                "conversation_archiver: directory listing failed",
                exc_info=True,
            )

        for bare in candidates:
            rel = f"{CATEGORY}/{bare}"
            self._cached_rel[base_slug] = rel
            em, eb = _read_meta_body(rel)
            return rel, str(self._memory_dir / rel), em, eb

        title_slug = _slug_for_title(derived_title_seed) if bucket == Bucket.USER else ""
        bucket_path = bucket_path_for(
            bucket=bucket, base_slug=base_slug, title_slug=title_slug,
        )
        rel = session_filename_for(
            session_id=self._session_id, bucket_path=bucket_path,
        )
        self._cached_rel[base_slug] = rel
        return rel, str(self._memory_dir / rel), {}, ""

    def _merge_frontmatter(
        self,
        *,
        existing_meta: Dict[str, Any],
        bucket: str,
        derived_title_seed: str,
        ts: datetime,
        view: InteractionEventView,
        tags_for_turn: List[str],
        links_for_turn: List[str],
        importance: str,
        eid8: str,
    ) -> Dict[str, Any]:
        """Combine existing session frontmatter with this turn's
        contribution.

        Title is sticky: once a non-empty title lives in the
        existing frontmatter, it survives unchanged. Per-bucket
        defaults when no title is yet set:

          - ``user``       — derived title (first body line) or
                              ``"Session <sid>"``.
          - ``reflection`` — fixed ``"Reflection"``.
          - ``dm``         — counterpart-derived seed (role + short
                              id) or ``"DM <cp_short>"``.
          - ``system``     — fixed ``"System"``.
        """
        date_iso = ts.date().isoformat()
        ts_iso = ts.isoformat()

        # Title — sticky once chosen.
        existing_title = ""
        if isinstance(existing_meta.get("title"), str):
            existing_title = existing_meta["title"].strip()
        if existing_title:
            title = existing_title
        elif derived_title_seed:
            title = derived_title_seed
        elif bucket == Bucket.REFLECTION:
            title = "Reflection"
        elif bucket == Bucket.SYSTEM:
            title = "System"
        elif bucket == Bucket.DM:
            cp = (view.counterpart_id or "").strip()
            title = f"DM {cp[:8]}" if cp else "DM"
        else:
            sid_short = _slug_for_session_id(self._session_id)
            title = f"Session {sid_short}"

        date_first = (
            existing_meta.get("date_first")
            if isinstance(existing_meta.get("date_first"), str) and existing_meta["date_first"]
            else date_iso
        )
        date_last = date_iso

        prev_event_ids = _str_list(existing_meta.get("event_ids"))
        if eid8 not in prev_event_ids:
            prev_event_ids.append(eid8)

        prev_kinds = _str_list(existing_meta.get("kinds"))
        if view.kind and view.kind not in prev_kinds:
            prev_kinds.append(view.kind)

        prev_counterparts = _str_list(existing_meta.get("counterparts"))
        cp = (view.counterpart_id or "").strip()
        if cp and cp not in _SELF_LIKE_COUNTERPARTS and cp not in prev_counterparts:
            prev_counterparts.append(cp)

        prev_tags = _str_list(existing_meta.get("tags"))
        for t in tags_for_turn:
            if t not in prev_tags:
                prev_tags.append(t)

        prev_links = _str_list(existing_meta.get("links_to"))
        for link in links_for_turn:
            if link not in prev_links:
                prev_links.append(link)

        prev_imp_max = str(
            existing_meta.get("importance_max")
            or existing_meta.get("importance")
            or "low"
        ).lower()
        if _IMPORTANCE_RANK.get(importance, 0) > _IMPORTANCE_RANK.get(prev_imp_max, 0):
            importance_max = importance
        else:
            importance_max = prev_imp_max
        if importance_max not in _IMPORTANCE_RANK:
            importance_max = "low"

        turn_count = int(existing_meta.get("turn_count") or 0) + 1

        return build_session_frontmatter(
            session_id=self._session_id,
            title=title,
            date_first=date_first,
            date_last=date_last,
            turn_count=turn_count,
            event_ids=prev_event_ids,
            kinds=prev_kinds,
            counterparts=prev_counterparts,
            importance_max=importance_max,
            tags=prev_tags,
            links_to=prev_links,
        )


# ─────────────────────────────────────────────────────────────────
# Module helpers
# ─────────────────────────────────────────────────────────────────


def _str_list(value: Any) -> List[str]:
    """Coerce a frontmatter value to a list of strings."""
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, (str, int, float)) and str(v) != ""]
    if isinstance(value, str) and value:
        return [value]
    return []


def _append_turn_block(existing_body: str, eid8: str, turn_block: str) -> str:
    """Append ``turn_block`` to ``existing_body``, skipping if the
    same anchor already exists (idempotent re-archive of the same
    event_id is a no-op on disk).

    Re-emits the ``# <title>`` H1 header on first turn so an empty
    starting body still renders a title. The H1 is sourced from
    ``# `` line if already present in ``existing_body`` to avoid
    duplication.
    """
    anchor = f"## turn-{eid8}"
    if anchor in (existing_body or ""):
        return existing_body or ""

    sep = "\n\n---\n\n" if existing_body and existing_body.strip() else ""
    base = existing_body.rstrip() if existing_body else ""
    if not base:
        # First turn: keep the body minimal — the rollup file's
        # frontmatter already carries the title; an H1 is optional
        # and risks drifting from the frontmatter title. Skip it.
        return turn_block

    return f"{base}{sep}{turn_block}"


def iter_turn_anchors(text: str) -> Iterable[Tuple[str, int]]:
    """Yield ``(eid8, char_offset)`` for each ``## turn-<eid>`` heading.

    Used by the migration script and tests to enumerate turns
    inside a rollup file.
    """
    for match in _TURN_BLOCK_RE.finditer(text or ""):
        yield match.group("eid"), match.start()


__all__ = [
    "CATEGORY",
    "EID_WIDTH_DEFAULT",
    "EID_WIDTH_MAX",
    "LONG_BODY_THRESHOLD",
    "SHORT_BODY_THRESHOLD",
    "TITLE_PREFIX_CHARS",
    "SESSION_TITLE_SLUG_MAX",
    "SESSION_ID_SLUG_MAX",
    "ArchivedConversation",
    "Bucket",
    "ConversationArchiver",
    "build_body",
    "build_frontmatter",       # legacy / migration only
    "build_session_frontmatter",
    "build_links_to",
    "build_tags",
    "build_title",
    "bucket_path_for",
    "compute_importance",
    "derive_session_title",
    "filename_for",            # legacy / migration only
    "iter_turn_anchors",
    "render_turn_block",
    "resolve_bucket",
    "sanitize_counterpart",
    "session_filename_for",
    "short_event_id",
]
