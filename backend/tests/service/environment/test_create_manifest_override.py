"""Cycle 20260427_1 — Library (NEW) tab create-with-manifest_override path.

The new builder tab assembles a full EnvironmentManifest client-side then
POSTs it as a single create call. This test confirms the service-layer
hook honours the override (instead of seeding from blank_manifest()) and
forces caller-supplied metadata so the env list reflects what the user
typed in the create form.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("geny_executor")

from geny_executor.core.environment import EnvironmentManifest  # noqa: E402

from service.environment.service import EnvironmentService  # noqa: E402


@pytest.fixture
def svc(tmp_path) -> EnvironmentService:
    return EnvironmentService(storage_path=str(tmp_path))


def _draft_manifest() -> dict:
    """Stand-in for a draft manifest the new tab would post — start
    from blank_manifest() then mutate one stage so we can assert the
    override actually took precedence over a fresh blank seed."""
    base = EnvironmentManifest.blank_manifest("draft-name")
    payload = base.to_dict()
    # Mark stage 6 (api) as active so we can verify the override
    # survives create.
    for stage in payload["stages"]:
        if stage["order"] == 6:
            stage["active"] = True
            stage.setdefault("config", {})["test_marker"] = "from-draft"
            break
    return payload


def test_manifest_override_is_used_verbatim(svc: EnvironmentService) -> None:
    draft = _draft_manifest()

    env_id = svc.create_blank(
        name="from-builder",
        description="created via Library NEW",
        tags=["beta"],
        manifest_override=draft,
    )

    loaded = svc.load_manifest(env_id)
    assert loaded is not None
    # Stage 6 mutation came through — proves blank_manifest() did NOT
    # silently re-seed.
    stage_six = next(s for s in loaded.stages if s.order == 6)
    assert stage_six.active is True
    assert stage_six.config.get("test_marker") == "from-draft"


def test_manifest_override_forces_metadata(svc: EnvironmentService) -> None:
    draft = _draft_manifest()
    # Draft has stale metadata.name from when it was first instantiated.
    draft["metadata"]["name"] = "stale-cached-name"
    draft["metadata"]["description"] = "cached desc"
    draft["metadata"]["tags"] = ["cached"]

    env_id = svc.create_blank(
        name="user-typed-this",
        description="user typed this too",
        tags=["fresh", "tag"],
        manifest_override=draft,
    )

    loaded = svc.load_manifest(env_id)
    assert loaded is not None
    # Caller-provided metadata wins over the draft's stale cache so the
    # env list view matches the create form.
    assert loaded.metadata.name == "user-typed-this"
    assert loaded.metadata.description == "user typed this too"
    assert list(loaded.metadata.tags) == ["fresh", "tag"]


def test_manifest_override_assigns_fresh_id_when_blank(
    svc: EnvironmentService,
) -> None:
    """The draft's metadata.id is empty by default. Service should mint a
    fresh env_<8-hex> id rather than persist the empty string."""
    draft = _draft_manifest()
    draft["metadata"]["id"] = ""

    env_id = svc.create_blank(
        name="autoid", manifest_override=draft
    )

    assert env_id.startswith("env_")
    loaded = svc.load_manifest(env_id)
    assert loaded is not None
    assert loaded.metadata.id == env_id
