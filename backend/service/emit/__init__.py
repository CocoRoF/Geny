"""Geny-side s14 emitter extensions.

Executor owns the default emitter roster (``text`` / ``callback`` /
``vtuber`` / ``tts``). This package contributes CreatureState-aware
emitters — currently :class:`AffectTagEmitter` — plus the helper that
installs them onto a manifest-built pipeline's emit chain.
"""

from __future__ import annotations

from service.emit.affect_tag_emitter import (
    AFFECT_TAGS,
    AFFECT_TAG_RE,
    MOOD_ALPHA,
    AffectTagEmitter,
)
from service.emit.chain_install import install_affect_tag_emitter

__all__ = [
    "AFFECT_TAGS",
    "AFFECT_TAG_RE",
    "MOOD_ALPHA",
    "AffectTagEmitter",
    "install_affect_tag_emitter",
]
