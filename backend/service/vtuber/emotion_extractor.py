"""
Emotion Extractor

Extracts emotion tags like [joy], [sadness] from LLM output text,
maps agent execution states to emotions, and — when a
:class:`~service.state.schema.mood.MoodVector` is provided — prefers
the creature's accumulated mood over keyword guessing.

Based on Open-LLM-VTuber's extract_emotion() pattern but adapted
for Geny's agent state system.
"""

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from service.state.schema.mood import MoodVector

# ``MoodVector.dominant`` is called with this threshold so the facial
# signal matches the prompt-side :class:`MoodBlock` cutoff exactly —
# otherwise a mood that just barely shows up in the prompt could fail
# to move the face (or vice versa), which is surprising.
_MOOD_BASIC_THRESHOLD: float = 0.15

# Mapping from ``MoodVector`` basic keys to facial-emotion names used
# in Live2D ``emotionMap``. ``excitement`` maps to ``surprise`` because
# that's the closest universally-present expression slot in the models
# Geny ships (``joy/sadness/anger/fear/surprise/neutral``). ``calm``
# is intentionally absent — a calm dominant signals "no specific mood
# pressure", so we fall through to the next source (agent state /
# explicit tags) instead of overriding it with a neutral face.
_MOOD_TO_EMOTION: Dict[str, str] = {
    "joy": "joy",
    "sadness": "sadness",
    "anger": "anger",
    "fear": "fear",
    "excitement": "surprise",
}


@dataclass
class EmotionResult:
    """Result of emotion extraction from text."""
    emotions: List[str] = field(default_factory=list)
    expression_indices: List[int] = field(default_factory=list)
    cleaned_text: str = ""
    primary_emotion: str = "neutral"
    primary_index: int = 0

    @property
    def has_emotions(self) -> bool:
        return len(self.emotions) > 0


# Regex pattern to match emotion tags: [emotion_name] or [emotion_name:strength].
# Matches bracketed letter-and-underscore identifiers with an optional
# *numeric* ``:strength`` suffix. Strict numeric payload so
# legitimate text like ``[note: todo]`` is not stripped here. Allows
# whitespace inside the bracket (``[joy : 0.7]``) for lightly malformed
# LLM output. The VTuber layer ignores the value — it only uses the
# identifier — so we don't capture strength.
_EMOTION_TAG_PATTERN = re.compile(
    r"\[\s*([a-zA-Z_]+)(?:\s*:\s*-?\d+(?:\.\d+)?)?\s*\]"
)


class EmotionExtractor:
    """
    Extracts emotion information from text using bracket-tag syntax.

    Usage:
        extractor = EmotionExtractor({"joy": 3, "neutral": 0, "anger": 2})
        result = extractor.extract("[joy] Hello! [surprise] Wow!")
        # result.emotions == ["joy", "surprise"]
        # result.cleaned_text == "Hello! Wow!"
        # result.primary_emotion == "joy"
    """

    def __init__(self, emotion_map: Dict[str, int]):
        self._emotion_map = emotion_map
        # Build set of valid emotion names for fast lookup
        self._valid_emotions = set(emotion_map.keys())

    @property
    def emotion_map(self) -> Dict[str, int]:
        return self._emotion_map

    def extract(self, text: str) -> EmotionResult:
        """
        Extract all emotion tags from text.

        Returns an EmotionResult with:
        - emotions: ordered list of extracted emotion names
        - expression_indices: corresponding expression index for each emotion
        - cleaned_text: text with all emotion tags removed
        - primary_emotion: first valid emotion found (or "neutral")
        - primary_index: expression index for primary emotion
        """
        if not text:
            return EmotionResult(
                cleaned_text="",
                primary_emotion="neutral",
                primary_index=self._emotion_map.get("neutral", 0),
            )

        emotions: List[str] = []
        indices: List[int] = []

        # Find all bracket-tagged emotions
        for match in _EMOTION_TAG_PATTERN.finditer(text):
            tag = match.group(1).lower()
            if tag in self._valid_emotions:
                emotions.append(tag)
                indices.append(self._emotion_map[tag])

        # Remove all bracket tags from text (even invalid ones)
        cleaned = _EMOTION_TAG_PATTERN.sub("", text).strip()
        # Collapse multiple spaces
        cleaned = re.sub(r"\s{2,}", " ", cleaned)

        primary_emotion = emotions[0] if emotions else "neutral"
        primary_index = indices[0] if indices else self._emotion_map.get("neutral", 0)

        return EmotionResult(
            emotions=emotions,
            expression_indices=indices,
            cleaned_text=cleaned,
            primary_emotion=primary_emotion,
            primary_index=primary_index,
        )

    def remove_tags(self, text: str) -> str:
        """Remove all emotion tags from text, returning cleaned text only."""
        return re.sub(r"\s{2,}", " ", _EMOTION_TAG_PATTERN.sub("", text)).strip()

    @staticmethod
    def map_mood_to_emotion(
        mood: Optional["MoodVector"],
        *,
        threshold: float = _MOOD_BASIC_THRESHOLD,
    ) -> Optional[str]:
        """Return a facial-emotion name for ``mood``, or ``None`` to defer.

        - ``None`` input → ``None`` (defer to agent-state/neutral).
        - Dominant basic emotion above ``threshold`` → mapped name.
        - Dominant falls back to ``"calm"`` → ``None`` so the caller can
          still honour an agent-state signal like ``executing`` (which
          is more actionable for the face than a generic neutral mood).
        """
        if mood is None:
            return None
        try:
            dominant = mood.dominant(threshold=threshold)
        except Exception:
            return None
        return _MOOD_TO_EMOTION.get(dominant)

    @staticmethod
    def map_state_to_emotion(agent_state: str) -> str:
        """
        Map an agent execution state to an emotion name.

        Agent execution states exposed by geny-executor:
        - thinking / planning → neutral
        - executing / tool_calling → surprise (actively working)
        - success / completed → joy
        - error / failed → fear
        - waiting / idle → neutral
        """
        state_map = {
            # Active states
            "thinking": "neutral",
            "planning": "neutral",
            "executing": "surprise",
            "tool_calling": "surprise",
            "running": "surprise",
            # Result states
            "success": "joy",
            "completed": "joy",
            "done": "joy",
            # Error states
            "error": "fear",
            "failed": "fear",
            "timeout": "sadness",
            # Idle states
            "idle": "neutral",
            "waiting": "neutral",
            "ready": "neutral",
        }
        return state_map.get(agent_state.lower(), "neutral")

    def resolve_emotion(
        self,
        text: Optional[str],
        agent_state: Optional[str],
        *,
        mood: Optional["MoodVector"] = None,
    ) -> Tuple[str, int]:
        """
        Combine text-based emotion extraction, creature mood, and agent
        state mapping into a single ``(emotion_name, expression_index)``.

        Priority:
          1. Explicit ``[emotion]`` tags in ``text`` (per-utterance cue
             from the LLM — strongest, most recent signal).
          2. ``mood.dominant()`` above threshold (creature's accumulated
             emotional state from ``CreatureState``).
          3. ``agent_state`` mapping (operational signal — executing,
             error, etc.).
          4. ``"neutral"``.

        ``mood`` defaults to ``None`` so callers without a hydrated
        ``CreatureState`` keep the classic text→state→neutral behaviour.
        """
        # 1. Explicit text tags win — the LLM just said what it felt.
        if text:
            result = self.extract(text)
            if result.has_emotions:
                return result.primary_emotion, result.primary_index

        # 2. Hydrated mood — use the creature's current dominant emotion
        # as long as a basic key clears the threshold. Calm / unset mood
        # returns ``None`` and falls through.
        mood_emotion = self.map_mood_to_emotion(mood)
        if mood_emotion is not None:
            index = self._emotion_map.get(mood_emotion, 0)
            return mood_emotion, index

        # 3. Operational state — useful fallback when mood is calm but
        # something is actively happening (executing → surprise, etc.).
        if agent_state:
            state_emotion = self.map_state_to_emotion(agent_state)
            index = self._emotion_map.get(state_emotion, 0)
            return state_emotion, index

        # 4. Default
        return "neutral", self._emotion_map.get("neutral", 0)
