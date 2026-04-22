"""Voice profile discovery — scans ``settings.voices_dir`` and surfaces
each subdirectory as a ``VoiceProfile``.

Compatible with the existing GPT-SoVITS profile layout used by Geny:

    <voices_dir>/<profile_id>/
        profile.json
        ref_neutral.wav
        ref_joy.wav
        ...

Only ``profile.json`` keys we actually consume are touched; unknown keys
are passed through unchanged so the file can stay shared with GPT-SoVITS.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from server.schemas import VoiceProfile, VoiceRefAudio

logger = logging.getLogger(__name__)


def _safe_load_profile_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except FileNotFoundError:
        return {}
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to parse profile.json at %s", path)
        return {}


def _scan_one(profile_dir: str, profile_id: str) -> Optional[VoiceProfile]:
    if not os.path.isdir(profile_dir):
        return None

    data = _safe_load_profile_json(os.path.join(profile_dir, "profile.json"))
    refs: list[VoiceRefAudio] = []

    emotion_refs = data.get("emotion_refs") if isinstance(data, dict) else None
    if isinstance(emotion_refs, dict):
        for emotion, meta in emotion_refs.items():
            if not isinstance(meta, dict):
                continue
            file_name = meta.get("file") or f"ref_{emotion}.wav"
            full = os.path.join(profile_dir, file_name)
            if not os.path.isfile(full):
                continue
            refs.append(
                VoiceRefAudio(
                    emotion=emotion,
                    file=full,
                    prompt_text=meta.get("prompt_text"),
                    prompt_lang=meta.get("prompt_lang"),
                )
            )

    if not refs:
        # Fall back to filesystem scan for any ref_<emotion>.wav files.
        for entry in sorted(os.listdir(profile_dir)):
            if entry.startswith("ref_") and entry.endswith(".wav"):
                emotion = entry[len("ref_"):-len(".wav")]
                refs.append(
                    VoiceRefAudio(
                        emotion=emotion,
                        file=os.path.join(profile_dir, entry),
                    )
                )

    return VoiceProfile(
        id=profile_id,
        name=str(data.get("display_name") or data.get("name") or profile_id),
        language=data.get("language") if isinstance(data, dict) else None,
        is_template=bool(data.get("is_template", False)) if isinstance(data, dict) else False,
        ref_audios=refs,
    )


def list_profiles(voices_dir: str) -> list[VoiceProfile]:
    if not os.path.isdir(voices_dir):
        logger.warning("voices_dir does not exist: %s", voices_dir)
        return []
    out: list[VoiceProfile] = []
    for entry in sorted(os.listdir(voices_dir)):
        full = os.path.join(voices_dir, entry)
        profile = _scan_one(full, entry)
        if profile is not None:
            out.append(profile)
    return out


def get_profile(voices_dir: str, profile_id: str) -> Optional[VoiceProfile]:
    return _scan_one(os.path.join(voices_dir, profile_id), profile_id)


def resolve_ref_audio(voices_dir: str, profile_id: str, emotion: str) -> Optional[VoiceRefAudio]:
    """Pick a reference audio for ``emotion`` with neutral fallback."""
    profile = get_profile(voices_dir, profile_id)
    if profile is None or not profile.ref_audios:
        return None
    by_emotion = {r.emotion: r for r in profile.ref_audios}
    if emotion in by_emotion:
        return by_emotion[emotion]
    if "neutral" in by_emotion:
        return by_emotion["neutral"]
    return profile.ref_audios[0]
