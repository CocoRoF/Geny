"""Geny-side Environment system.

Bridges geny-executor v0.20.0's :class:`EnvironmentManifest` persistence
model into Geny. Port of :mod:`geny_executor_web.app.services.environment_service`
with identical JSON layout on disk — existing web-created environments
can be copied into Geny's storage root without conversion.

Phase 3 scope: service + exceptions only. Routers (controller layer) and
the `env_id` / `memory_config` extension on `POST /api/agents` arrive in
separate PRs (see ``plan/06_rollout_and_verification.md`` entries 6-8).
"""

from service.environment.exceptions import (
    EnvironmentNotFoundError,
    StageValidationError,
)
from service.environment.service import EnvironmentService

__all__ = [
    "EnvironmentNotFoundError",
    "EnvironmentService",
    "StageValidationError",
]
