"""What this agent's harness is ACTUALLY running.

The manifest is not the answer. Geny declares placeholders in it and then
installs the real implementations when the session is built — the guard
chain, the session's file persister, the HITL resume requester, the
persisting compactor, the affect emitter. A page rendered from the manifest
would show ``no_persist`` on a stage that persists and an empty guard chain
on a session that guards, which is the same class of mistake as drawing a
capability switch from a sparse override: a partial truth presented as the
whole one.

So the view is built from the **live pipeline** — `describe()` reports what
each slot currently holds — and every value is labelled with where it came
from:

``default``   the stage's own, nobody said otherwise
``manifest``  the one environment declared it
``runtime``   Geny installed it when this session was built
``session``   this agent was told to

That label is the whole point. Without it the page can tell you what is
running but not whether changing it will stick.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from service.harness.catalogue import (
    BASIC_SLOTS,
    RUNTIME_INSTALLED,
    STAGE_GROUPS,
    lock_reason,
    tier_of,
)

logger = logging.getLogger(__name__)

__all__ = ["build_harness_view", "slot_catalogue"]


#: ``(order, slot)`` → introspection, built once. Class-level metadata: what
#: each implementation is called, what it does, and the config schema its
#: form needs. Free of any session.
_CATALOGUE: Optional[Dict[str, Any]] = None


def slot_catalogue() -> Dict[str, Any]:
    """Descriptions + config schemas for every slot, keyed ``"<order>.<slot>"``.

    Read from the library rather than restated here — a description copied
    into Geny is one that stops matching the code it describes.
    """
    global _CATALOGUE
    if _CATALOGUE is not None:
        return _CATALOGUE

    catalogue: Dict[str, Any] = {}
    try:
        from geny_executor.core.introspection import introspect_all

        for entry in introspect_all():
            order = entry.order
            for name, slot in (entry.strategy_slots or {}).items():
                catalogue[f"{order}.{name}"] = {
                    "description": slot.description or "",
                    "implDescriptions": dict(slot.impl_descriptions or {}),
                    "implSchemas": _schemas(slot.impl_schemas),
                    "isChain": False,
                }
            for name, chain in (entry.strategy_chains or {}).items():
                catalogue[f"{order}.{name}"] = {
                    "description": chain.description or "",
                    "implDescriptions": dict(chain.impl_descriptions or {}),
                    "implSchemas": _schemas(chain.impl_schemas),
                    "isChain": True,
                }
    except Exception:  # noqa: BLE001 — a settings page, never a turn
        logger.warning("harness catalogue unavailable", exc_info=True)
    _CATALOGUE = catalogue
    return catalogue


def _schemas(raw: Any) -> Dict[str, Any]:
    """``{impl: ConfigSchema}`` → plain dicts a form can render."""
    out: Dict[str, Any] = {}
    for impl, schema in (raw or {}).items():
        if schema is None:
            continue
        fields = []
        for f in getattr(schema, "fields", None) or []:
            fields.append(
                {
                    "name": f.name,
                    "type": f.type,
                    "label": f.label or f.name,
                    "description": f.description or "",
                    "default": f.default,
                    "required": bool(f.required),
                    "minValue": f.min_value,
                    "maxValue": f.max_value,
                    "options": f.options,
                    "itemType": f.item_type,
                }
            )
        if fields:
            out[str(impl)] = {"fields": fields}
    return out


def _manifest_slots(manifest: Any) -> Dict[int, Dict[str, Any]]:
    """``{order: {"strategies": {...}, "config": {...}, "chains": {...}}}``."""
    declared: Dict[int, Dict[str, Any]] = {}
    try:
        for entry in manifest.stage_entries():
            declared[int(entry.order)] = {
                "strategies": dict(entry.strategies or {}),
                "config": dict(entry.config or {}),
                "strategyConfigs": dict(entry.strategy_configs or {}),
                "chains": dict(entry.chain_order or {}),
                "active": bool(entry.active),
            }
    except Exception:  # noqa: BLE001
        logger.debug("manifest not readable for the harness view", exc_info=True)
    return declared


def _source_of(
    order: int,
    slot: str,
    value: Any,
    declared: Dict[int, Dict[str, Any]],
    overlay_slots: Dict[str, Any],
    overlay_configs: Optional[Dict[str, Any]] = None,
) -> str:
    """Where this slot's live value came from.

    Order matters: the session's own choice is checked first because it is
    applied last, and ``runtime`` is what is left when the live value matches
    neither the manifest nor the stage's default — which is exactly the shape
    of an install Geny does at build time.
    """
    key = f"{order}.{slot}"
    # A changed setting on an unchanged implementation is still the owner's
    # decision — without this the page offered no way back from it.
    if key in overlay_slots or key in (overlay_configs or {}):
        return "session"
    if (order, slot) in RUNTIME_INSTALLED:
        return "runtime"
    stage = declared.get(order) or {}
    if slot in (stage.get("strategies") or {}):
        return "manifest" if stage["strategies"][slot] == value else "runtime"
    if slot in (stage.get("chains") or {}):
        return "manifest" if stage["chains"][slot] == value else "runtime"
    return "default"


def build_harness_view(
    *,
    pipeline: Any,
    manifest: Any = None,
    overlay: Optional[Dict[str, Any]] = None,
    budgets: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The effective harness of one running session, ready to render.

    ``pipeline`` is the session's own live Pipeline — the only thing that
    knows what is actually installed. ``manifest`` and ``overlay`` are needed
    only to label each value's origin; both may be ``None``, in which case
    every value reads as ``default`` or ``runtime`` and the page still
    renders honestly.
    """
    catalogue = slot_catalogue()
    declared = _manifest_slots(manifest) if manifest is not None else {}
    # ``overlay`` is the OWNER's harness file (service.harness.overlay), whose
    # slots sit at the top level. The agent's own env overlay is a different
    # file with a different owner and is deliberately not consulted here.
    overlay_slots = dict((overlay or {}).get("slots") or {})
    overlay_configs = dict((overlay or {}).get("slotConfigs") or {})

    stages: List[Dict[str, Any]] = []
    for description in pipeline.describe():
        order = int(description.order)
        if description.category == "unregistered":
            # A slot in the 21-layout with no stage behind it. Shown so the
            # page is the whole pipeline, not the part that happens to exist.
            stages.append(
                {
                    "order": order,
                    "name": description.name,
                    "category": description.category,
                    "group": STAGE_GROUPS.get(order, "after"),
                    "active": False,
                    "slots": [],
                }
            )
            continue

        slots: List[Dict[str, Any]] = []
        for info in description.strategies or []:
            meta = catalogue.get(f"{order}.{info.slot_name}") or {}
            is_chain = bool(meta.get("isChain"))
            config = dict(info.config or {})
            # A chain reports its members in ``config["items"]``; a plain slot
            # reports one name. Both render as "what is installed here".
            if is_chain:
                items = config.get("items") or []
                value: Any = [
                    (i.get("name") if isinstance(i, dict) else str(i)) for i in items
                ]
            else:
                value = info.current_impl

            options = [
                {
                    "name": impl,
                    "description": (meta.get("implDescriptions") or {}).get(impl, ""),
                    "schema": (meta.get("implSchemas") or {}).get(impl),
                    "installed": False,
                }
                for impl in (info.available_impls or [])
            ]
            # What Geny installs at build time is an INSTANCE, not a name the
            # stage's registry knows — ``persisting_llm_summary``,
            # ``memory_aware``, ``geny_dedupe``. Leave it out and the dropdown
            # cannot render its own current value: it falls back to the first
            # option, so the page says ``llm_summary`` where the persisting
            # one runs, and a reader who touches the control downgrades
            # something they were never shown. Which is the exact lie this
            # whole view exists to prevent, one mile from the end.
            if not is_chain and value and value not in [o["name"] for o in options]:
                options.insert(
                    0,
                    {
                        "name": value,
                        "description": (meta.get("implDescriptions") or {}).get(value, ""),
                        "schema": None,
                        "installed": True,
                    },
                )

            slots.append(
                {
                    "slot": info.slot_name,
                    "value": value,
                    "isChain": is_chain,
                    "options": options,
                    "config": config,
                    "description": meta.get("description", ""),
                    "tier": tier_of(order, info.slot_name),
                    "question": BASIC_SLOTS.get((order, info.slot_name)),
                    "lockedBecause": lock_reason(order, info.slot_name),
                    "installedBy": RUNTIME_INSTALLED.get((order, info.slot_name)),
                    "source": _source_of(
                        order, info.slot_name, value, declared, overlay_slots, overlay_configs
                    ),
                }
            )

        stages.append(
            {
                "order": order,
                "name": description.name,
                "category": description.category,
                "group": STAGE_GROUPS.get(order, "after"),
                "active": bool(description.is_active),
                "slots": slots,
            }
        )

    return {
        "stages": stages,
        "budgets": dict(budgets or {}),
    }
