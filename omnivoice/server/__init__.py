"""Geny's FastAPI server wrapping the vendored OmniVoice inference engine."""

from server.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
