"""
Storage Utilities

Utilities for managing session storage, including gitignore pattern filtering.
"""
import fnmatch
from functools import lru_cache
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


@lru_cache(maxsize=64)
def _compiled_spec(patterns: tuple):
    """Compile-once cache for ignore specs.

    should_ignore_path used to call PathSpec.from_lines PER PATH — ~3 ms a
    compile × every entry of every listing. With scope=all walking the
    whole storage root (observed: 8,005 entries, the memory vault alone is
    ~7,800) one listing burned ~24 s — synchronously, on the event loop —
    and the web UI polls it every few seconds, so the loop was effectively
    permanently seized (storage/changes timed out, every sync engine hung
    in 'syncing'). The pattern list is stable per (defaults + session
    .gitignore), so 64 cached compilations cover every live session."""
    return pathspec.PathSpec.from_lines('gitwildmatch', list(patterns))


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
            spec = _compiled_spec(tuple(ignore_patterns))
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
    include_gitignore: bool = True,
    extra_roots: Optional[List[str]] = None,
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
    # Containment. `subpath` arrives from a query string and the tree can
    # hold symlinks, so the joined path is RESOLVED and then required to sit
    # under an allowed root. Without this, a symlink planted anywhere in a
    # workspace made this endpoint enumerate any directory in the backend
    # container — verified against /etc, 498 entries. The raw-file reader and
    # every write path already checked; the listing did not.
    #
    # `extra_roots` exists for one legitimate escape: the server-created
    # `workspace/cloud` link into the caller's own cloud. It is passed by the
    # caller that already authorised that scope — never inferred here.
    roots = [Path(storage_path).resolve()]
    for extra in extra_roots or []:
        try:
            roots.append(Path(extra).resolve())
        except OSError:
            continue

    target_path = Path(storage_path)
    if subpath:
        target_path = target_path / subpath
    try:
        resolved = target_path.resolve()
    except OSError:
        return []
    if not any(resolved == r or r in resolved.parents for r in roots):
        logger.warning(
            "%slisting refused — %s escapes the allowed roots",
            f"[{session_id}] " if session_id else "", subpath,
        )
        return []
    # NOTE: `target_path` deliberately stays UNRESOLVED for the walk. Every
    # row's `path` is computed as `item.relative_to(storage_path)`, so walking
    # the resolved location would put entries outside the scope root and drop
    # them all — the cloud link would list empty. The resolved form is only
    # ever used for the containment decision above.

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
        # Recursively walk through all entries. Directories are listed too —
        # an explorer UI must show empty folders (a freshly created folder
        # would otherwise be invisible until it gains a file).
        for item in target_path.rglob("*"):
            if item.is_dir():
                try:
                    rel_path = str(item.relative_to(storage_path)).replace("\\", "/")
                    if should_ignore_path(rel_path, ignore_patterns, session_id):
                        continue
                    stat = item.stat()
                    files.append({
                        "name": item.name,
                        "path": rel_path,
                        "is_dir": True,
                        "size": None,
                        "modified_at": datetime.fromtimestamp(stat.st_mtime),
                    })
                except (OSError, ValueError):
                    continue
                continue
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


def within_scope(root: Path, target: Path) -> bool:
    """Is *target* inside this scope, counting its workspace wherever it lives?

    An agent's ``workspace`` is usually a SYMLINK into the user's cloud tree,
    so a resolved path under it is not under the session directory at all.
    A plain ``relative_to`` check therefore rejects every file the agent has
    ever written — which is what "File not found: workspace/…/note.md" was,
    on every file in the explorer, while the listing next to it showed them
    all. Directory traversal still fails both bases.
    """
    for base in (root, (root / "workspace")):
        try:
            target.relative_to(base.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def resolve_in_scope(storage_path: str, file_path: str) -> Optional[Path]:
    """The real path of *file_path* inside this scope, or None if it escapes."""
    root = Path(storage_path)
    target = (root / file_path).resolve()
    return target if within_scope(root, target) else None


def read_storage_file(
    storage_path: str,
    file_path: str,
    encoding: str = "utf-8",
    session_id: str = ""
) -> Optional[Dict]:
    """
    Read storage file content.

    Bytes that are not text in this encoding come back as ``binary: True``
    with the size, rather than as a 404 — "this is a PNG" and "there is no
    such file" are different answers, and a viewer that can show the PNG
    needs to be told which one it got.

    Args:
        storage_path: Path to the storage directory.
        file_path: File path (relative to storage root).
        encoding: File encoding.
        session_id: Session ID for logging (optional).

    Returns:
        File content dictionary or None when there is no such file.
    """
    log_prefix = f"[{session_id}] " if session_id else ""

    target_path = resolve_in_scope(storage_path, file_path)
    if target_path is None:
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
            "encoding": encoding,
            "binary": False,
        }
    except (UnicodeDecodeError, ValueError):
        # A real file that simply is not text. The client fetches the bytes
        # from ``storage-raw`` and renders it as what it is.
        try:
            size = target_path.stat().st_size
        except OSError:
            size = 0
        return {
            "file_path": file_path,
            "content": "",
            "size": size,
            "encoding": encoding,
            "binary": True,
        }
    except Exception as e:
        logger.error(f"{log_prefix}Failed to read file: {e}")
        return None
