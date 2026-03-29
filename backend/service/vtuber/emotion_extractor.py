"""
Emotion Extractor

Extracts emotion tags like [joy], [sadness] from LLM output text,
and maps agent execution states to emotions.

Based on Open-LLM-VTuber's extract_emotion() pattern but adapted
for Geny's agent state system.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


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


# Regex pattern to match emotion tags: [emotion_name]
# Matches bracketed lowercase words including underscores
_EMOTION_TAG_PATTERN = re.compile(r"\[([a-zA-Z_]+)\]")


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
    def map_state_to_emotion(agent_state: str) -> str:
        """
        Map an agent execution state to an emotion name.

        Agent states from Geny's LangGraph:
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
    ) -> Tuple[str, int]:
        """
        Combine text-based emotion extraction with agent state mapping.

        Priority: explicit emotion tags > agent state mapping > neutral

        Returns (emotion_name, expression_index).
        """
        # Try text-based extraction first
        if text:
            result = self.extract(text)
            if result.has_emotions:
                return result.primary_emotion, result.primary_index

        # Fall back to state-based mapping
        if agent_state:
            state_emotion = self.map_state_to_emotion(agent_state)
            index = self._emotion_map.get(state_emotion, 0)
            return state_emotion, index

        # Default
        return "neutral", self._emotion_map.get("neutral", 0)
