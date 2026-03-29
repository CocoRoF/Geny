"""
VTuber Service Package

Provides Live2D model management, emotion extraction, and avatar state management
for VTuber character rendering in the Geny frontend.
"""

from .live2d_model_manager import Live2dModelManager, Live2dModelInfo
from .emotion_extractor import EmotionExtractor, EmotionResult
from .avatar_state_manager import AvatarStateManager, AvatarState

__all__ = [
    "Live2dModelManager",
    "Live2dModelInfo",
    "EmotionExtractor",
    "EmotionResult",
    "AvatarStateManager",
    "AvatarState",
]
