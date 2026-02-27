"""
Platform Utilities

Cross-platform utilities for process and storage management.
"""
import asyncio
import os
import platform
import subprocess as sp
import tempfile
from logging import getLogger
from pathlib import Path
from typing import Optional, Dict, List, Tuple

from service.claude_manager.constants import STDIO_BUFFER_LIMIT

logger = getLogger(__name__)

# Platform detection
IS_WINDOWS = platform.system() == 'Windows'
IS_MACOS = platform.system() == 'Darwin'
IS_LINUX = platform.system() == 'Linux'


def _get_default_storage_root() -> str:
    """Get platform-appropriate default storage root."""
    env_storage = os.environ.get('GENY_AGENT_STORAGE_ROOT')
    if env_storage:
        return env_storage

    # Use platform-appropriate temp directory
    if IS_WINDOWS:
        # On Windows, use LOCALAPPDATA or TEMP
        base = os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()
        return str(Path(base) / 'geny_agent_sessions')
    elif IS_MACOS:
        # On macOS, use ~/Library/Application Support or /tmp
        app_support = Path.home() / 'Library' / 'Application Support' / 'geny_agent_sessions'
        try:
            app_support.mkdir(parents=True, exist_ok=True)
            return str(app_support)
        except (PermissionError, OSError):
            return '/tmp/geny_agent_sessions'
    else:
        # On Linux and other Unix-like systems, use /tmp
        return '/tmp/geny_agent_sessions'


DEFAULT_STORAGE_ROOT = _get_default_storage_root()


def get_claude_env_vars() -> Dict[str, str]:
    """
    Collect environment variables required for Claude Code execution.

    Returns:
        Dictionary of environment variables to pass to Claude Code.
    """
    from service.claude_manager.constants import CLAUDE_ENV_KEYS

    env_vars = {}
    for key in CLAUDE_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            env_vars[key] = value
    return env_vars


class WindowsProcessWrapper:
    """
    Wrapper class that provides asyncio.subprocess.Process-like interface
    for subprocess.Popen on Windows. This avoids the NotImplementedError
    that occurs when uvicorn uses SelectorEventLoop instead of ProactorEventLoop.
    """

    def __init__(self, popen: sp.Popen):
        self._popen = popen
        # Wrap stdin/stdout/stderr with async-compatible wrappers
        self._stdin_wrapper = AsyncStreamWriter(popen.stdin) if popen.stdin else None
        self._stdout_wrapper = AsyncStreamReader(popen.stdout) if popen.stdout else None
        self._stderr_wrapper = AsyncStreamReader(popen.stderr) if popen.stderr else None

    @property
    def pid(self) -> int:
        return self._popen.pid

    @property
    def returncode(self) -> Optional[int]:
        return self._popen.returncode

    @property
    def stdin(self):
        """Async-compatible stdin wrapper."""
        return self._stdin_wrapper

    @property
    def stdout(self):
        """Async-compatible stdout wrapper."""
        return self._stdout_wrapper

    @property
    def stderr(self):
        """Async-compatible stderr wrapper."""
        return self._stderr_wrapper

    async def communicate(self, input: Optional[bytes] = None) -> Tuple[bytes, bytes]:
        """Async wrapper around Popen.communicate()"""
        def _communicate():
            return self._popen.communicate(input=input)

        return await asyncio.to_thread(_communicate)

    async def wait(self) -> int:
        """Async wrapper around Popen.wait()"""
        def _wait():
            return self._popen.wait()

        return await asyncio.to_thread(_wait)

    def terminate(self):
        """Terminate the process"""
        self._popen.terminate()

    def kill(self):
        """Kill the process"""
        self._popen.kill()

    def send_signal(self, sig):
        """Send a signal to the process"""
        self._popen.send_signal(sig)


class AsyncStreamWriter:
    """Async wrapper for synchronous file-like write objects (e.g., Popen.stdin)."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, data: bytes):
        """Write data to stream (synchronous, but matches asyncio interface)."""
        return self._stream.write(data)

    async def drain(self):
        """Flush the stream (async-compatible)."""
        await asyncio.to_thread(self._stream.flush)

    def close(self):
        """Close the stream."""
        self._stream.close()

    async def wait_closed(self):
        """Wait for stream to close (no-op for sync streams)."""
        pass


class AsyncStreamReader:
    """Async wrapper for synchronous file-like read objects (e.g., Popen.stdout)."""

    def __init__(self, stream):
        self._stream = stream

    async def readline(self) -> bytes:
        """Read a line asynchronously."""
        def _readline():
            return self._stream.readline()
        return await asyncio.to_thread(_readline)

    async def read(self, n: int = -1) -> bytes:
        """Read n bytes asynchronously."""
        def _read():
            return self._stream.read(n)
        return await asyncio.to_thread(_read)

    def close(self):
        """Close the stream."""
        self._stream.close()


async def create_subprocess_cross_platform(
    cmd: List[str],
    stdin: Optional[int] = None,
    stdout: Optional[int] = None,
    stderr: Optional[int] = None,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
    limit: int = STDIO_BUFFER_LIMIT
):
    """
    Create a subprocess in a cross-platform compatible way.

    IMPORTANT: On Windows, caller must provide direct executable commands
    (e.g., node.exe with arguments), NOT batch files (.cmd/.bat).
    This function does NOT wrap commands with cmd.exe or PowerShell.

    Args:
        cmd: Command and arguments as a list. First element must be a direct executable.
        stdin: stdin handling (e.g., asyncio.subprocess.PIPE or None)
        stdout: stdout handling
        stderr: stderr handling
        env: Environment variables dictionary
        cwd: Working directory path
        limit: Buffer limit for stdio pipes (only used on Unix)

    Returns:
        The created subprocess (WindowsProcessWrapper on Windows, asyncio.subprocess.Process on Unix).

    Raises:
        OSError: If the subprocess cannot be created.
    """
    if not cmd:
        raise ValueError("Command list cannot be empty")

    logger.debug(f"Platform: {platform.system()}, Command: {cmd[:4]}...")

    try:
        if IS_WINDOWS:
            # Windows: Use subprocess.Popen directly with node.exe
            # No cmd.exe wrapper - direct execution only

            # Map asyncio.subprocess constants to subprocess constants
            stdin_arg = sp.PIPE if stdin == asyncio.subprocess.PIPE else stdin
            stdout_arg = sp.PIPE if stdout == asyncio.subprocess.PIPE else stdout
            stderr_arg = sp.PIPE if stderr == asyncio.subprocess.PIPE else stderr

            # CREATE_NO_WINDOW (0x08000000) prevents console window popup
            creationflags = sp.CREATE_NO_WINDOW

            # STARTUPINFO to hide window
            startupinfo = sp.STARTUPINFO()
            startupinfo.dwFlags |= sp.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = sp.SW_HIDE

            # Create process synchronously (Popen doesn't block)
            popen = sp.Popen(
                cmd,
                stdin=stdin_arg,
                stdout=stdout_arg,
                stderr=stderr_arg,
                env=env,
                cwd=cwd,
                creationflags=creationflags,
                startupinfo=startupinfo
            )

            process = WindowsProcessWrapper(popen)
            logger.debug(f"Windows subprocess created with PID: {process.pid}")
            return process
        else:
            # Unix-like systems: use asyncio subprocess directly
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                env=env,
                cwd=cwd,
                limit=limit
            )
            logger.debug(f"Unix subprocess created with PID: {process.pid}")
            return process

    except FileNotFoundError:
        logger.error(f"Executable not found: {cmd[0]}")
        raise
    except PermissionError:
        logger.error(f"Permission denied executing: {cmd[0]}")
        raise
    except OSError as e:
        if IS_WINDOWS and hasattr(e, 'winerror') and e.winerror == 193:
            logger.error(
                f"OSError 193: Cannot execute {cmd[0]} directly. "
                f"Ensure you are passing a direct executable (e.g., node.exe), not a script."
            )
        raise
