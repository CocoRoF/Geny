"""Install :class:`AffectTagEmitter` onto a prebuilt pipeline's s14 chain.

The executor composes the emit chain from manifest declarations; its
registry only knows the four default emitters (text/callback/vtuber/tts).
Rather than forking that registry or extending the manifest schema,
Geny installs the affect emitter into the already-built pipeline — a
tiny, explicit boundary that keeps the executor oblivious to
CreatureState concerns.

Placement: **prepended** so its ``final_text`` rewrite (tag strip) is
visible to any later emitter (vtuber / tts / text) in the same chain.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from service.emit.affect_tag_emitter import (
    DEFAULT_MAX_TAG_MUTATIONS_PER_TURN,
    AffectTagEmitter,
)

logger = logging.getLogger(__name__)

EMIT_STAGE_ORDER: int = 14


def install_affect_tag_emitter(
    pipeline: Any,
    *,
    max_tags_per_turn: int = DEFAULT_MAX_TAG_MUTATIONS_PER_TURN,
) -> Optional[AffectTagEmitter]:
    """Prepend an :class:`AffectTagEmitter` onto the pipeline's s14 chain.

    Returns the emitter instance on success, or ``None`` if the pipeline
    has no emit stage (e.g. a custom manifest dropped it) or the chain
    already contains one — callers treat ``None`` as "nothing to do".

    The helper is idempotent: calling it twice on the same pipeline
    adds at most one emitter.
    """
    stage = _get_emit_stage(pipeline)
    if stage is None:
        logger.debug(
            "install_affect_tag_emitter: pipeline has no stage at order %d; skipping",
            EMIT_STAGE_ORDER,
        )
        return None

    chain = getattr(stage, "emitters", None)
    if chain is None or not hasattr(chain, "items"):
        logger.debug(
            "install_affect_tag_emitter: stage %r has no emitters chain; skipping",
            getattr(stage, "name", type(stage).__name__),
        )
        return None

    for existing in chain.items:
        if getattr(existing, "name", None) == "affect_tag":
            logger.debug(
                "install_affect_tag_emitter: chain already has an affect_tag emitter; skipping"
            )
            return None

    emitter = AffectTagEmitter(max_tags_per_turn=max_tags_per_turn)
    chain.items.insert(0, emitter)
    logger.info(
        "install_affect_tag_emitter: prepended (chain now: %s)",
        [getattr(e, "name", type(e).__name__) for e in chain.items],
    )
    return emitter


def _get_emit_stage(pipeline: Any) -> Any:
    getter = getattr(pipeline, "get_stage", None)
    if callable(getter):
        return getter(EMIT_STAGE_ORDER)
    stages = getattr(pipeline, "_stages", None)
    if isinstance(stages, dict):
        return stages.get(EMIT_STAGE_ORDER)
    return None
