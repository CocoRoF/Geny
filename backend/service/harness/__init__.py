"""The harness of one agent: what it is running, and what of that can change.

``view`` answers the first question from the live pipeline (never from the
manifest, which describes placeholders Geny replaces at build time).
``catalogue`` answers the second — which of the 33 replaceable parts a person
should be offered, and which are what this product IS rather than how it
happens to be configured.
"""

from service.harness.catalogue import (
    BASIC_SLOTS,
    LOCKED_SLOTS,
    RUNTIME_INSTALLED,
    STAGE_GROUPS,
    lock_reason,
    tier_of,
)
from service.harness.view import build_harness_view, slot_catalogue

__all__ = [
    "BASIC_SLOTS",
    "LOCKED_SLOTS",
    "RUNTIME_INSTALLED",
    "STAGE_GROUPS",
    "build_harness_view",
    "lock_reason",
    "slot_catalogue",
    "tier_of",
]
