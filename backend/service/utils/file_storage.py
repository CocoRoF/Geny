"""
Storage Utilities

Utilities for managing session storage, including gitignore pattern filtering.
"""
import fnmatch
from logging import getLogger
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

# Optional pathspec for gitignore parsing (fallback to fnmatch if not available)
try:
    import pathspec
    PATHSPEC_AVAILABLE = True
except ImportError:
    pathspec = None
    PATHSPEC_AVAILABLE = False

logger = getLogger(__name__)

# Default ignore patterns for storage file listing
# These patterns are always applied regardless of .gitignore
DEFAULT_IGNORE_PATTERNS = [
    # Package managers & dependencies
    'node_modules/',
    'node_modules/**',
    '.npm/',
    '.yarn/',
    '.pnpm-store/',
    'bower_components/',

    # Python virtual environments
    '.venv/',
    '.venv/**',
    'venv/',
    'venv/**',
    '.env/',
    'env/',
    '__pycache__/',
    '__pycache__/**',
    '*.pyc',
    '*.pyo',
    '*.pyd',
    '.Python',
    'pip-log.txt',
    'pip-delete-this-directory.txt',
    '.tox/',
    '.nox/',
    '.pytest_cache/',
    '.mypy_cache/',
    '.ruff_cache/',

    # Build outputs
    'build/',
    'dist/',
    'out/',
    'target/',
    '*.egg-info/',
    '.eggs/',

    # IDE & editors
    '.idea/',
    '.vscode/',
    '*.swp',
    '*.swo',
    '*~',
    '.project',
    '.classpath',
    '.settings/',

    # Version control
    '.git/',
    '.git/**',
    '.svn/',
    '.hg/',

    # OS files
    '.DS_Store',
    'Thumbs.db',
    'desktop.ini',

    # Logs
    '*.log',
    'logs/',
    'npm-debug.log*',
    'yarn-debug.log*',
    'yarn-error.log*',

    # Coverage & testing
    'coverage/',
    '.coverage',
    'htmlcov/',
    '.nyc_output/',

    # Next.js / React
    '.next/',
    '.nuxt/',

    # Misc
    '.cache/',
    'tmp/',
    'temp/',
    '.temp/',
    '.tmp/',
]


def load_gitignore_patterns(storage_path: str, session_id: str = "") -> List[str]:
    """
    Load .gitignore patterns from the storage directory.

    Args:
        storage_path: Path to the storage directory.
        session_id: Session ID for logging (optional).

    Returns:
        List of gitignore patterns from the session's .gitignore file.
    """
    gitignore_path = Path(storage_path) / ".gitignore"
    patterns = []

    if gitignore_path.exists():
        try:
            content = gitignore_path.read_text(encoding='utf-8')
            for line in content.splitlines():
                line = line.strip()
                # Skip empty lines and comments
                if line and not line.startswith('#'):
                    patterns.append(line)
            log_prefix = f"[{session_id}] " if session_id else ""
            logger.debug(f"{log_prefix}Loaded {len(patterns)} patterns from .gitignore")
        except Exception as e:
            log_prefix = f"[{session_id}] " if session_id else ""
            logger.warning(f"{log_prefix}Failed to load .gitignore: {e}")

    return patterns


def should_ignore_path(rel_path: str, ignore_patterns: List[str], session_id: str = "") -> bool:
    """
    Check if a path should be ignored based on ignore patterns.

    Args:
        rel_path: Relative path to check (using forward slashes).
        ignore_patterns: List of gitignore-style patterns.
        session_id: Session ID for logging (optional).

    Returns:
        True if the path should be ignored.
    """
    if PATHSPEC_AVAILABLE:
        # Use pathspec for accurate gitignore matching
        try:
            spec = pathspec.PathSpec.from_lines('gitwildmatch', ignore_patterns)
            return spec.match_file(rel_path)
        except Exception as e:
            log_prefix = f"[{session_id}] " if session_id else ""
            logger.debug(f"{log_prefix}pathspec error, falling back to fnmatch: {e}")

    # Fallback to fnmatch-based matching
    for pattern in ignore_patterns:
        # Handle directory patterns (ending with /)
        if pattern.endswith('/'):
            dir_pattern = pattern.rstrip('/')
            # Check if any part of the path starts with this directory
            path_parts = rel_path.split('/')
            for i, part in enumerate(path_parts):
                partial_path = '/'.join(path_parts[:i+1])
                if fnmatch.fnmatch(part, dir_pattern) or fnmatch.fnmatch(partial_path, dir_pattern):
                    return True
        # Handle ** patterns (match any directory depth)
        elif '**' in pattern:
            # Convert ** to regex-like matching
            regex_pattern = pattern.replace('**', '*')
            if fnmatch.fnmatch(rel_path, regex_pattern):
                return True
        else:
            # Simple pattern matching
            if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(rel_path.split('/')[-1], pattern):
                return True

    return False


def list_storage_files(
    storage_path: str,
    subpath: str = "",
    session_id: str = "",
    include_gitignore: bool = True
) -> List[Dict]:
    """
    List all files in the storage directory recursively.

    Files matching .gitignore patterns and default ignore patterns
    (node_modules, .venv, etc.) are automatically excluded.

    Args:
        storage_path: Path to the storage directory.
        subpath: Subdirectory path (empty string for root).
        session_id: Session ID for logging (optional).
        include_gitignore: Whether to load and apply .gitignore patterns.

    Returns:
        List of file information dictionaries.
    """
    target_path = Path(storage_path)
    if subpath:
        target_path = target_path / subpath

    if not target_path.exists():
        return []

    # Combine default patterns with session's .gitignore
    ignore_patterns = list(DEFAULT_IGNORE_PATTERNS)
    if include_gitignore:
        gitignore_patterns = load_gitignore_patterns(storage_path, session_id)
        ignore_patterns.extend(gitignore_patterns)

    log_prefix = f"[{session_id}] " if session_id else ""
    logger.debug(f"{log_prefix}Using {len(ignore_patterns)} ignore patterns")

    files = []
    try:
        # Recursively walk through all files
        for item in target_path.rglob("*"):
            if item.is_file():
                try:
                    rel_path = str(item.relative_to(storage_path))
                    # Normalize path separators
                    rel_path = rel_path.replace("\\", "/")

                    # Check if path should be ignored
                    if should_ignore_path(rel_path, ignore_patterns, session_id):
                        logger.debug(f"{log_prefix}Ignoring: {rel_path}")
                        continue

                    stat = item.stat()
                    files.append({
                        "name": item.name,
                        "path": rel_path,
                        "is_dir": False,
                        "size": stat.st_size,
                        "modified_at": datetime.fromtimestamp(stat.st_mtime)
                    })
                except (OSError, ValueError) as e:
                    logger.debug(f"{log_prefix}Skipping file {item}: {e}")
    except Exception as e:
        logger.error(f"{log_prefix}Failed to list files: {e}")

    return files


def read_storage_file(
    storage_path: str,
    file_path: str,
    encoding: str = "utf-8",
    session_id: str = ""
) -> Optional[Dict]:
    """
    Read storage file content.

    Args:
        storage_path: Path to the storage directory.
        file_path: File path (relative to storage root).
        encoding: File encoding.
        session_id: Session ID for logging (optional).

    Returns:
        File content dictionary or None.
    """
    target_path = Path(storage_path) / file_path
    log_prefix = f"[{session_id}] " if session_id else ""

    # Path validation (prevent directory traversal)
    try:
        target_path.resolve().relative_to(Path(storage_path).resolve())
    except ValueError:
        logger.warning(f"{log_prefix}Invalid file path: {file_path}")
        return None

    if not target_path.exists() or not target_path.is_file():
        return None

    try:
        content = target_path.read_text(encoding=encoding)
        return {
            "file_path": file_path,
            "content": content,
            "size": len(content),
            "encoding": encoding
        }
    except Exception as e:
        logger.error(f"{log_prefix}Failed to read file: {e}")
        return None
