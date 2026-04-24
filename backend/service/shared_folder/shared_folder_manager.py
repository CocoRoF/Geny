"""
Shared Folder Manager

Manages a shared folder accessible by all Claude CLI sessions.
Provides file listing, reading, writing, and deletion operations
with directory traversal protection and proper encoding handling.

The shared folder path is determined by:
1. Environment variable GENY_SHARED_FOLDER_PATH
2. SharedFolderConfig setting via the Config UI
3. Default: {STORAGE_ROOT}/_shared
"""

import json
import os
import shutil
from datetime import datetime
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

from service.utils.utils import now_kst as _now_tz
from service.utils.platform import DEFAULT_STORAGE_ROOT
from service.utils.file_storage import (
    list_storage_files as _list_storage_files,
    read_storage_file as _read_storage_file,
)

logger = getLogger(__name__)

# Default shared folder name (subdirectory under STORAGE_ROOT)
SHARED_FOLDER_NAME = "_shared"

# Singleton
_shared_folder_manager: Optional["SharedFolderManager"] = None


def _get_default_shared_folder_path() -> str:
    """Get the default shared folder path."""
    env_path = os.environ.get("GENY_SHARED_FOLDER_PATH")
    if env_path:
        return env_path
    return str(Path(DEFAULT_STORAGE_ROOT) / SHARED_FOLDER_NAME)


class SharedFolderManager:
    """
    Manages a shared folder accessible by all sessions.

    Features:
    - Automatic creation on startup
    - File CRUD operations (list, read, write, delete)
    - Directory traversal protection
    - Gitignore-aware file listing (reuses storage_utils)
    - Symlink creation into each session's storage for direct CLI access
    """

    def __init__(self, shared_path: Optional[str] = None):
        """
        Initialize SharedFolderManager.

        Args:
            shared_path: Custom shared folder path. If None, uses default.
        """
        self._shared_path = shared_path or _get_default_shared_folder_path()
        self._ensure_shared_folder()
        logger.info(f"SharedFolderManager initialized: {self._shared_path}")

    @property
    def shared_path(self) -> str:
        """Return the absolute shared folder path."""
        return self._shared_path

    def update_path(self, new_path: str) -> None:
        """
        Update the shared folder path (e.g., from config change).

        Creates the new directory if it doesn't exist.
        Does NOT migrate files from the old path.
        """
        old_path = self._shared_path
        self._shared_path = new_path
        self._ensure_shared_folder()
        logger.info(f"Shared folder path updated: {old_path} → {new_path}")

    # ------------------------------------------------------------------ #
    # Initialization
    # ------------------------------------------------------------------ #

    def _ensure_shared_folder(self) -> None:
        """Create the shared folder and a README if it doesn't exist."""
        try:
            folder = Path(self._shared_path)
            folder.mkdir(parents=True, exist_ok=True)
            self._ensure_readme()
        except Exception as e:
            logger.error(f"Failed to create shared folder {self._shared_path}: {e}")

    def _ensure_readme(self) -> None:
        """Create a README.md in the shared folder if missing."""
        readme_path = Path(self._shared_path) / "README.md"
        if readme_path.exists():
            return
        try:
            readme_path.write_text(
                "# Shared Folder\n\n"
                "This folder is shared across all GenY sessions.\n\n"
                "## Usage\n"
                "- Any file placed here is visible to **every** session.\n"
                "- Use it to exchange data, results, and intermediate outputs.\n"
                "- You can read, write, copy, and delete files freely.\n\n"
                "## Examples\n"
                "```bash\n"
                "# List shared files\n"
                "ls _shared/\n\n"
                "# Copy a file to the shared folder\n"
                "cp my_result.json _shared/\n\n"
                "# Read a shared file\n"
                "cat _shared/data.txt\n"
                "```\n",
                encoding="utf-8",
            )
            logger.info("Created shared folder README.md")
        except Exception as e:
            logger.debug(f"Could not create shared folder README: {e}")

    def _validate_path(self, relative_path: str) -> Optional[Path]:
        """
        Validate and resolve a relative path within the shared folder.

        Prevents directory traversal attacks (e.g., ../../etc/passwd).

        Args:
            relative_path: Relative path within the shared folder.

        Returns:
            Resolved absolute path, or None if the path is invalid.
        """
        try:
            shared_root = Path(self._shared_path).resolve()
            target = (shared_root / relative_path).resolve()
            # Ensure target is within shared folder
            target.relative_to(shared_root)
            return target
        except (ValueError, OSError):
            logger.warning(f"Invalid path (traversal attempt?): {relative_path}")
            return None

    # ------------------------------------------------------------------ #
    # File Listing
    # ------------------------------------------------------------------ #

    def list_files(self, subpath: str = "") -> List[Dict[str, Any]]:
        """
        List files in the shared folder (recursively).

        Uses the same gitignore-aware logic as session storage.

        Args:
            subpath: Subdirectory to list (empty for root).

        Returns:
            List of file info dicts: {name, path, is_dir, size, modified_at}
        """
        return _list_storage_files(
            storage_path=self._shared_path,
            subpath=subpath,
            session_id="shared",
            include_gitignore=True,
        )

    # ------------------------------------------------------------------ #
    # File Reading
    # ------------------------------------------------------------------ #

    def read_file(self, file_path: str, encoding: str = "utf-8") -> Optional[Dict[str, Any]]:
        """
        Read a file from the shared folder.

        Args:
            file_path: Relative path within the shared folder.
            encoding: File encoding.

        Returns:
            Dict with file_path, content, size, encoding; or None if not found.
        """
        return _read_storage_file(
            storage_path=self._shared_path,
            file_path=file_path,
            encoding=encoding,
            session_id="shared",
        )

    # ------------------------------------------------------------------ #
    # File Writing
    # ------------------------------------------------------------------ #

    def write_file(
        self,
        file_path: str,
        content: str,
        encoding: str = "utf-8",
        overwrite: bool = True,
    ) -> Dict[str, Any]:
        """
        Write (create or overwrite) a file in the shared folder.

        Automatically creates parent directories.

        Args:
            file_path: Relative path within the shared folder.
            content: File content string.
            encoding: File encoding.
            overwrite: If False, raises error when file exists.

        Returns:
            Dict with file_path, size, created_at.

        Raises:
            ValueError: If path is invalid or file exists (when overwrite=False).
        """
        target = self._validate_path(file_path)
        if target is None:
            raise ValueError(f"Invalid file path: {file_path}")

        if not overwrite and target.exists():
            raise ValueError(f"File already exists: {file_path}")

        # Ensure parent directories exist
        target.parent.mkdir(parents=True, exist_ok=True)

        target.write_text(content, encoding=encoding)
        logger.info(f"[shared] File written: {file_path} ({len(content)} bytes)")

        return {
            "file_path": file_path,
            "size": len(content.encode(encoding)),
            "created_at": _now_tz().isoformat(),
        }

    def write_binary(
        self,
        file_path: str,
        data: bytes,
        overwrite: bool = True,
    ) -> Dict[str, Any]:
        """
        Write binary data to a file in the shared folder.

        Args:
            file_path: Relative path within the shared folder.
            data: Binary content.
            overwrite: If False, raises error when file exists.

        Returns:
            Dict with file_path, size, created_at.
        """
        target = self._validate_path(file_path)
        if target is None:
            raise ValueError(f"Invalid file path: {file_path}")

        if not overwrite and target.exists():
            raise ValueError(f"File already exists: {file_path}")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        logger.info(f"[shared] Binary file written: {file_path} ({len(data)} bytes)")

        return {
            "file_path": file_path,
            "size": len(data),
            "created_at": _now_tz().isoformat(),
        }

    # ------------------------------------------------------------------ #
    # File / Directory Deletion
    # ------------------------------------------------------------------ #

    def delete_file(self, file_path: str) -> bool:
        """
        Delete a file from the shared folder.

        Args:
            file_path: Relative path within the shared folder.

        Returns:
            True if deleted, False if not found.
        """
        target = self._validate_path(file_path)
        if target is None or not target.exists():
            return False

        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

        logger.info(f"[shared] Deleted: {file_path}")
        return True

    # ------------------------------------------------------------------ #
    # Directory Creation
    # ------------------------------------------------------------------ #

    def create_directory(self, dir_path: str) -> Dict[str, Any]:
        """
        Create a directory in the shared folder.

        Args:
            dir_path: Relative directory path.

        Returns:
            Dict with path and created_at.
        """
        target = self._validate_path(dir_path)
        if target is None:
            raise ValueError(f"Invalid directory path: {dir_path}")

        target.mkdir(parents=True, exist_ok=True)
        logger.info(f"[shared] Directory created: {dir_path}")

        return {
            "path": dir_path,
            "created_at": _now_tz().isoformat(),
        }

    # ------------------------------------------------------------------ #
    # Session Integration: Symlink / Junction
    # ------------------------------------------------------------------ #

    def link_to_session(self, session_storage_path: str, link_name: str = "_shared") -> bool:
        """
        Create a symlink (or junction on Windows) from a session's storage
        to the shared folder so the Claude CLI can access shared files.

        Args:
            session_storage_path: Absolute path to the session's storage dir.
            link_name: Name of the symlink inside the session folder.

        Returns:
            True if link created, False on failure.
        """
        link_path = Path(session_storage_path) / link_name

        # Skip if already linked correctly
        if link_path.exists() or link_path.is_symlink():
            try:
                if link_path.is_symlink() and str(link_path.resolve()) == str(Path(self._shared_path).resolve()):
                    return True  # Already correctly linked
                # Remove stale link
                if link_path.is_symlink():
                    link_path.unlink()
                elif link_path.is_dir():
                    shutil.rmtree(link_path)
                else:
                    link_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to cleanup stale link {link_path}: {e}")
                return False

        try:
            import platform
            if platform.system() == "Windows":
                # On Windows, use directory junction (no admin needed)
                import subprocess
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link_path), str(self._shared_path)],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode != 0:
                    logger.warning(f"Junction creation failed: {result.stderr}")
                    return False
            else:
                # Unix: standard symlink
                link_path.symlink_to(self._shared_path, target_is_directory=True)

            logger.info(f"Shared folder linked: {link_path} → {self._shared_path}")
            return True

        except OSError as e:
            logger.warning(f"Failed to create link {link_path}: {e}")
            return False

    def unlink_from_session(self, session_storage_path: str, link_name: str = "_shared") -> bool:
        """
        Remove the shared folder link from a session's storage.

        Args:
            session_storage_path: Absolute path to the session's storage dir.
            link_name: Name of the symlink inside the session folder.

        Returns:
            True if removed, False on failure.
        """
        link_path = Path(session_storage_path) / link_name

        if not link_path.exists() and not link_path.is_symlink():
            return True  # Nothing to remove

        try:
            if link_path.is_symlink():
                link_path.unlink()
            elif link_path.is_dir():
                # Windows junction appears as a directory
                import platform
                if platform.system() == "Windows":
                    import subprocess
                    subprocess.run(
                        ["cmd", "/c", "rmdir", str(link_path)],
                        capture_output=True, text=True, timeout=10,
                    )
                else:
                    link_path.unlink()
            logger.info(f"Shared folder unlinked: {link_path}")
            return True
        except Exception as e:
            logger.warning(f"Failed to unlink {link_path}: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Info / Stats
    # ------------------------------------------------------------------ #

    def get_info(self) -> Dict[str, Any]:
        """
        Get shared folder information.

        Returns:
            Dict with path, exists, total_files, total_size.
        """
        shared = Path(self._shared_path)
        exists = shared.exists()
        total_files = 0
        total_size = 0

        if exists:
            try:
                for f in shared.rglob("*"):
                    if f.is_file():
                        total_files += 1
                        try:
                            total_size += f.stat().st_size
                        except OSError:
                            pass
            except Exception:
                pass

        return {
            "path": self._shared_path,
            "exists": exists,
            "total_files": total_files,
            "total_size": total_size,
        }


# ------------------------------------------------------------------ #
# Singleton accessor
# ------------------------------------------------------------------ #


def get_shared_folder_manager() -> SharedFolderManager:
    """Get or create the SharedFolderManager singleton."""
    global _shared_folder_manager
    if _shared_folder_manager is None:
        _shared_folder_manager = SharedFolderManager()
    return _shared_folder_manager


def reset_shared_folder_manager() -> None:
    """Reset the singleton (for testing)."""
    global _shared_folder_manager
    _shared_folder_manager = None
