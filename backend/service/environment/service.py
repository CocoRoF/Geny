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
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from geny_executor import (
    EnvironmentManifest,
    Pipeline,
    PipelineMutator,
    PipelinePresets,
    PipelineSnapshot,
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


# Stage orders that are structurally required for any pipeline. Mirrors
# ``geny_executor.core.introspection._STAGE_REQUIRED`` (s01_input, s06_api,
# s09_parse, s16_yield). Enforced on every write so a client that sends
# ``active=False`` — whether by accident, via a stale payload, or by
# editing the JSON directly — cannot persist a pipeline that the runtime
# would refuse to build.
_REQUIRED_ORDERS: frozenset[int] = frozenset({1, 6, 9, 16})


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


class EnvironmentService:
    """Save, load, diff, and mutate pipeline environments on disk."""

    def __init__(self, storage_path: Optional[str] = None) -> None:
        path = storage_path or _default_storage_path()
        self._storage = Path(path)
        self._storage.mkdir(parents=True, exist_ok=True)

    @property
    def storage_path(self) -> Path:
        return self._storage

    # ── File layout helpers ────────────────────────────────────

    def _path(self, env_id: str) -> Path:
        return self._storage / f"{env_id}.json"

    def _read_raw(self, env_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(env_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None

    def _write_raw(self, env_id: str, data: Dict[str, Any]) -> None:
        self._path(env_id).write_text(json.dumps(data, ensure_ascii=False, indent=2))

    # ── Manifest load / save ───────────────────────────────────

    def load_manifest(self, env_id: str) -> Optional[EnvironmentManifest]:
        """Return the stored environment as a v2 :class:`EnvironmentManifest`.

        Accepts both the current ``manifest`` layout and the legacy
        ``snapshot`` layout written by v0.7.x. Manifests written before
        geny-executor 0.13.5 may carry ``provider: mock`` on the s06_api
        stage because introspection used MockProvider; those are rewritten
        to ``anthropic`` on load so runtime sessions hit the real API.
        """
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

        self._migrate_legacy_mock_provider(manifest)
        return manifest

    @staticmethod
    def _force_required_stages_active(manifest: EnvironmentManifest) -> None:
        """Coerce every required stage's ``active`` flag to ``True``.

        Runs on every write so a client payload (or edited JSON) cannot
        persist a required stage in an inactive state. The UI already hides
        the toggle for required stages; this is the last-line defence
        behind it.
        """
        entries = manifest.stage_entries()
        changed = False
        for entry in entries:
            if entry.order in _REQUIRED_ORDERS and not entry.active:
                entry.active = True
                changed = True
        if changed:
            manifest.set_stage_entries(entries)

    @staticmethod
    def _migrate_legacy_mock_provider(manifest: EnvironmentManifest) -> None:
        """Rewrite pre-0.13.5 ``s06_api.strategies.provider = 'mock'`` entries.

        Older blank manifests recorded ``mock`` because introspection used
        MockProvider to instantiate APIStage session-lessly. At runtime that
        meant ``PipelineMutator.restore()`` swapped the real AnthropicProvider
        for MockProvider, producing ``"Mock response"`` instead of real API
        calls. The library is fixed forward; this rewrites the on-load view
        of stale manifests so existing envs behave correctly without a
        manual re-save.
        """
        entries = manifest.stage_entries()
        changed = False
        for entry in entries:
            if entry.order != 6 or entry.artifact != "default":
                continue
            if entry.strategies.get("provider") == "mock":
                entry.strategies["provider"] = "anthropic"
                changed = True
        if changed:
            manifest.set_stage_entries(entries)

    def _write_manifest(
        self,
        env_id: str,
        manifest: EnvironmentManifest,
        *,
        created_at: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist *manifest* to disk in v2 layout and return the full record."""
        manifest.metadata.id = env_id
        self._force_required_stages_active(manifest)
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
        """List stored environments with UI-friendly summaries."""
        result: List[Dict[str, Any]] = []
        for f in sorted(self._storage.glob("*.json")):
            try:
                data = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            summary = self._summarize(data)
            if summary is not None:
                result.append(summary)
        return result

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
        path = self._path(env_id)
        if path.exists():
            path.unlink()
            return True
        return False

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
            self._force_required_stages_active(manifest)
            data["manifest"] = manifest.to_dict()
            data.pop("snapshot", None)
        elif "manifest" in data and isinstance(data["manifest"], dict):
            migrated = EnvironmentManifest.from_dict(data["manifest"])
            migrated.metadata.id = env_id
            self._force_required_stages_active(migrated)
            data["manifest"] = migrated.to_dict()

        self._write_raw(env_id, data)
        return env_id

    # ── v2 — template CRUD ─────────────────────────────────────

    def create_blank(
        self,
        name: str,
        description: str = "",
        tags: Optional[List[str]] = None,
        base_preset: Optional[str] = None,
    ) -> str:
        """Create a new environment template without a live session.

        When *base_preset* names a registered PipelinePresets factory, that
        preset's snapshot is used as the starting point. Otherwise the
        library's ``blank_manifest`` seeds every stage inactive with its
        default artifact + strategy picks — the UI renders 16 rows, the
        user toggles what they want, rebuild succeeds.
        """
        if base_preset:
            manifest = self._manifest_from_preset(
                base_preset, name=name, description=description, tags=tags or []
            )
        else:
            manifest = EnvironmentManifest.blank_manifest(
                name, description=description, tags=tags or []
            )
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
        api_key: str,
        strict: bool = True,
        adhoc_providers: Sequence[Any] = (),
    ) -> Pipeline:
        """Load the manifest and build a Pipeline via the library helper.

        Uses :meth:`Pipeline.from_manifest_async` (geny-executor v0.22+)
        so that any ``tools.mcp_servers`` declared in the manifest are
        connected before the pipeline is returned, and
        ``adhoc_providers`` get a chance to register their tools against
        ``manifest.tools.external``.
        """
        manifest = self.load_manifest(env_id)
        if manifest is None:
            raise EnvironmentNotFoundError(env_id)
        return await Pipeline.from_manifest_async(
            manifest,
            api_key=api_key,
            strict=strict,
            adhoc_providers=adhoc_providers,
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
