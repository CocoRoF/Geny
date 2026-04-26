"""D.2 (cycle 20260426_1) — known section reader map.

The ``register_section`` API lets host code register Pydantic schemas
for any settings.json section name. The framework-settings UI happily
edits any registered section, but it doesn't tell the operator
*who reads the section at runtime*. A misnamed section silently
no-ops — the JSON sits in ~/.geny/settings.json and no executor
module ever consults it.

This map is the single-file source of truth for "section X is read by
modules M1, M2, …". It powers:

- ``GET /api/admin/framework-section-readers`` (D.2 admin endpoint)
- The "read by:" hint beside each section row in
  ``FrameworkSettingsPanel.tsx``.

Update this file whenever a new ``register_section`` call is added.
The list is intentionally maintained by hand — automatic discovery
would require importing every reader module at registry-build time
and grepping for ``get_section`` calls; that's heavier than the
maintenance cost of a 10-line dict.
"""

from __future__ import annotations

from typing import Dict, List


# Each value is a list of dotted module paths (or pseudo-paths like
# ``executor:hooks`` for executor-internal readers we don't directly
# import in Geny). The order is "user-relevant first" — the operator
# sees a comma-joined string and the first reader matters most.
SECTION_READERS: Dict[str, List[str]] = {
    "preset": [
        "service.preset_manager",
    ],
    "vtuber": [
        "service.vtuber.config_loader",
    ],
    "hooks": [
        "service.hooks.install",
    ],
    "skills": [
        "service.skills.install",
    ],
    "model": [
        # Read by the executor's pipeline config bridge during manifest
        # instantiation (executor 1.3.0 — bake_model_defaults).
        "executor:core.config",
    ],
    "telemetry": [
        # Read by Geny's telemetry bootstrap when present; absent =
        # framework defaults.
        "service.telemetry.config",
    ],
    "notifications": [
        "service.notifications.install",
    ],
    "permissions": [
        "service.permission.install",
    ],
    # G.1 (cycle 20260426_2) — memory provider config.
    "memory": [
        "service.memory_provider.config",
    ],
    # G.3 (cycle 20260426_2) — affect tag emitter knob.
    "affect": [
        "service.emit.chain_install",
    ],
    # L.1 (cycle 20260426_3) — SendMessageChannel registry config.
    "channels": [
        "service.notifications.install",
    ],
}


def readers_for(section_name: str) -> List[str]:
    """Return the reader list for a section, or empty list if unknown.

    A section that's registered (via ``register_section``) but not in
    this map is a code smell — either the registration is dead or this
    file is out of date. The admin endpoint flags this case.
    """
    return list(SECTION_READERS.get(section_name, ()))


__all__ = ["SECTION_READERS", "readers_for"]
