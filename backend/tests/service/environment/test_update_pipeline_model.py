"""P.1 (cycle 20260426_2) — pipeline + model patch service tests.

Verifies that ``EnvironmentService.update_pipeline`` /
``update_model`` shallow-merge the given keys into ``manifest.pipeline``
and ``manifest.model`` respectively, leaving unspecified keys untouched.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

# pydantic + executor required transitively.
pytest.importorskip("pydantic")
pytest.importorskip("geny_executor")

from geny_executor.core.environment import EnvironmentManifest  # noqa: E402

from service.environment.exceptions import EnvironmentNotFoundError  # noqa: E402
from service.environment.service import EnvironmentService  # noqa: E402


@pytest.fixture
def svc(tmp_path) -> EnvironmentService:
    return EnvironmentService(storage_path=str(tmp_path))


def _new_env(svc: EnvironmentService) -> str:
    """Create a blank env and seed the model + pipeline blocks with
    initial values so the merge tests have something concrete to
    compare against."""
    env_id = svc.create_blank(name="P1-test", description="patch test")
    manifest = svc.load_manifest(env_id)
    assert manifest is not None
    manifest.pipeline = {
        "max_iterations": 50,
        "context_window_budget": 200_000,
    }
    manifest.model = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 8192,
        "temperature": 0.0,
    }
    svc.update_manifest(env_id, manifest)
    return env_id


def test_update_pipeline_merges_changes(svc: EnvironmentService) -> None:
    env_id = _new_env(svc)
    record = svc.update_pipeline(env_id, {"max_iterations": 5})
    pipeline: Dict[str, Any] = record["manifest"]["pipeline"]
    # Changed key takes the new value.
    assert pipeline["max_iterations"] == 5
    # Untouched key preserved.
    assert pipeline["context_window_budget"] == 200_000


def test_update_pipeline_adds_new_key(svc: EnvironmentService) -> None:
    env_id = _new_env(svc)
    record = svc.update_pipeline(env_id, {"cost_budget_usd": 1.5})
    pipeline = record["manifest"]["pipeline"]
    assert pipeline["cost_budget_usd"] == 1.5
    # Existing keys still present.
    assert pipeline["max_iterations"] == 50


def test_update_pipeline_empty_changes_is_noop(svc: EnvironmentService) -> None:
    env_id = _new_env(svc)
    record = svc.update_pipeline(env_id, {})
    assert record["manifest"]["pipeline"]["max_iterations"] == 50


def test_update_pipeline_unknown_env(svc: EnvironmentService) -> None:
    with pytest.raises(EnvironmentNotFoundError):
        svc.update_pipeline("nope", {"max_iterations": 3})


def test_update_model_merges_changes(svc: EnvironmentService) -> None:
    env_id = _new_env(svc)
    record = svc.update_model(env_id, {"temperature": 0.7})
    model = record["manifest"]["model"]
    assert model["temperature"] == 0.7
    # Untouched key preserved.
    assert model["model"] == "claude-sonnet-4-20250514"
    assert model["max_tokens"] == 8192


def test_update_model_adds_thinking_fields(svc: EnvironmentService) -> None:
    env_id = _new_env(svc)
    record = svc.update_model(
        env_id,
        {"thinking_enabled": True, "thinking_budget_tokens": 5000},
    )
    model = record["manifest"]["model"]
    assert model["thinking_enabled"] is True
    assert model["thinking_budget_tokens"] == 5000


def test_update_model_unknown_env(svc: EnvironmentService) -> None:
    with pytest.raises(EnvironmentNotFoundError):
        svc.update_model("nope", {"temperature": 0.5})


def test_update_pipeline_does_not_touch_model(svc: EnvironmentService) -> None:
    """Crossover guard: pipeline changes must not bleed into model dict."""
    env_id = _new_env(svc)
    svc.update_pipeline(env_id, {"max_iterations": 7})
    manifest = svc.load_manifest(env_id)
    assert manifest is not None
    assert manifest.model.get("temperature") == 0.0
    assert "max_iterations" not in manifest.model


def test_round_trip_through_executor_manifest(svc: EnvironmentService) -> None:
    """The patched manifest must still parse via EnvironmentManifest.from_dict —
    our shallow merge can't introduce keys the executor would reject."""
    env_id = _new_env(svc)
    svc.update_pipeline(env_id, {"max_iterations": 12, "stream": False})
    svc.update_model(env_id, {"temperature": 0.3, "thinking_enabled": True})
    raw = svc.read_raw(env_id)
    assert raw is not None
    # Throws if any key is invalid.
    EnvironmentManifest.from_dict(raw["manifest"])
