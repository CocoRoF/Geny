"""
Platform Utilities

Cross-platform storage-root resolution and OS detection.

NOTE: Historically this module also held Claude-CLI-specific subprocess
helpers (WindowsProcessWrapper, AsyncStreamWriter/Reader,
create_subprocess_cross_platform, get_claude_env_vars). Those were
deleted in cycle 20260424_2 PR-4 along with the ClaudeProcess chain.
What remains is range-generic — used by memory/, shared_folder/,
executor/, etc. PR-5 will relocate it to ``service/utils/platform.py``.
"""
import os
import platform
import tempfile
from logging import getLogger
from pathlib import Path

logger = getLogger(__name__)

# Platform detection
IS_WINDOWS = platform.system() == 'Windows'
IS_MACOS = platform.system() == 'Darwin'
IS_LINUX = platform.system() == 'Linux'


def _get_default_storage_root() -> str:
    """Return a platform-appropriate default storage root path."""
    env_storage = os.environ.get('GENY_AGENT_STORAGE_ROOT')
    if env_storage:
        return env_storage

    if IS_WINDOWS:
        base = os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()
        return str(Path(base) / 'geny_agent_sessions')
    elif IS_MACOS:
        app_support = Path.home() / 'Library' / 'Application Support' / 'geny_agent_sessions'
        try:
            app_support.mkdir(parents=True, exist_ok=True)
            return str(app_support)
        except (PermissionError, OSError):
            return '/tmp/geny_agent_sessions'
    else:
        return '/tmp/geny_agent_sessions'


DEFAULT_STORAGE_ROOT = _get_default_storage_root()
