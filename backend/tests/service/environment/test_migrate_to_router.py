"""Collapsing the harness for environments that already exist.

Installing three new seeds did not collapse anything: the eight per-backend
seeds stayed on disk and every user environment kept naming the provider it
was created with. A session bound to one of those runs its turns through that
provider directly — it never reaches the route, never fails over, and when
that backend is out of quota every single turn fails with the raw error.

That is what production did. The live session sat on an env pinned to
``claude_code_cli``, the subscription had hit its spend cap, and a working
OpenAI account sat unused in the route.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from geny_executor import build_manifest
from service.environment.migrate_to_router import (
    SUPERSEDED_SEED_ENV_IDS,
    migrate_environments_to_router,
)


class _Service:
    """The four EnvironmentService methods the migration touches."""

    def __init__(self, envs: Dict[str, Any]) -> None:
        self.envs = dict(envs)
        self.writes: List[str] = []
        self.deletes: List[str] = []

    def list_all(self) -> List[Dict[str, Any]]:
        return [{"id": env_id, "name": env_id} for env_id in self.envs]

    def load_manifest(self, env_id: str) -> Any:
        return self.envs.get(env_id)

    def _write_manifest(self, env_id: str, manifest: Any) -> None:
        self.envs[env_id] = manifest
        self.writes.append(env_id)

    def delete(self, env_id: str) -> bool:
        existed = env_id in self.envs
        self.envs.pop(env_id, None)
        self.deletes.append(env_id)
        return existed

    def provider_of(self, env_id: str) -> Optional[str]:
        manifest = self.envs[env_id]
        for entry in manifest.stage_entries():
            if entry.order == 6:
                return (entry.config or {}).get("provider")
        return None


def _env(provider: str) -> Any:
    return build_manifest("default", provider=provider)


class TestSupersededSeeds:
    def test_the_per_backend_seeds_are_removed(self) -> None:
        """They exist only to offer a choice that no longer exists, and
        leaving them in the picker invites someone to pick one again."""
        service = _Service({env_id: _env("claude_code_cli") for env_id in SUPERSEDED_SEED_ENV_IDS})
        result = migrate_environments_to_router(service)
        assert sorted(result["deleted"]) == sorted(SUPERSEDED_SEED_ENV_IDS)
        assert service.envs == {}

    def test_the_three_that_remain_are_kept(self) -> None:
        """Worker / VTuber / VSCode differ by tools and persona, which is a
        real difference. The deleted ones differed by provider."""
        service = _Service({
            "template-worker-env": _env("geny_router"),
            "template-vtuber-env": _env("geny_router"),
            "template-vscode-env": _env("geny_router"),
        })
        migrate_environments_to_router(service)
        assert set(service.envs) == {
            "template-worker-env", "template-vtuber-env", "template-vscode-env",
        }

    def test_sessions_are_moved_before_the_env_disappears(self) -> None:
        """Deleting first would leave them pointing at nothing."""
        service = _Service({"template-claude-code-vtuber-env": _env("claude_code_cli")})
        moved: List[Tuple[str, str]] = []

        def rebind(old: str, new: str) -> int:
            assert old in service.envs, "rebind must run while the env still exists"
            moved.append((old, new))
            return 1

        result = migrate_environments_to_router(service, rebind=rebind)
        assert moved == [("template-claude-code-vtuber-env", "template-vtuber-env")]
        assert result["rebound"] == 1

    def test_a_worker_seed_rebinds_to_the_worker(self) -> None:
        service = _Service({"template-openai-worker-env": _env("openai")})
        moved: List[Tuple[str, str]] = []
        migrate_environments_to_router(service, rebind=lambda o, n: moved.append((o, n)) or 1)
        assert moved == [("template-openai-worker-env", "template-worker-env")]


class TestRepointing:
    def test_a_user_environment_moves_onto_the_route(self) -> None:
        """Their tool roster and persona are theirs and are untouched. The
        provider was the one field that is no longer an environment's
        business."""
        service = _Service({"엘렌_new": _env("claude_code_cli")})
        result = migrate_environments_to_router(service)
        assert service.provider_of("엘렌_new") == "geny_router"
        assert result["repointed"] == [("엘렌_new", "claude_code_cli")]

    @pytest.mark.parametrize("provider", ["anthropic", "openai", "ollama", "claude_code_cli"])
    def test_every_legacy_provider_is_repointed(self, provider: str) -> None:
        service = _Service({"custom": _env(provider)})
        migrate_environments_to_router(service)
        assert service.provider_of("custom") == "geny_router"

    def test_an_environment_already_on_the_router_is_not_rewritten(self) -> None:
        service = _Service({"template-worker-env": _env("geny_router")})
        result = migrate_environments_to_router(service)
        assert result["repointed"] == []
        assert service.writes == []

    def test_the_legacy_strategies_home_is_cleared(self) -> None:
        """A provider left in strategies fails a strict manifest load — and it
        is the exact field this migration retires."""
        manifest = _env("anthropic")
        entries = manifest.stage_entries()
        for entry in entries:
            if entry.order == 6:
                entry.strategies = {**(entry.strategies or {}), "provider": "anthropic"}
        manifest.set_stage_entries(entries)

        service = _Service({"legacy": manifest})
        migrate_environments_to_router(service)
        stage6 = next(e for e in service.envs["legacy"].stage_entries() if e.order == 6)
        assert "provider" not in (stage6.strategies or {})
        assert (stage6.config or {})["provider"] == "geny_router"

    def test_the_rest_of_the_environment_survives(self) -> None:
        manifest = build_manifest(
            "default", provider="openai",
            external_tools=["web_search", "memory_write"], built_in_tools=["*"],
        )
        service = _Service({"mine": manifest})
        migrate_environments_to_router(service)
        kept = service.envs["mine"]
        assert kept.tools.external == ["web_search", "memory_write"]
        assert kept.tools.built_in == ["*"]
        assert len(kept.stages) == 21


class TestSafety:
    def test_running_twice_changes_nothing_the_second_time(self) -> None:
        service = _Service({
            "template-openai-worker-env": _env("openai"),
            "mine": _env("anthropic"),
        })
        migrate_environments_to_router(service)
        service.writes.clear()
        service.deletes.clear()
        second = migrate_environments_to_router(service)
        assert second == {"deleted": [], "repointed": [], "rebound": 0}
        assert service.writes == [] and service.deletes == []

    def test_one_broken_environment_does_not_stop_the_rest(self) -> None:
        class _Broken(_Service):
            def load_manifest(self, env_id: str) -> Any:
                if env_id == "corrupt":
                    raise ValueError("unreadable manifest")
                return super().load_manifest(env_id)

        service = _Broken({"corrupt": None, "mine": _env("openai")})
        migrate_environments_to_router(service)
        assert service.provider_of("mine") == "geny_router"

    def test_a_service_that_cannot_list_is_not_fatal(self) -> None:
        class _Down:
            def list_all(self) -> Any:
                raise RuntimeError("database is down")

        assert migrate_environments_to_router(_Down()) == {
            "deleted": [], "repointed": [], "rebound": 0,
        }
