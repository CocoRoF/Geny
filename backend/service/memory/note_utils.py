"""Note-shape helpers shared across the host-side memory layer.

These were the module-level helpers previously living in
``service.memory.structured_writer``. After Sprint 3 + Cleanup retired
the ``StructuredMemoryWriter`` class and inlined every CRUD op into
the manager / multi-tenant managers, the helpers themselves stayed
useful — they encode Geny's host-specific note conventions
(slug shape, valid categories, wikilink syntax, linked_from
propagation) which the executor's flat-category ``NoteDraft`` /
``NotesHandle`` deliberately doesn't model.

Public surface:
    VALID_CATEGORIES      — set of category folders the host recognises
    PINNED_CATEGORY       — alias for the always-pinned facts folder
    extract_wikilinks(text) -> list[str]
    _slugify(title)       -> filesystem-safe slug
    _propagate_linked_from(provider, source_filename, targets)
                          -> async-via-run_coro_sync rewrite of every
                             linked target's frontmatter ``linked_from``
"""

from __future__ import annotations

import math
import re
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = getLogger(__name__)


# Valid categories that map to subdirectories.
#
# Memory v2 (cf. /Geny/plan.md §1.5) categorises memory into four
# semantic groups (entities/ category was retired — counterpart info
# lives in dms/ and is derivable from conversations/ frontmatter):
#
#   * PINNED (always-inject)   — ``critical`` (Memory v2 PR 12)
#   * LEAF (source of truth)   — ``conversations`` (1 turn = 1 file)
#   * INDEX                    — ``dms`` (per-counterpart-per-day bundles)
#   * DERIVED                  — ``insights`` (LLM-distilled)
#   * CURATED                  — ``topics`` / ``projects`` / ``daily``
#   * ARTIFACT                 — ``compactions`` (s02 compactor snapshots)
#
# Membership in this set is the registration token: any category here
# is recognised by the index, search tools, and Opsidian sidebar.
VALID_CATEGORIES = {
    "critical",
    "daily", "topics", "projects", "insights",
    "dms", "conversations", "compactions",
    "executions",
    "inbox",  # whiteboard P0 — raw captures awaiting refinement
    "knowledge",  # knowledge repository — document cards + collected sources
    "observations",  # VTuber screen-observation notes (vision plan P2)
    "root",
}

# Pinned-facts category. Centralised here so the constant is the
# single source of truth shared by the manager's ``_notes_*`` helpers,
# the ``memory_pin`` tool, and the auto-promote callback wired into
# ``GenyMemoryStrategy``.
PINNED_CATEGORY = "critical"

# Maximum slug length for filenames.
_MAX_SLUG = 80


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9가-힣\s_-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = slug.strip("-")
    return slug[:_MAX_SLUG] or "untitled"


_WIKILINK_RE = re.compile(r"\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]")


def extract_wikilinks(content: str) -> List[str]:
    """Extract ``[[wikilink]]`` targets from ``content`` (lowercased,
    deduped).
    """
    found: List[str] = []
    seen: set = set()
    for match in _WIKILINK_RE.finditer(content):
        target = match.group(1).strip().lower()
        if target and target not in seen:
            found.append(target)
            seen.add(target)
    return found


async def apropagate_linked_from(
    provider,
    source_filename: str,
    target_wikilinks: list,
) -> None:
    """For each wikilink target the source declares, append the source
    filename (sans extension) to the target's frontmatter
    ``linked_from`` list.

    Memory v2 PR 15 — closes the regression where Obsidian's Properties
    pane and external readers saw stale backlinks until the next
    reindex pass. The propagation is *immediate*: the source's first
    write triggers the rewrite of every linked target so the
    bidirectional graph is consistent before the next turn renders
    the system prompt.

    Routes the read+update through the executor's ``NotesHandle`` so
    the in-memory cache stays consistent with the on-disk
    ``linked_from`` field. Earlier revisions wrote target files
    directly with ``Path.write_text``, which bypassed the executor's
    note cache and left ``target.links_in`` empty for the rest of the
    session.

    Resolution: exact bare-stem match against ``notes.list()``, with a
    substring fallback when the wikilink doesn't match a stem
    verbatim.

    No-op when the source has no wikilinks or the provider isn't
    attached. Best-effort: if a single target rewrite fails, the
    others still go through.
    """
    if not target_wikilinks or provider is None:
        return
    from geny_executor.memory.provider import NotePatch

    notes = provider.notes()
    try:
        metas = await notes.list()
    except Exception:
        logger.debug(
            "apropagate_linked_from: provider list failed", exc_info=True,
        )
        return

    by_stem: Dict[str, str] = {}
    for m in metas:
        stem = Path(m.ref.filename).stem
        by_stem.setdefault(stem, m.ref.filename)

    source_bare = Path(source_filename).name
    source_stem = Path(source_filename).stem

    for target_link in target_wikilinks:
        link = str(target_link).strip().lower()
        if not link:
            continue
        link_stem = Path(link).stem
        bare_target = by_stem.get(link_stem)
        if bare_target is None:
            for stem, fname in by_stem.items():
                if link_stem and link_stem in stem:
                    bare_target = fname
                    break
        if bare_target is None or bare_target == source_bare:
            continue
        try:
            existing = await notes.read(bare_target)
            if existing is None:
                continue
            fm = dict(existing.frontmatter or {})
            linked = list(fm.get("linked_from") or [])
            if source_stem in linked or source_filename in linked:
                continue
            linked.append(source_stem)
            fm["linked_from"] = linked
            await notes.update(bare_target, NotePatch(frontmatter=fm))
        except Exception:
            logger.debug(
                "apropagate_linked_from: rewrite failed for %s", target_link,
                exc_info=True,
            )


def scan_dms_directory(memory_dir: Path | str) -> Dict[str, Dict[str, Any]]:
    """Deep-scan ``memory/dms/<counterpart_id>/<date>.md`` and return a
    flat ``{display_filename: file_info}`` dict.

    The ``dms/`` category uses a 2-level layout (one bundle per
    counterpart per day) which the executor's ``IndexHandle`` —
    designed for flat ``memory/<category>/<file>.md`` — cannot pick
    up. This helper does the deep walk and returns rows in the same
    shape the executor's snapshot produces, so callers (manager
    snapshot merger, ``dm_archiver._maintain_shard``) can splice them
    into the global index without the executor needing dms-specific
    awareness.

    The ``display_filename`` key uses the relative ``dms/<cp>/<date>.md``
    form so it can't collide across counterparts on the same day.
    """
    from service.memory.frontmatter import parse_frontmatter

    out: Dict[str, Dict[str, Any]] = {}
    root = Path(memory_dir) / "dms"
    if not root.exists():
        return out

    for cp_dir in sorted(root.iterdir()):
        if not cp_dir.is_dir():
            continue
        for path in sorted(cp_dir.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            try:
                meta, body = parse_frontmatter(text)
            except Exception:  # noqa: BLE001
                meta, body = {}, text
            try:
                rel = str(path.relative_to(memory_dir)).replace("\\", "/")
            except ValueError:
                rel = f"dms/{cp_dir.name}/{path.name}"
            stat = None
            try:
                stat = path.stat()
            except OSError:
                pass
            tags = meta.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            row: Dict[str, Any] = {
                "filename": rel,
                "title": meta.get("title") or path.stem,
                "category": "dms",
                "tags": list(tags),
                "importance": meta.get("importance") or "medium",
                "char_count": len(text),
                "links_to": list(meta.get("links_to") or []),
                "linked_from": list(meta.get("linked_from") or []),
                "summary": (
                    body.split("\n", 1)[0][:240].strip() if body.strip() else ""
                ),
                "created": meta.get("created") or "",
                "modified": meta.get("modified") or "",
                "source": "dm_bundle",
                # Counterpart-specific dimensions surfaced for index
                # consumers (Opsidian sidebar grouping, retriever).
                "counterpart": cp_dir.name,
                "counterpart_role": meta.get("counterpart_role") or "",
                "session_id": meta.get("session_id") or "",
                "event_count": int(meta.get("event_count") or 0),
                "date_first": meta.get("date_first") or "",
                "date_last": meta.get("date_last") or "",
            }
            if stat is not None and not row["modified"]:
                from datetime import datetime, timezone
                row["modified"] = datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc,
                ).isoformat()
            out[rel] = row
    return out


async def aget_index_snapshot_with_dms(
    provider, memory_dir: Path | str
) -> Dict[str, Any]:
    """One-shot helper: ``await provider.index().snapshot()`` + restore
    the ``dms/_index.json`` shard the executor clobbered + splice dms
    rows into the in-memory payload.

    The executor's ``IndexHandle.snapshot()`` (and ``.rebuild()``)
    rewrites every per-category shard from a flat ``glob("*.md")`` that
    cannot see the 2-level ``dms/<cp>/<date>.md`` layout. So even
    after ``dm_archiver`` writes a fresh shard, the *next* snapshot
    call clobbers it. This helper:

      1. Calls the executor's snapshot.
      2. Re-runs ``write_dms_shard`` so the on-disk shard is correct
         again before the next operator refresh.
      3. Splices the dms rows into the in-memory ``files`` dict so
         the returned payload reports them too (totals updated).

    Use from anywhere that needs a session-scoped index snapshot —
    ``SessionMemoryManager._index_snapshot``, controller routes, or
    any other reader. Multi-tenant managers (Global / Curated /
    UserOpsidian) don't need this — their providers don't have
    a ``dms/`` category in scope.
    """
    snap = await provider.index().snapshot()
    try:
        write_dms_shard(memory_dir)
    except Exception:
        logger.debug(
            "aget_index_snapshot_with_dms: shard restore failed",
            exc_info=True,
        )
    try:
        dms_rows = scan_dms_directory(memory_dir)
    except Exception:
        logger.debug(
            "aget_index_snapshot_with_dms: dms scan failed",
            exc_info=True,
        )
        return snap
    if not dms_rows:
        return snap
    files = dict(snap.get("files") or {})
    tag_map: Dict[str, List[str]] = {
        k: list(v) for k, v in (snap.get("tag_map") or {}).items()
    }
    total_chars = int(snap.get("total_chars", 0) or 0)
    for rel, row in dms_rows.items():
        files[rel] = row
        total_chars += int(row.get("char_count") or 0)
        for tag in row.get("tags") or []:
            tag_map.setdefault(str(tag).lower(), []).append(rel)
    out = dict(snap)
    out["files"] = files
    out["tag_map"] = tag_map
    out["total_chars"] = total_chars
    out["total_files"] = len(files)
    return out


def write_dms_shard(memory_dir: Path | str) -> None:
    """Atomically rewrite ``memory/dms/_index.json`` from a deep scan.

    Called by ``dm_archiver._append_locked`` after every bundle
    write so the operator-facing JSON shard reflects reality. The
    schema mirrors the executor's per-category shard format
    (``file_count`` / ``files`` / ``last_rebuilt`` / ``tag_counts``)
    so existing readers don't see a different shape.
    """
    import json
    import os
    import tempfile
    from datetime import datetime
    from service.utils.utils import _configured_tz as _get_tz

    files = scan_dms_directory(memory_dir)
    tag_counts: Dict[str, int] = {}
    for row in files.values():
        for tag in row.get("tags") or []:
            tag_counts[str(tag).lower()] = tag_counts.get(str(tag).lower(), 0) + 1

    payload = {
        "category": "dms",
        "description": "Per-counterpart-per-day DM index bundles.",
        "file_count": len(files),
        "files": files,
        "last_rebuilt": datetime.now(_get_tz()).isoformat(),
        "tag_counts": tag_counts,
        "version": "2",
    }
    shard_path = Path(memory_dir) / "dms" / "_index.json"
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix="_index.", suffix=".json.tmp", dir=str(shard_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, shard_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ─────────────────────────────────────────────────────────────────────
# Graph projection — single source of truth for every Opsidian surface
# (user / curated / global / session). Builds nodes + edges from an index
# snapshot. Edge derivation lives here so all managers stay identical and
# so the de-clumping policy (IDF tag weights + meta-tag denylist + df
# cutoff + per-node fanout cap) is defined once.
#
# Edge sources, in priority order:
#   1. idx["edges"]  — if the executor already derived a unified edge list
#      (semantic-kNN + IDF-tag + wikilink), render it verbatim. (Phase 2+)
#   2. else fall back to deriving wikilink + IDF-tag edges from the
#      per-note links_to/tags in the snapshot. (Phase 1)
# ─────────────────────────────────────────────────────────────────────

# Meta tags that appear on (nearly) every archived note — connecting all
# notes that share one produces a useless hairball, so they never form
# tag edges. Compared case-insensitively, leading '#' stripped.
META_TAG_DENYLIST = {
    "conversation", "user_chat", "assistant_chat", "agent_dm", "dm", "dms",
    "compaction", "system-artifact", "system", "auto", "automated",
    "log", "logs", "chat", "session", "archive", "execution", "execution-summary",
    "insight", "insights", "memory", "note", "daily", "digest",
}

# A tag on more than max(ABS_FLOOR, RATIO*N) notes is treated as too common
# to be discriminative and skipped. The absolute floor keeps SMALL vaults
# from over-pruning (e.g. a "neowiz" tag on 3 of 5 notes is a real cluster,
# not noise — a bare ratio would drop it). A tag on *every* note is always
# dropped (universal == meaningless).
TAG_DF_RATIO_MAX = 0.33
TAG_DF_ABS_FLOOR = 12
# Cap how many tag edges a single note may contribute — prevents a few
# popular tags from dominating the force layout (clumping into balls).
TAG_FANOUT_MAX = 6


def compute_total_links(idx: Optional[Dict[str, Any]]) -> int:
    """Count resolved wikilinks (outgoing links whose target exists)."""
    if not idx:
        return 0
    files_map = idx.get("files", {}) or {}
    total = 0
    for info in files_map.values():
        for tgt in (info.get("links_to") or []):
            if tgt in files_map:
                total += 1
    return total


async def fetch_provider_edges(provider) -> Optional[List[Dict[str, Any]]]:
    """Return the executor-derived rich edge list (wikilink + IDF-tag + lexical
    semantic-kNN) when the provider's index exposes ``graph_edges()``
    (geny-executor >= 2.38.0), else ``None`` so the caller falls back to the
    Phase-1 heuristic edges built inside :func:`build_graph_from_index`.

    Feature-detected via ``getattr`` (the method is intentionally NOT on the
    ``@runtime_checkable`` IndexHandle Protocol), so an older executor degrades
    gracefully instead of raising.
    """
    try:
        index = provider.index()
        fn = getattr(index, "graph_edges", None)
        if fn is None:
            return None
        return await fn()
    except Exception:  # noqa: BLE001 — never let edge enrichment break the graph
        return None


def is_silent_reply(text: Optional[str]) -> bool:
    """True when a persona turn's final output is the ``[SILENT]``
    no-response marker (thinking-trigger protocol). Tolerant of stray
    whitespace/punctuation but nothing more — any real sentence after
    the marker counts as a spoken reply."""
    # The executor's rule, so the replay and this agree on what silence is
    # (they did not: "[SILENT]." was silence here and a conversation turn
    # there). It also reads past leading cue tags ("[neutral] [SILENT]").
    from geny_executor.memory.short_term_window import is_silence_text

    return is_silence_text(text or "")


def build_graph_from_index(idx: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Project an index snapshot into a {nodes, edges} graph for the UI.

    De-clumped: tag edges are IDF-weighted, drop meta/over-common tags,
    and respect a per-node fanout cap so the force layout shows topical
    clusters rather than one dense hairball.
    """
    if not idx:
        return {"nodes": [], "edges": []}

    files_map = idx.get("files", {}) or {}
    n = max(1, len(files_map))
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    edge_set: set = set()
    tag_to_files: Dict[str, List[str]] = {}

    def _add_edge(a: str, b: str, etype: str, weight: float, label: Optional[str] = None) -> bool:
        if a == b:
            return False
        if (a, b) in edge_set or (b, a) in edge_set:
            return False
        edge_set.add((a, b))
        edge = {"source": a, "target": b, "type": etype, "weight": weight}
        if label is not None:
            edge["label"] = label
        edges.append(edge)
        return True

    # Silent-turn records (persona chose not to speak) are kept as notes
    # for audit but carry no conversational meaning — surfacing them as
    # graph nodes buries the real structure under no-op executions.
    hidden = {
        fn
        for fn, info in files_map.items()
        if "silent" in (info.get("tags") or [])
    }

    for fn, info in files_map.items():
        if fn in hidden:
            continue
        links_to = info.get("links_to") or []
        linked_from = info.get("linked_from") or []
        tags = info.get("tags") or []
        nodes.append({
            "id": fn,
            "label": info.get("title", fn),
            "category": info.get("category", "root"),
            "importance": info.get("importance", "medium"),
            "tags": tags,
            "connectionCount": len(links_to) + len(linked_from),
            "summary": info.get("summary", "") or "",
            "charCount": info.get("char_count", 0),
        })
        for target in links_to:
            if target in files_map and target not in hidden:
                _add_edge(fn, target, "wikilink", 1.0)
        for tag in tags:
            tag_to_files.setdefault(tag, []).append(fn)

    # If the executor already shipped a unified edge list, prefer it
    # (Phase 2+ semantic-kNN / IDF-tag edges) and skip heuristic tag edges.
    pre_edges = idx.get("edges")
    if pre_edges:
        for e in pre_edges:
            src, tgt = e.get("source"), e.get("target")
            if (
                src in files_map and tgt in files_map
                and src not in hidden and tgt not in hidden
            ):
                _add_edge(src, tgt, e.get("type", "semantic"),
                          float(e.get("weight", 0.5)), e.get("label"))
        return {"nodes": nodes, "edges": edges}

    # Phase 1 fallback: IDF-weighted, de-clumped tag edges.
    node_tag_degree: Dict[str, int] = {}
    df_max = max(TAG_DF_ABS_FLOOR, int(TAG_DF_RATIO_MAX * n))
    for tag, fns in tag_to_files.items():
        df = len(fns)
        # need ≥2 notes; drop universal tags (on every note) and over-common ones
        if df < 2 or df >= n or df > df_max:
            continue
        if tag.lower().lstrip("#") in META_TAG_DENYLIST:
            continue
        weight = round(0.5 * math.log((1 + n) / (1 + df)), 3)
        if weight <= 0:
            continue
        for i in range(len(fns)):
            a = fns[i]
            if node_tag_degree.get(a, 0) >= TAG_FANOUT_MAX:
                continue
            for j in range(i + 1, len(fns)):
                b = fns[j]
                if node_tag_degree.get(b, 0) >= TAG_FANOUT_MAX:
                    continue
                if _add_edge(a, b, "tag", weight, tag):
                    node_tag_degree[a] = node_tag_degree.get(a, 0) + 1
                    node_tag_degree[b] = node_tag_degree.get(b, 0) + 1
                    if node_tag_degree[a] >= TAG_FANOUT_MAX:
                        break

    return {"nodes": nodes, "edges": edges}


__all__ = [
    "VALID_CATEGORIES",
    "PINNED_CATEGORY",
    "_slugify",
    "extract_wikilinks",
    "apropagate_linked_from",
    "scan_dms_directory",
    "write_dms_shard",
    "aget_index_snapshot_with_dms",
    "build_graph_from_index",
    "compute_total_links",
    "fetch_provider_edges",
    "META_TAG_DENYLIST",
]
