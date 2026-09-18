"""Environment persistence service — save/load/diff pipeline environments.

Port of ``geny_executor_web.app.services.environment_service`` to Geny. The
on-disk JSON layout is byte-compatible, so environments exported from the
web console can be imported into Geny (and vice versa) without conversion.

v0.8.0 of the format shifted from bare ``snapshot`` payloads to full
:class:`EnvironmentManifest` v2 dicts. Legacy files are loaded via silent
migration: their ``snapshot`` key is rehydrated into an ``EnvironmentManifest``
on read. New writes always emit the v2 ``manifest`` key.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

logger = logging.getLogger(__name__)

from geny_executor import (
    EnvironmentManifest,
    Pipeline,
    PipelineMutator,
    PipelinePresets,
    PipelineSnapshot,
    validate_manifest,
)

from service.environment.exceptions import (
    EnvironmentNotFoundError,
    StageValidationError,
)

__all__ = [
    "EnvironmentService",
    "EnvironmentNotFoundError",
    "StageValidationError",
]


_PRESET_FACTORIES = {
    "minimal": PipelinePresets.minimal,
    "chat": PipelinePresets.chat,
    "agent": PipelinePresets.agent,
    "evaluator": PipelinePresets.evaluator,
    "geny_vtuber": PipelinePresets.geny_vtuber,
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fresh_id() -> str:
    return uuid4().hex[:12]


def _default_storage_path() -> str:
    """Resolve the storage root from ``ENVIRONMENT_STORAGE_PATH`` env var.

    Falls back to ``./data/environments`` which matches the web console's
    default and keeps docker volume mounts symmetric across the two apps.
    """
    return (os.getenv("ENVIRONMENT_STORAGE_PATH") or "./data/environments").strip()


# Platform tool families exposed as *core* (upfront, no ToolSearch) on EVERY
# environment — including custom envs that predate the seed-template promotion
# (`templates._promote_core_tools`). The memory family is Geny's always-on base
# toolkit; the agent should be able to store/recall from turn 1 without a
# ToolSearch round-trip. knowledge_* / hook_* stay deferred.
_RUNTIME_CORE_PROMOTIONS = {"memory_*": True}


def _promote_platform_core_tools(manifest: "EnvironmentManifest") -> None:
    """Ensure the always-on platform tool families are *core* on ``manifest``.

    Applied to every loaded manifest (seed or custom). Merge-safe: ``setdefault``
    keeps any explicit per-env override. A wildcard override for a family the env
    doesn't include is a harmless no-op. Never raises — a promotion failure must
    not break session build.
    """
    try:
        tools = getattr(manifest, "tools", None)
        if tools is None:
            return
        overrides = dict(getattr(tools, "core_overrides", None) or {})
        changed = False
        for pattern, core in _RUNTIME_CORE_PROMOTIONS.items():
            if pattern not in overrides:
                overrides[pattern] = core
                changed = True
        if changed:
            tools.core_overrides = overrides
    except Exception:  # noqa: BLE001
        logger.debug("core-tool promotion skipped for manifest", exc_info=True)


class EnvironmentService:
    """Save, load, diff, and mutate pipeline environments.

    Phase 2B (cycle 20260519): Postgres ``environments`` table is the
    source of truth when the DB is reachable; the JSON files under
    ``ENVIRONMENT_STORAGE_PATH`` are a mirrored fallback used during
    DB outages. ``set_database(app_db)`` wires the DB at startup and
    runs a one-shot reconcile that pushes file-only envs to the DB
    and mirrors DB rows to disk (DB wins on conflict).

    All CRUD funnels through ``_read_raw`` / ``_write_raw`` /
    ``delete`` / ``list_all`` so the DB indirection is transparent to
    the rest of the service's API.
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        app_db: Any = None,
    ) -> None:
        path = storage_path or _default_storage_path()
        self._storage = Path(path)
        self._storage.mkdir(parents=True, exist_ok=True)
        self._app_db = app_db
        # Short-TTL parsed-manifest memo (audit L2): a single session
        # build calls load_manifest ~13× (each _env_* helper independently)
        # and each call is a blocking DB read + full parse on the event
        # loop — a rehydrate storm serialized ~13·N of them. The memo
        # coalesces the calls within one build; the TTL is tiny so an env
        # edit is picked up almost immediately, and _write_raw invalidates
        # the entry outright.
        import threading

        self._manifest_cache: Dict[str, tuple] = {}
        self._manifest_cache_lock = threading.Lock()

    @property
    def storage_path(self) -> Path:
        return self._storage

    # ── DB wiring ──────────────────────────────────────────────

    def set_database(self, app_db: Any) -> None:
        """Attach the AppDatabaseManager and reconcile both backends."""
        self._app_db = app_db
        logger.info("EnvironmentService: database backend attached")
        try:
            self._reconcile()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "EnvironmentService: reconcile failed (continuing): %s", exc,
            )

    @property
    def _db_available(self) -> bool:
        if self._app_db is None:
            return False
        try:
            return self._app_db.db_manager._is_pool_healthy()
        except Exception:
            return False

    # ── File layout helpers ────────────────────────────────────

    def _path(self, env_id: str) -> Path:
        return self._storage / f"{env_id}.json"

    def _read_raw(self, env_id: str) -> Optional[Dict[str, Any]]:
        """DB-first read; falls back to the JSON file on miss / outage."""
        if self._db_available:
            try:
                row = self._app_db.db_manager.execute_query_one(
                    "SELECT data FROM environments WHERE env_id = %s",
                    (env_id,),
                )
                if row is not None:
                    return _row_to_record(row)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "EnvironmentService: DB read failed for %s, trying file: %s",
                    env_id, exc,
                )
        return self._read_raw_from_file(env_id)

    def _read_raw_from_file(self, env_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(env_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None

    def _write_raw(self, env_id: str, data: Dict[str, Any]) -> None:
        """DB-UPSERT first; always mirror to the JSON file."""
        # Invalidate the parsed-manifest memo so an edit is visible at once
        # (audit L2), regardless of the 3s TTL.
        with self._manifest_cache_lock:
            self._manifest_cache.pop(env_id, None)
        if self._db_available:
            try:
                self._upsert_to_db(env_id, data)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "EnvironmentService: DB write failed for %s, falling back to file: %s",
                    env_id, exc,
                )
        # Mirror to disk regardless — fallback / DR copy.
        self._path(env_id).write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _upsert_to_db(self, env_id: str, data: Dict[str, Any]) -> None:
        is_template = bool(env_id.startswith("template-"))
        name = data.get("name") or ""
        payload = json.dumps(data, ensure_ascii=False, default=str)
        query = """
            INSERT INTO environments (env_id, name, is_template, data)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (env_id)
            DO UPDATE SET
                name = EXCLUDED.name,
                is_template = EXCLUDED.is_template,
                data = EXCLUDED.data,
                updated_at = CURRENT_TIMESTAMP
        """
        self._app_db.db_manager.execute_insert(
            query, (env_id, name, is_template, payload),
        )

    def _delete_from_db(self, env_id: str) -> bool:
        affected = self._app_db.db_manager.execute_update_delete(
            "DELETE FROM environments WHERE env_id = %s",
            (env_id,),
        )
        return bool(affected and affected > 0)

    def _list_raw_from_db(self) -> List[Dict[str, Any]]:
        rows = self._app_db.db_manager.execute_query(
            "SELECT data FROM environments ORDER BY name ASC",
        )
        if not rows:
            return []
        records: List[Dict[str, Any]] = []
        for row in rows:
            rec = _row_to_record(row)
            if rec is not None:
                records.append(rec)
        return records

    # ── Manifest load / save ───────────────────────────────────

    def load_manifest(self, env_id: str) -> Optional[EnvironmentManifest]:
        """Return the stored environment as a v2 :class:`EnvironmentManifest`.

        Accepts both the current ``manifest`` layout and the legacy
        ``snapshot`` layout written by v0.7.x. Legacy quirks (e.g.
        pre-0.13.5 ``provider: mock`` entries) are migrated inside
        ``EnvironmentManifest.from_dict`` since geny-executor 2.2.0 —
        the load path needs no host-side coercion shims anymore.
        """
        import time

        # Serve from the short-TTL memo when fresh (audit L2). The manifest
        # is treated read-only by every caller (the _env_* extractors and
        # instantiate_pipeline read fields; they don't mutate it), so
        # sharing the parsed object across the coalesced calls is safe.
        _CACHE_TTL = 3.0
        with self._manifest_cache_lock:
            hit = self._manifest_cache.get(env_id)
            if hit is not None and (time.monotonic() - hit[0]) < _CACHE_TTL:
                return hit[1]

        raw = self._read_raw(env_id)
        if raw is None:
            return None

        if "manifest" in raw and isinstance(raw["manifest"], dict):
            manifest = EnvironmentManifest.from_dict(raw["manifest"])
        else:
            snapshot_dict = raw.get("snapshot")
            if not isinstance(snapshot_dict, dict):
                return None
            snap = PipelineSnapshot.from_dict(snapshot_dict)
            manifest = EnvironmentManifest.from_snapshot(
                snap,
                name=raw.get("name", "imported"),
                description=raw.get("description", ""),
                tags=raw.get("tags", []),
            )
        _promote_platform_core_tools(manifest)
        with self._manifest_cache_lock:
            self._manifest_cache[env_id] = (time.monotonic(), manifest)
        return manifest

    @staticmethod
    def _validate_for_write(manifest: EnvironmentManifest) -> None:
        """Write-time contract check (geny-executor 2.2.0).

        Replaces the old ``_force_required_stages_active`` silent
        rewrite: instead of coercing a bad payload into shape, the
        write is *rejected* with the library's findings so the editor
        surfaces them (a required stage flipped inactive is now a 400
        naming ``stage.required_inactive``, not a silently-undone
        toggle). Warning-severity findings log and never block.

        Raises:
            StageValidationError: one ``[code] message`` line per
                error-severity :class:`geny_executor.ManifestIssue`.
        """
        issues = validate_manifest(manifest)
        errors = [i for i in issues if i.severity == "error"]
        for issue in issues:
            if issue.severity != "error":
                logger.warning(
                    "manifest validation warning [%s] %s", issue.code, issue.message,
                )
        if errors:
            raise StageValidationError(
                "manifest validation failed:\n"
                + "\n".join(f"[{i.code}] {i.message}" for i in errors)
            )

    def _write_manifest(
        self,
        env_id: str,
        manifest: EnvironmentManifest,
        *,
        created_at: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist *manifest* to disk in v2 layout and return the full record.

        Raises :class:`StageValidationError` when the manifest carries
        error-severity findings (write-time validation rule).
        """
        manifest.metadata.id = env_id
        self._validate_for_write(manifest)
        now = _iso_now()
        record: Dict[str, Any] = {
            "id": env_id,
            "name": manifest.metadata.name,
            "description": manifest.metadata.description,
            "tags": list(manifest.metadata.tags),
            "manifest": manifest.to_dict(),
            "created_at": created_at or manifest.metadata.created_at or now,
            "updated_at": now,
        }
        if extra:
            record.update(extra)
        self._write_raw(env_id, record)
        return record

    # ── Legacy API (preserved for existing callers) ────────────

    def save(
        self,
        session,  # noqa: ARG002 — legacy signature; session reserved for future enrichment
        mutator: PipelineMutator,
        name: str,
        description: str = "",
        tags: Optional[List[str]] = None,
    ) -> str:
        """Persist a live pipeline's current snapshot as a v2 manifest."""
        snapshot = mutator.snapshot(description=name)
        manifest = EnvironmentManifest.from_snapshot(
            snapshot,
            name=name,
            description=description,
            tags=tags or [],
        )
        env_id = manifest.metadata.id or _fresh_id()
        self._write_manifest(env_id, manifest)
        return env_id

    def load(self, env_id: str) -> Optional[Dict[str, Any]]:
        """Return the raw JSON record for *env_id* (legacy callers)."""
        return self._read_raw(env_id)

    def list_all(self) -> List[Dict[str, Any]]:
        """List stored environments with UI-friendly summaries.

        Prefers DB rows; layers in any JSON-file orphans (e.g. envs
        created while the DB was unreachable) so the operator can see
        them in the UI and decide whether to delete or repair.
        """
        seen: Dict[str, Dict[str, Any]] = {}
        if self._db_available:
            try:
                for record in self._list_raw_from_db():
                    env_id = record.get("id")
                    if not env_id:
                        continue
                    summary = self._summarize(record)
                    if summary is not None:
                        seen[env_id] = summary
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "EnvironmentService: DB list failed, falling back to files: %s",
                    exc,
                )

        for f in sorted(self._storage.glob("*.json")):
            try:
                data = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            env_id = data.get("id")
            if not env_id or env_id in seen:
                continue
            summary = self._summarize(data)
            if summary is not None:
                seen[env_id] = summary
        return list(seen.values())

    @staticmethod
    def _summarize(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        env_id = data.get("id")
        if not env_id:
            return None
        manifest_dict = data.get("manifest")
        base_preset = ""
        if isinstance(manifest_dict, dict):
            model = manifest_dict.get("model", {}).get("model", "")
            stages = manifest_dict.get("stages", [])
            base_preset = manifest_dict.get("metadata", {}).get("base_preset", "") or (
                manifest_dict.get("pipeline", {}).get("name", "")
            )
            active = sum(1 for s in stages if isinstance(s, dict) and s.get("active"))
        else:
            snapshot = data.get("snapshot", {})
            model = snapshot.get("model_config", {}).get("model", "")
            stages = snapshot.get("stages", [])
            active = sum(
                1 for s in stages if isinstance(s, dict) and s.get("is_active")
            )
        # Built-in template IDs are minted by
        # ``install_environment_templates`` with stable, well-known
        # values (``template-worker-env`` / ``template-vtuber-env``).
        # User-created envs always get a 12-char hex from
        # ``_fresh_id``, so the prefix is unambiguous. We surface the
        # boolean rather than asking the frontend to do the prefix
        # check so future template additions / renames are a
        # one-place change.
        built_in = env_id.startswith("template-")
        # ``kind`` — whether this env is a VTuber persona env or a plain
        # agent/worker env. Session creation uses it to derive the role from
        # the chosen environment (so the create dialog only needs the env).
        # VTuber signal = persona preset attached OR a bound owned sub-agent
        # (the two capabilities every VTuber env declares), with base_preset /
        # id as fallbacks.
        extras = {}
        if isinstance(manifest_dict, dict):
            extras = (manifest_dict.get("host_selections", {}) or {}).get("extras", {}) or {}
        owned = extras.get("owned_subagent") or {}
        is_vtuber = bool(
            extras.get("persona_preset_id")
            or (isinstance(owned, dict) and owned.get("enabled"))
            or "vtuber" in (base_preset or "").lower()
            or "vtuber" in str(env_id).lower()
        )
        return {
            "id": env_id,
            "name": data.get("name", ""),
            "description": data.get("description", ""),
            "tags": data.get("tags", []),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "stage_count": len(stages),
            "active_stage_count": active,
            "model": model,
            "base_preset": base_preset,
            "built_in": built_in,
            "kind": "vtuber" if is_vtuber else "agent",
        }

    def update(self, env_id: str, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Patch top-level metadata (name / description / tags)."""
        raw = self._read_raw(env_id)
        if raw is None:
            return None
        manifest = self.load_manifest(env_id)
        for key in ("name", "description", "tags"):
            if key in changes and changes[key] is not None:
                raw[key] = changes[key]
                if manifest is not None:
                    setattr(manifest.metadata, key, changes[key])
        if manifest is not None:
            manifest.metadata.updated_at = _iso_now()
            raw["manifest"] = manifest.to_dict()
        raw["updated_at"] = _iso_now()
        self._write_raw(env_id, raw)
        return raw

    def delete(self, env_id: str) -> bool:
        """Remove from DB + file. Returns True if either side had it."""
        db_removed = False
        if self._db_available:
            try:
                db_removed = self._delete_from_db(env_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "EnvironmentService: DB delete failed for %s: %s", env_id, exc,
                )
        file_removed = False
        path = self._path(env_id)
        if path.exists():
            path.unlink()
            file_removed = True
        return db_removed or file_removed

    def export_json(self, env_id: str) -> Optional[str]:
        raw = self._read_raw(env_id)
        if raw is None:
            return None
        return json.dumps(raw, ensure_ascii=False, indent=2)

    def import_json(self, data: Dict[str, Any]) -> str:
        """Import a previously exported environment JSON.

        Accepts both v0.7.x payloads (top-level ``snapshot``) and v2
        payloads (top-level ``manifest``). The incoming id is preserved
        when present, otherwise a fresh one is generated.
        """
        data = copy.deepcopy(data)
        env_id = data.get("id") or _fresh_id()
        data["id"] = env_id
        now = _iso_now()
        data.setdefault("created_at", now)
        data["updated_at"] = now

        if "manifest" not in data and "snapshot" in data:
            snap = PipelineSnapshot.from_dict(data["snapshot"])
            manifest = EnvironmentManifest.from_snapshot(
                snap,
                name=data.get("name", "imported"),
                description=data.get("description", ""),
                tags=data.get("tags", []),
            )
            manifest.metadata.id = env_id
            self._validate_for_write(manifest)
            data["manifest"] = manifest.to_dict()
            data.pop("snapshot", None)
        elif "manifest" in data and isinstance(data["manifest"], dict):
            migrated = EnvironmentManifest.from_dict(data["manifest"])
            migrated.metadata.id = env_id
            self._validate_for_write(migrated)
            data["manifest"] = migrated.to_dict()

        self._write_raw(env_id, data)
        return env_id

    # ── v2 — template CRUD ─────────────────────────────────────

    def _apply_env_defaults(self, manifest: "EnvironmentManifest") -> None:
        """Seed a freshly-created manifest from the host env-defaults set.

        Audit 2026-06-17 (C5) — env-defaults curation used to be applied
        only by the frontend draft seeder, so environments created via
        the API, a preset, or any non-draft path silently ignored the
        host's ★ defaults. This applies the same curation server-side so
        *every* creation path honours it.

        Semantics mirror the FE seeder and the ``HostSelections`` contract:
            empty / uncurated list → leave the manifest's wildcard
                (``["*"]``) so the env still gets every host registration.
            non-empty list         → narrow to exactly those ids.

        Covered here:
            host_selections.{hooks, skills, permissions} — id lists.
            tools.external (custom_tools ★, C6)           — tool names.

        NOT covered (left to the FE draft seeder, which has the host MCP
        registry to materialise full configs): ``mcp_servers`` — that
        category is declarative (``tools.mcp_servers`` stores configs,
        not selection ids), so a server-side join would duplicate the
        FE's per-server config fetch. API/preset envs add MCP servers
        explicitly via the manifest instead.

        Best-effort: any failure (no DB, helper import error) degrades to
        a no-op so env creation never fails on the seeding step.
        """
        if self._app_db is None:
            return
        try:
            from service.env_defaults.service import EnvDefaultsService

            defaults = EnvDefaultsService(self._app_db).get_all()
        except Exception:
            logger.debug(
                "create: env-defaults seeding skipped (unavailable)",
                exc_info=True,
            )
            return

        host_sel = getattr(manifest, "host_selections", None)
        if host_sel is not None:
            for category in ("hooks", "skills", "permissions"):
                ids = defaults.get(category) or []
                if ids:
                    setattr(host_sel, category, list(ids))

        # C6 — custom_tools ★ narrows the custom (DB) tools seeded into
        # tools.external. Union with whatever the manifest already has so
        # a preset's own external picks are preserved.
        custom_default = defaults.get("custom_tools") or []
        if custom_default and getattr(manifest, "tools", None) is not None:
            existing = list(getattr(manifest.tools, "external", None) or [])
            merged = existing + [n for n in custom_default if n not in existing]
            manifest.tools.external = merged
            logger.info(
                "create: seeded %d custom_tools default(s) into tools.external",
                len(custom_default),
            )

    def create_blank(
        self,
        name: str,
        description: str = "",
        tags: Optional[List[str]] = None,
        base_preset: Optional[str] = None,
        manifest_override: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a new environment template without a live session.

        When *manifest_override* is supplied (cycle 20260427_1, Library NEW),
        the caller-provided manifest dict is used verbatim — only metadata
        name/description/tags are forced to the API call's values so the
        list view stays consistent. base_preset is ignored in this mode.

        When *base_preset* names a registered PipelinePresets factory, that
        preset's snapshot is used as the starting point. Otherwise the
        library's ``blank_manifest`` seeds every stage inactive with its
        default artifact + strategy picks — the UI renders 21 rows, the
        user toggles what they want, rebuild succeeds.
        """
        if manifest_override is not None:
            manifest = EnvironmentManifest.from_dict(manifest_override)
            # Force caller-provided metadata so the list view matches what
            # the user typed in the create form, regardless of what the
            # draft manifest had cached.
            manifest.metadata.name = name
            manifest.metadata.description = description
            manifest.metadata.tags = list(tags or [])
        elif base_preset:
            manifest = self._manifest_from_preset(
                base_preset, name=name, description=description, tags=tags or []
            )
            # Non-override paths bypass the FE draft seeder — apply the
            # host env-defaults server-side so they still honour ★ (C5).
            self._apply_env_defaults(manifest)
        else:
            manifest = EnvironmentManifest.blank_manifest(
                name, description=description, tags=tags or []
            )
            self._apply_env_defaults(manifest)
        env_id = manifest.metadata.id or _fresh_id()
        self._write_manifest(env_id, manifest)
        return env_id

    def create_from_preset(
        self,
        preset_name: str,
        name: str,
        description: str = "",
        tags: Optional[List[str]] = None,
    ) -> str:
        manifest = self._manifest_from_preset(
            preset_name, name=name, description=description, tags=tags or []
        )
        # Honour host ★ defaults server-side (C5) — this path never goes
        # through the FE draft seeder.
        self._apply_env_defaults(manifest)
        env_id = manifest.metadata.id or _fresh_id()
        self._write_manifest(env_id, manifest)
        return env_id

    def _manifest_from_preset(
        self,
        preset_name: str,
        *,
        name: str,
        description: str,
        tags: List[str],
    ) -> EnvironmentManifest:
        factory = _PRESET_FACTORIES.get(preset_name)
        if factory is None:
            raise ValueError(f"Unknown preset: {preset_name}")
        pipeline = factory(api_key="preset-introspection-key")
        snapshot = PipelineMutator(pipeline).snapshot(description=name)
        return EnvironmentManifest.from_snapshot(
            snapshot,
            name=name,
            description=description,
            tags=tags,
        )

    def update_manifest(
        self, env_id: str, manifest: EnvironmentManifest
    ) -> Dict[str, Any]:
        """Replace the entire manifest payload (template edit)."""
        raw = self._read_raw(env_id)
        if raw is None:
            raise EnvironmentNotFoundError(env_id)
        manifest.metadata.id = env_id
        if not manifest.metadata.created_at:
            manifest.metadata.created_at = raw.get("created_at", _iso_now())
        return self._write_manifest(env_id, manifest, created_at=raw.get("created_at"))

    def update_stage(
        self,
        env_id: str,
        order: int,
        *,
        artifact: Optional[str] = None,
        strategies: Optional[Dict[str, str]] = None,
        strategy_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        config: Optional[Dict[str, Any]] = None,
        tool_binding: Optional[Dict[str, Any]] = None,
        model_override: Optional[Dict[str, Any]] = None,
        chain_order: Optional[Dict[str, List[str]]] = None,
        active: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Patch a single stage in the manifest.

        Only non-None parameters are applied. Raises
        :class:`EnvironmentNotFoundError` if *env_id* is unknown, or
        ``ValueError`` if there is no stage at *order* in the manifest.
        """
        manifest = self.load_manifest(env_id)
        if manifest is None:
            raise EnvironmentNotFoundError(env_id)

        entries = manifest.stage_entries()
        target = next((e for e in entries if e.order == order), None)
        if target is None:
            raise ValueError(f"Stage {order} not found in environment {env_id}")

        if artifact is not None:
            target.artifact = artifact
        if strategies is not None:
            target.strategies = dict(strategies)
        if strategy_configs is not None:
            target.strategy_configs = {k: dict(v) for k, v in strategy_configs.items()}
        if config is not None:
            target.config = dict(config)
        if tool_binding is not None:
            target.tool_binding = dict(tool_binding)
        if model_override is not None:
            target.model_override = dict(model_override)
        if chain_order is not None:
            target.chain_order = {k: list(v) for k, v in chain_order.items()}
        if active is not None:
            target.active = active

        manifest.set_stage_entries(entries)
        manifest.metadata.updated_at = _iso_now()
        return self._write_manifest(env_id, manifest)

    def update_pipeline(
        self,
        env_id: str,
        changes: Dict[str, Any],
    ) -> Dict[str, Any]:
        """P.1 (cycle 20260426_2) — patch the manifest's ``pipeline``
        block with shallow-merge semantics.

        ``changes`` is a dict of ``PipelineConfig`` field names → new
        values. Existing keys not in ``changes`` are preserved. Use this
        instead of :meth:`update_manifest` for granular edits so the UI
        doesn't need to round-trip the whole manifest just to change
        ``max_iterations``.
        """
        manifest = self.load_manifest(env_id)
        if manifest is None:
            raise EnvironmentNotFoundError(env_id)
        if changes:
            manifest.pipeline.update(changes)
        manifest.metadata.updated_at = _iso_now()
        return self._write_manifest(env_id, manifest)

    def update_model(
        self,
        env_id: str,
        changes: Dict[str, Any],
    ) -> Dict[str, Any]:
        """P.1 (cycle 20260426_2) — patch the manifest's ``model`` block
        with shallow-merge semantics.

        ``changes`` is a dict of ``ModelConfig`` field names → new
        values. Existing keys not in ``changes`` are preserved.
        """
        manifest = self.load_manifest(env_id)
        if manifest is None:
            raise EnvironmentNotFoundError(env_id)
        if changes:
            manifest.model.update(changes)
        manifest.metadata.updated_at = _iso_now()
        return self._write_manifest(env_id, manifest)

    def duplicate(self, env_id: str, new_name: str) -> Optional[str]:
        """Deep-copy the environment under a fresh id + name."""
        manifest = self.load_manifest(env_id)
        if manifest is None:
            return None
        new_id = _fresh_id()
        clone = EnvironmentManifest.from_dict(copy.deepcopy(manifest.to_dict()))
        clone.metadata.id = new_id
        clone.metadata.name = new_name
        clone.metadata.created_at = _iso_now()
        clone.metadata.updated_at = _iso_now()
        self._write_manifest(new_id, clone)
        return new_id

    async def instantiate_pipeline(
        self,
        env_id: str,
        *,
        credentials: Optional[Any] = None,
        api_key: Optional[str] = None,
        subagent_registry: Optional[Any] = None,
        strict: bool = True,
        adhoc_providers: Sequence[Any] = (),
        extra_external_tools: Sequence[str] = (),
        extra_mcp_servers: Sequence[Any] = (),
        satisfied_config: Optional[Any] = None,
    ) -> Pipeline:
        """Load the manifest and build a Pipeline via the library helper.

        Phase E2 of the LLM backend upgrade — the canonical credential
        channel is ``credentials`` (a geny-executor
        :class:`CredentialBundle`). ``api_key`` is retained as a thin
        compatibility shim that wraps a single Anthropic key into a
        bundle so older call sites keep working until they migrate.

        ``subagent_registry`` is forwarded to
        ``Pipeline.from_manifest_async`` so Stage 12's ``subagent_type``
        orchestrator is wired with the host's seed of sub-agent
        descriptors.

        Uses :meth:`Pipeline.from_manifest_async` so that any
        ``tools.mcp_servers`` declared in the manifest are connected
        before the pipeline is returned, and ``adhoc_providers`` get a
        chance to register their tools against
        ``manifest.tools.external``.

        The Stage-6 provider on the loaded manifest is the *single*
        source of truth. A prior version of this method (PR #861)
        rewrote it in-memory from ``LLMCredentialsConfig.default_provider``
        — that bypass layer is removed. The active backend now flows
        through the canonical path: ``install_environment_templates``
        bakes ``pick_default_backend_provider()`` into the template
        envs at boot, and the user edits per-env manifests directly
        for any custom routing. Environment = source of truth.
        """
        manifest = self.load_manifest(env_id)
        if manifest is None:
            raise EnvironmentNotFoundError(env_id)
        # Platform core-tool promotion at BUILD time (not just template
        # creation): envs persisted before a pattern was added would
        # otherwise never receive it — the stored core_overrides snapshot
        # is frozen at env creation. ``_promote_core_tools`` is idempotent
        # and merge-safe (setdefault — a user's deliberate override wins),
        # so applying it on every build is the robust path.
        try:
            from service.environment.templates import _promote_core_tools

            _promote_core_tools(manifest)
        except Exception:  # noqa: BLE001 — promotion must never block a build
            pass
        # Sandbox tool packs (per-env opt-in): union the selected packs' tool
        # names into tools.external so they activate like custom tools. The
        # pack provider (resolving these names) is passed in adhoc_providers.
        if extra_external_tools:
            existing = list(getattr(manifest.tools, "external", None) or [])
            merged = existing + [t for t in extra_external_tools if t not in existing]
            manifest.tools.external = merged
        # MCP connectors (config-gated): append configured connectors' MCP server
        # dicts to mcp_servers so the executor connects them + their tools appear.
        # Gate is omission — only configured connectors are passed in (see
        # service.mcp_connectors). Dedup by name; env-defined servers win.
        if extra_mcp_servers:
            existing_srv = list(getattr(manifest.tools, "mcp_servers", None) or [])
            have = {s.get("name") for s in existing_srv if isinstance(s, dict)}
            for srv in extra_mcp_servers:
                if isinstance(srv, dict) and srv.get("name") and srv["name"] not in have:
                    existing_srv.append(srv)
                    have.add(srv["name"])
            manifest.tools.mcp_servers = existing_srv
        # Route providers to the correct executor channel by capability:
        #   * get-style (``get`` + ``list_names``) → ``adhoc_providers`` —
        #     resolve manifest.tools.external by name (GenyToolProvider, …).
        #   * MCP-style (``startup``/``list_tools``, no ``get``) →
        #     ``tool_providers`` — STARTED via register_providers so their
        #     tools (e.g. the SkillToolProvider's per-skill tools) actually
        #     register, and so the self-modifying-env controller can find the
        #     skill registry. Passing these via adhoc never started them (skills
        #     silently surfaced 0 tools) and risked a ``.get`` crash.
        get_style, started_style = [], []
        for p in adhoc_providers or ():
            if callable(getattr(p, "get", None)) and callable(getattr(p, "list_names", None)):
                get_style.append(p)
            elif callable(getattr(p, "startup", None)) or callable(getattr(p, "list_tools", None)):
                started_style.append(p)
            else:
                get_style.append(p)
        return await Pipeline.from_manifest_async(
            manifest,
            credentials=credentials,
            api_key=api_key,
            subagent_registry=subagent_registry,
            strict=strict,
            adhoc_providers=get_style,
            tool_providers=started_style or None,
            satisfied_config=satisfied_config,
        )

    # ── Reconcile ──────────────────────────────────────────────

    def _reconcile(self) -> None:
        """Align DB + JSON-file backends at startup. DB wins on conflict.

        Strategy mirrors ToolPresetStore (Phase 2A):
          1. Every DB record is mirrored to its on-disk JSON file.
          2. Every JSON-file env not in the DB is pushed up (covers
             "DB was down when user created env X" recovery).
          3. Orphans on either side stay; deletes remain explicit.
        """
        if not self._db_available:
            logger.info("EnvironmentService: reconcile skipped (DB unavailable)")
            return

        try:
            db_records = {
                rec["id"]: rec for rec in self._list_raw_from_db() if rec.get("id")
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("EnvironmentService: reconcile DB read failed: %s", exc)
            return

        file_records: Dict[str, Dict[str, Any]] = {}
        for f in sorted(self._storage.glob("*.json")):
            try:
                rec = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            env_id = rec.get("id")
            if env_id:
                file_records[env_id] = rec

        mirrored = 0
        for env_id, rec in db_records.items():
            try:
                self._path(env_id).write_text(
                    json.dumps(rec, ensure_ascii=False, indent=2),
                )
                mirrored += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "EnvironmentService: reconcile mirror failed for %s: %s",
                    env_id, exc,
                )

        pushed = 0
        for env_id, rec in file_records.items():
            if env_id in db_records:
                continue
            try:
                self._upsert_to_db(env_id, rec)
                pushed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "EnvironmentService: reconcile push failed for %s: %s",
                    env_id, exc,
                )

        logger.info(
            "EnvironmentService: reconcile done — db_rows=%d, files=%d, mirrored=%d, pushed=%d",
            len(db_records), len(file_records), mirrored, pushed,
        )

    # ── Diff ───────────────────────────────────────────────────

    def diff(self, env_id_a: str, env_id_b: str) -> List[Dict[str, Any]]:
        a = self._read_raw(env_id_a)
        b = self._read_raw(env_id_b)
        return self.diff_from_raw(a, b)

    def diff_from_raw(
        self,
        raw_a: Optional[Dict[str, Any]],
        raw_b: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Compute a diff between two already-loaded env records.

        Exposed so callers doing many pairwise diffs (e.g. the
        `/diff-bulk` matrix endpoint) can load each unique env once and
        then iterate over pairs without repeating the filesystem read.
        Mirrors `diff`'s empty-on-missing contract.
        """
        if raw_a is None or raw_b is None:
            return []
        left = raw_a.get("manifest") or raw_a.get("snapshot") or {}
        right = raw_b.get("manifest") or raw_b.get("snapshot") or {}
        changes: List[Dict[str, Any]] = []
        self._diff_recursive(left, right, "", changes)
        return changes

    def read_raw(self, env_id: str) -> Optional[Dict[str, Any]]:
        """Public wrapper around `_read_raw` for callers that need the
        raw record without going through `load()`'s manifest coercion.

        Used by the `/diff-bulk` endpoint to cache one read per unique
        env id across all pairs in the batch.
        """
        return self._read_raw(env_id)

    def _diff_recursive(
        self,
        old: Any,
        new: Any,
        prefix: str,
        changes: List[Dict[str, Any]],
    ) -> None:
        if isinstance(old, dict) and isinstance(new, dict):
            all_keys = set(old) | set(new)
            for k in sorted(all_keys):
                path = f"{prefix}.{k}" if prefix else k
                if k not in old:
                    changes.append(
                        {
                            "path": path,
                            "type": "added",
                            "old_value": None,
                            "new_value": new[k],
                        }
                    )
                elif k not in new:
                    changes.append(
                        {
                            "path": path,
                            "type": "removed",
                            "old_value": old[k],
                            "new_value": None,
                        }
                    )
                else:
                    self._diff_recursive(old[k], new[k], path, changes)
        elif isinstance(old, list) and isinstance(new, list):
            for i in range(max(len(old), len(new))):
                path = f"{prefix}[{i}]"
                if i >= len(old):
                    changes.append(
                        {
                            "path": path,
                            "type": "added",
                            "old_value": None,
                            "new_value": new[i],
                        }
                    )
                elif i >= len(new):
                    changes.append(
                        {
                            "path": path,
                            "type": "removed",
                            "old_value": old[i],
                            "new_value": None,
                        }
                    )
                else:
                    self._diff_recursive(old[i], new[i], path, changes)
        elif old != new:
            changes.append(
                {"path": prefix, "type": "changed", "old_value": old, "new_value": new}
            )


def _row_to_record(row: Any) -> Optional[Dict[str, Any]]:
    """Decode an ``environments.data`` row into the raw env record.

    psycopg returns JSONB as a Python dict by default; older drivers
    can hand back a string. Handle both. Returns the same shape as
    the on-disk JSON file (``id``, ``name``, ``manifest``, etc.).
    """
    if row is None:
        return None
    raw = row.get("data") if isinstance(row, dict) else row[0]
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse environment JSON from DB: %s", exc)
            return None
    if not isinstance(raw, dict):
        return None
    return raw
