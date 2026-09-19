"""What the OWNER changed about this agent's harness, and how it survives.

Two different people write settings onto one session. The agent evolves
itself through the ``env`` tool — its prompt, the tools it keeps enabled, the
skills it authored — and that lands in ``env_overlay.json``, rewritten whole
every time the agent saves. The owner configures the agent from the settings
page, and that lands **here**, in a separate file.

Separate on purpose. A single file with two writers means the agent's next
``env(action="save")`` serialises its own view of the world and silently
drops whatever the owner had set, which is a data-loss bug that would show up
as "my setting keeps reverting" and be very hard to explain.

Precedence at session build is manifest → Geny's runtime installs → this.
The owner is applied last because an install is a *default upgrade*, not a
mandate: when someone has explicitly said "compact by truncating", the
persisting summariser Geny installs for everyone is not an improvement, it is
an override of a decision.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from service.harness.catalogue import lock_reason

logger = logging.getLogger(__name__)

__all__ = [
    "HARNESS_FILE",
    "HarnessRejected",
    "apply_overlay",
    "merge_overlay",
    "read_overlay",
    "validate_overlay",
    "write_overlay",
]

HARNESS_FILE = "harness.json"

#: Budget keys the owner may set, and the ``PipelineConfig`` field each one
#: writes. Short on purpose — these three are the ones whose absence changes
#: whether a long turn survives, and every other pipeline knob belongs to the
#: manifest.
_BUDGETS: Dict[str, str] = {
    "maxIterations": "max_iterations",
    "contextWindow": "context_window_budget",
    "costCeiling": "cost_budget_usd",
}


class HarnessRejected(ValueError):
    """The change was refused, with a reason a person can act on."""


def path_for(storage_path: Optional[str]) -> Optional[str]:
    return os.path.join(storage_path, HARNESS_FILE) if storage_path else None


def read_overlay(storage_path: Optional[str]) -> Dict[str, Any]:
    """This session's owner-set harness, or ``{}``."""
    path = path_for(storage_path)
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001 — an unreadable overlay is "nothing set"
        logger.warning("harness overlay unreadable at %s", path, exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


def write_overlay(storage_path: Optional[str], overlay: Dict[str, Any]) -> None:
    """Persist atomically. A half-written overlay is a session that will not
    build, so the rename is the commit."""
    path = path_for(storage_path)
    if not path:
        raise HarnessRejected("이 세션에는 저장 공간이 없습니다")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(overlay, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def merge_overlay(current: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Lay *patch* over *current*, one key at a time.

    A patch is what the page sent, not the whole world: a form that submits
    one changed field must not clear every other setting. ``None`` is how a
    field says "go back to inherited", and it removes the key rather than
    storing a null nobody can distinguish from "not set".
    """
    merged: Dict[str, Any] = {
        "budgets": dict(current.get("budgets") or {}),
        "slots": dict(current.get("slots") or {}),
        "slotConfigs": dict(current.get("slotConfigs") or {}),
    }
    for section in ("budgets", "slots", "slotConfigs"):
        for key, value in (patch.get(section) or {}).items():
            if value is None:
                merged[section].pop(key, None)
            else:
                merged[section][key] = value
    return merged


def _split(key: str) -> Tuple[int, str]:
    order, _, slot = str(key).partition(".")
    return int(order), slot


def validate_overlay(overlay: Dict[str, Any], *, pipeline: Any) -> None:
    """Refuse anything that would not do what it says.

    Checked against the LIVE pipeline rather than a table, so a slot that
    exists only on some builds, or an implementation name that was renamed in
    the library, is refused here instead of failing on the next turn.
    """
    for key, value in (overlay.get("budgets") or {}).items():
        if key not in _BUDGETS:
            raise HarnessRejected(f"알 수 없는 예산 항목입니다: {key}")
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise HarnessRejected(f"{key} 은 숫자여야 합니다") from None
        if number < 0:
            raise HarnessRejected(f"{key} 은 0 이상이어야 합니다")

    stages = {int(getattr(s, "order", 0)): s for s in getattr(pipeline, "stages", [])}
    for key, impl in (overlay.get("slots") or {}).items():
        try:
            order, slot = _split(key)
        except ValueError:
            raise HarnessRejected(f"슬롯 이름 형식이 아닙니다: {key}") from None

        reason = lock_reason(order, slot)
        if reason:
            raise HarnessRejected(
                f"{key} 는 바꿀 수 없는 항목입니다 ({reason}) — 이 값은 Geny 가 무엇인지를 "
                "정하는 부분이라 설정으로 열려 있지 않습니다"
            )

        stage = stages.get(order)
        if stage is None:
            raise HarnessRejected(f"{order} 단계가 이 파이프라인에 없습니다")

        available = _available(stage, slot)
        if available is None:
            raise HarnessRejected(f"{order} 단계에 {slot} 슬롯이 없습니다")
        names = [impl] if isinstance(impl, str) else list(impl or [])
        for name in names:
            if name not in available:
                raise HarnessRejected(
                    f"{key} 에 쓸 수 없는 값입니다: {name} — 가능한 값: {', '.join(available)}"
                )

    for key in (overlay.get("slotConfigs") or {}):
        try:
            order, slot = _split(key)
        except ValueError:
            raise HarnessRejected(f"슬롯 이름 형식이 아닙니다: {key}") from None
        if lock_reason(order, slot):
            raise HarnessRejected(f"{key} 는 바꿀 수 없는 항목입니다")


def _available(stage: Any, slot: str) -> Optional[List[str]]:
    """The implementations *slot* accepts on this stage, or ``None``."""
    description = stage.describe()
    for info in description.strategies or []:
        if info.slot_name == slot:
            return list(info.available_impls or [])
    return None


def _is_chain(stage: Any, slot: str) -> bool:
    for info in stage.describe().strategies or []:
        if info.slot_name == slot:
            return isinstance((info.config or {}).get("items"), list)
    return False


def apply_overlay(pipeline: Any, overlay: Dict[str, Any]) -> List[str]:
    """Apply the owner's choices to a built pipeline. Returns what was applied.

    Called last in the build, after Geny's runtime installs, so an explicit
    choice wins over a default upgrade. Each item is applied independently:
    one stale key (a slot removed from the library between releases) must not
    cost the session every other setting the owner made.
    """
    applied: List[str] = []

    config = getattr(pipeline, "_config", None)
    if config is not None:
        for key, field in _BUDGETS.items():
            if key not in (overlay.get("budgets") or {}):
                continue
            value = overlay["budgets"][key]
            try:
                number = float(value) if value is not None else 0.0
            except (TypeError, ValueError):
                continue
            if field == "cost_budget_usd":
                setattr(config, field, number if number > 0 else None)
            elif number > 0:
                setattr(config, field, int(number))
            else:
                continue
            applied.append(f"{key}={getattr(config, field)}")

    stages = {int(getattr(s, "order", 0)): s for s in getattr(pipeline, "stages", [])}
    for key, impl in (overlay.get("slots") or {}).items():
        try:
            order, slot = _split(key)
        except ValueError:
            continue
        stage = stages.get(order)
        if stage is None or lock_reason(order, slot):
            continue
        slot_config = (overlay.get("slotConfigs") or {}).get(key) or None
        try:
            if _is_chain(stage, slot):
                stage.clear_chain(slot)
                for name in (impl if isinstance(impl, list) else [impl]):
                    stage.add_to_chain(slot, name, slot_config)
            else:
                stage.set_strategy(slot, impl, slot_config)
        except Exception as exc:  # noqa: BLE001 — one stale key, not the session
            logger.warning("harness overlay: could not apply %s=%s: %s", key, impl, exc)
            continue
        applied.append(f"{key}={impl}")

    # A config change with no accompanying strategy change still has to land.
    for key, slot_config in (overlay.get("slotConfigs") or {}).items():
        if key in (overlay.get("slots") or {}):
            continue
        try:
            order, slot = _split(key)
        except ValueError:
            continue
        stage = stages.get(order)
        if stage is None or lock_reason(order, slot):
            continue
        current = None
        for info in stage.describe().strategies or []:
            if info.slot_name == slot:
                current = info.current_impl
        if not current or current == "none":
            continue
        try:
            stage.set_strategy(slot, current, dict(slot_config or {}))
        except Exception as exc:  # noqa: BLE001
            logger.warning("harness overlay: could not configure %s: %s", key, exc)
            continue
        applied.append(f"{key}(config)")

    if applied:
        logger.info("harness overlay applied: %s", ", ".join(applied))
    return applied
