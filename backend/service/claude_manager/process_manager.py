"""
Claude Code Process Manager

Manages Claude CLI as subprocess instances.
Each session has its own independent process and storage directory.

Uses --output-format stream-json for real-time tool usage logging.
"""
import asyncio
import json
import os
import re
import shutil
import time
from logging import getLogger
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable
from datetime import datetime

from service.claude_manager.models import SessionStatus, MCPConfig
from service.claude_manager.constants import CLAUDE_DEFAULT_TIMEOUT, STDIO_BUFFER_LIMIT
from service.claude_manager.platform_utils import (
    IS_WINDOWS,
    DEFAULT_STORAGE_ROOT,
    get_claude_env_vars,
    create_subprocess_cross_platform,
)
from service.claude_manager.cli_discovery import (
    ClaudeNodeConfig,
    find_claude_node_config,
    build_direct_node_command,
)
from service.claude_manager.storage_utils import (
    list_storage_files as _list_storage_files,
    read_storage_file as _read_storage_file,
)
from service.claude_manager.stream_parser import (
    StreamParser,
    StreamEvent,
    StreamEventType,
    ExecutionSummary,
)
from service.logging.session_logger import get_session_logger
from service.utils.utils import now_kst

logger = getLogger(__name__)


class ClaudeProcess:
    """
    Individual Claude Code Process.

    Manages a Claude CLI subprocess.
    Each instance has a unique session ID and storage path.
    """

    def __init__(
        self,
        session_id: str,
        session_name: Optional[str] = None,
        working_dir: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        model: Optional[str] = None,
        max_turns: Optional[int] = None,
        timeout: Optional[float] = None,
        storage_root: Optional[str] = None,
        mcp_config: Optional[MCPConfig] = None,
        system_prompt: Optional[str] = None,
        role: Optional[str] = "worker",
    ):
        self.session_id = session_id
        self.session_name = session_name
        self.model = model
        self.max_turns = max_turns or 50
        self.timeout = timeout or 21600.0  # Default 6 hours
        self.env_vars = env_vars or {}
        self.mcp_config = mcp_config
        self.system_prompt = system_prompt  # Store system prompt for all executions

        # Role settings
        self.role = role or "worker"

        # Storage configuration (using Path for cross-platform compatibility)
        self._storage_root = storage_root or DEFAULT_STORAGE_ROOT
        self._storage_path = str(Path(self._storage_root) / session_id)

        # Use storage path as working directory if not specified
        self.working_dir = working_dir or self._storage_path

        # Process state
        self.process: Optional[asyncio.subprocess.Process] = None
        self.status = SessionStatus.STOPPED
        self.error_message: Optional[str] = None
        self.created_at = now_kst()

        # Shared folder configuration
        self._shared_folder_link_name: Optional[str] = None
        self._shared_folder_path: Optional[str] = None

        # Execution tracking for --resume support
        self._execution_count = 0
        self._conversation_id: Optional[str] = None

        # Claude Node.js configuration (set during initialize)
        self._node_config: Optional[ClaudeNodeConfig] = None

        # Current running process (for execute commands)
        self._current_process: Optional[asyncio.subprocess.Process] = None
        self._execution_lock = asyncio.Lock()

        # ── Pre-warming: overlap next subprocess creation with current execution ──
        self._warm_process: Optional[asyncio.subprocess.Process] = None
        self._warm_cmd: Optional[list] = None
        self._warm_env: Optional[dict] = None
        self._prewarm_lock = asyncio.Lock()
        self._prewarm_task: Optional[asyncio.Task] = None

    @property
    def storage_path(self) -> str:
        """Session-specific storage path."""
        return self._storage_path

    def set_shared_folder(self, link_name: str, shared_path: str) -> None:
        """Configure shared folder info so storage reads can delegate properly.

        Args:
            link_name: Name of the junction/symlink in session storage (e.g. '_shared').
            shared_path: Absolute path to the actual shared folder.
        """
        self._shared_folder_link_name = link_name
        self._shared_folder_path = shared_path
        logger.info(f"[{self.session_id}] Shared folder set: {link_name} → {shared_path}")
        # Update session info file with shared folder metadata
        self._update_session_info_file()

    @property
    def pid(self) -> Optional[int]:
        """Current running process ID."""
        if self._current_process:
            return self._current_process.pid
        return None

    async def initialize(self) -> bool:
        """
        Initialize the session.

        Creates the storage directory and prepares the session.
        Creates .mcp.json file if MCP configuration is provided.

        Returns:
            True if initialization succeeds, False otherwise.
        """
        try:
            self.status = SessionStatus.STARTING
            logger.info(f"[{self.session_id}] Initializing Claude session...")

            # Create storage directory (using Path for cross-platform compatibility)
            Path(self._storage_path).mkdir(parents=True, exist_ok=True)
            logger.info(f"[{self.session_id}] Storage created: {self._storage_path}")

            # Create session info file for tools to read
            self._create_session_info_file()

            # Create working_dir if different from storage path
            if self.working_dir != self._storage_path:
                Path(self.working_dir).mkdir(parents=True, exist_ok=True)

            # Create MCP configuration file (.mcp.json)
            if self.mcp_config and self.mcp_config.servers:
                await self._create_mcp_config()

            # Find Claude Node.js configuration (direct node.exe + cli.js execution)
            node_config = find_claude_node_config()
            if node_config is None:
                raise FileNotFoundError(
                    "Claude Code CLI not found. "
                    "Install it with: 'npm install -g @anthropic-ai/claude-code'"
                )

            # Store Node.js config for use in execute()
            self._node_config = node_config

            # Log the found paths with platform info
            import platform
            logger.info(f"[{self.session_id}] Claude CLI config: {node_config}")
            logger.info(f"[{self.session_id}] Platform: {platform.system()} ({platform.machine()})")

            self.status = SessionStatus.RUNNING
            logger.info(f"[{self.session_id}] ✅ Session initialized successfully")
            return True

        except Exception as e:
            self.status = SessionStatus.ERROR
            self.error_message = str(e)
            logger.error(f"[{self.session_id}] Failed to initialize session: {e}")
            return False

    def _create_session_info_file(self) -> None:
        """
        Create .claude_session.json with session information.

        Placed in storage_path so tools can find it via cwd.
        """
        session_info = {
            "session_id": self.session_id,
            "session_name": self.session_name,
            "role": self.role,
            "storage_path": self._storage_path,
            "created_at": self.created_at.isoformat()
        }

        # Include shared folder info if available
        if self._shared_folder_path:
            session_info["shared_folder_path"] = self._shared_folder_path
            session_info["shared_folder_link"] = self._shared_folder_link_name or "_shared"

        info_path = Path(self._storage_path) / ".claude_session.json"
        with open(info_path, 'w', encoding='utf-8') as f:
            json.dump(session_info, f, indent=2)

        logger.info(f"[{self.session_id}] Session info file created: {info_path}")

    def _update_session_info_file(self) -> None:
        """Re-write .claude_session.json with current state (including shared folder info)."""
        try:
            self._create_session_info_file()
        except Exception as e:
            logger.warning(f"[{self.session_id}] Failed to update session info: {e}")

    # ── Git authentication helpers ──────────────────────────────────

    @staticmethod
    def _setup_git_auth_env(env: Dict[str, str]) -> None:
        """Inject git HTTPS auth into *env* when ``GITHUB_TOKEN`` is present.

        Three layers:
        1. ``GH_TOKEN`` — authenticates the ``gh`` CLI.
        2. ``GIT_TERMINAL_PROMPT=0`` — prevent interactive credential prompts
           inside a non-interactive subprocess.
        3. ``GIT_CONFIG_*`` env vars — transparently rewrite GitHub HTTPS
           URLs to embed the PAT, exactly like GitHub Actions does::

               url."https://x-access-token:<TOKEN>@github.com/".insteadOf
                   = https://github.com/

           This ensures ``git push``, ``git clone``, ``git fetch``, etc.
           work without any credential helper or manual URL editing.
        """
        github_token = env.get('GITHUB_TOKEN')
        if not github_token:
            return

        # gh CLI auth
        env['GH_TOKEN'] = github_token

        # Prevent interactive prompts in non-TTY subprocess
        env['GIT_TERMINAL_PROMPT'] = '0'

        # Inject git config via environment (git ≥ 2.31)
        idx = int(env.get('GIT_CONFIG_COUNT', '0'))

        # URL rewriting: https://github.com/ → https://x-access-token:<PAT>@github.com/
        env[f'GIT_CONFIG_KEY_{idx}'] = (
            f'url.https://x-access-token:{github_token}@github.com/.insteadOf'
        )
        env[f'GIT_CONFIG_VALUE_{idx}'] = 'https://github.com/'
        idx += 1

        env['GIT_CONFIG_COUNT'] = str(idx)

    async def _create_mcp_config(self) -> None:
        """
        Create .mcp.json configuration file.

        Creates MCP configuration file in the session's working_dir.
        Claude Code automatically reads this file to connect to MCP servers.
        """
        if not self.mcp_config:
            return

        mcp_json_path = Path(self.working_dir) / ".mcp.json"
        mcp_data = self.mcp_config.to_mcp_json()

        try:
            with open(mcp_json_path, 'w', encoding='utf-8') as f:
                json.dump(mcp_data, f, indent=2, ensure_ascii=False)

            logger.info(f"[{self.session_id}] 🔌 MCP config created: {mcp_json_path}")
            logger.info(f"[{self.session_id}] MCP servers: {list(self.mcp_config.servers.keys())}")
        except Exception as e:
            logger.error(f"[{self.session_id}] Failed to create MCP config: {e}")

    # ── Pre-warm helpers ─────────────────────────────────────────

    async def _take_warm_process(
        self, cmd: list, env: dict,
    ) -> Optional[asyncio.subprocess.Process]:
        """Take the pre-warmed subprocess if its command matches *cmd*.

        Returns the warm process (caller owns it) or ``None``.
        """
        async with self._prewarm_lock:
            if (
                self._warm_process is not None
                and self._warm_cmd == cmd
                and self._warm_process.returncode is None  # still alive
            ):
                proc = self._warm_process
                self._warm_process = None
                self._warm_cmd = None
                self._warm_env = None
                logger.info(
                    f"[{self.session_id}] ♻️ Using pre-warmed subprocess (pid {proc.pid})"
                )
                return proc
            # Mismatch or dead — discard if present
            await self._discard_warm_process_locked()
            return None

    async def _discard_warm_process_locked(self) -> None:
        """Kill and clear the warm process. Caller must hold ``_prewarm_lock``."""
        if self._warm_process is not None:
            try:
                self._warm_process.kill()
                await self._warm_process.wait()
            except (ProcessLookupError, OSError):
                pass
            self._warm_process = None
            self._warm_cmd = None
            self._warm_env = None

    async def _discard_warm_process(self) -> None:
        """Public wrapper that acquires the lock first."""
        async with self._prewarm_lock:
            await self._discard_warm_process_locked()
        # Cancel any running prewarm task
        if self._prewarm_task and not self._prewarm_task.done():
            self._prewarm_task.cancel()
            self._prewarm_task = None

    def _schedule_prewarm(self, cmd: list, env: dict) -> None:
        """Fire-and-forget: create a warm subprocess in the background."""
        if self._prewarm_task and not self._prewarm_task.done():
            return  # already pre-warming
        self._prewarm_task = asyncio.create_task(
            self._do_prewarm(cmd, env)
        )

    async def _do_prewarm(self, cmd: list, env: dict) -> None:
        """Background coroutine that creates a warm subprocess."""
        try:
            proc = await create_subprocess_cross_platform(
                cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=self.working_dir,
                limit=STDIO_BUFFER_LIMIT,
            )
            async with self._prewarm_lock:
                # Another execution may have started; discard old warm if any
                await self._discard_warm_process_locked()
                self._warm_process = proc
                self._warm_cmd = cmd
                self._warm_env = env
            logger.info(
                f"[{self.session_id}] 🔥 Pre-warmed subprocess ready (pid {proc.pid})"
            )
        except Exception as e:
            logger.debug(f"[{self.session_id}] Pre-warm failed (non-critical): {e}")

    async def execute(
        self,
        prompt: str,
        timeout: float = CLAUDE_DEFAULT_TIMEOUT,
        skip_permissions: Optional[bool] = None,
        system_prompt: Optional[str] = None,
        max_turns: Optional[int] = None,
        resume: Optional[bool] = None,
        on_event: Optional[Callable[[StreamEvent], None]] = None
    ) -> Dict:
        """
        Execute a prompt with Claude using streaming JSON output.

        Uses --output-format stream-json for real-time parsing of:
        - Tool invocations and their results
        - Assistant messages
        - Execution costs and timing

        Args:
            prompt: The prompt to send to Claude.
            timeout: Execution timeout in seconds.
            skip_permissions: Skip permission prompts (None uses environment variable).
            system_prompt: Additional system prompt (for autonomous mode instructions).
            max_turns: Maximum turns for this execution (None uses session setting).
            resume: Whether to resume previous conversation (None = auto-detect).
            on_event: Callback for real-time stream events (tool use, messages, etc.).

        Returns:
            Result dictionary with success, output, error, cost_usd, duration_ms,
            tool_calls, and execution_summary.
        """
        async with self._execution_lock:
            if self.status != SessionStatus.RUNNING:
                return {
                    "success": False,
                    "error": f"Session is not running (status: {self.status})"
                }

            start_time = datetime.now()

            # Get session logger for real-time logging
            session_logger = get_session_logger(self.session_id, create_if_missing=False)

            # Create real-time logging callback
            def realtime_log_event(event: StreamEvent):
                """Log stream events in real-time to session logger."""
                # Call user-provided callback if any
                if on_event:
                    on_event(event)

                # Log to session logger for UI visibility
                if session_logger:
                    if event.event_type == StreamEventType.SYSTEM_INIT:
                        session_logger.log_stream_event("system_init", {
                            "model": event.model,
                            "tools": event.tools,
                            "mcp_servers": event.mcp_servers
                        })
                    elif event.event_type == StreamEventType.TOOL_USE:
                        if event.tool_name:
                            session_logger.log_tool_use(
                                tool_name=event.tool_name,
                                tool_input=event.tool_input,
                                tool_id=event.tool_use_id
                            )
                    elif event.event_type == StreamEventType.ASSISTANT_MESSAGE:
                        # Log tool uses from assistant message content
                        if event.tool_name:
                            session_logger.log_tool_use(
                                tool_name=event.tool_name,
                                tool_input=event.tool_input,
                                tool_id=event.tool_use_id
                            )

            # Initialize stream parser with real-time logging
            stream_parser = StreamParser(
                on_event=realtime_log_event,
                session_id=self.session_id
            )

            try:
                # Prepare environment variables
                env = os.environ.copy()
                env.update(get_claude_env_vars())
                env.update(self.env_vars)

                # ── GitHub HTTPS authentication ──────────────────────
                # git doesn't natively read GITHUB_TOKEN.  We inject
                # git config via GIT_CONFIG_* env vars (git 2.31+) to
                # transparently rewrite https://github.com/ URLs so
                # they include the PAT — same pattern GitHub Actions uses.
                self._setup_git_auth_env(env)

                # Get Claude CLI config
                node_config = self._node_config or find_claude_node_config()
                if not node_config:
                    return {
                        "success": False,
                        "error": "Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
                    }

                # Build arguments with stream-json output format
                args = ["--print", "--verbose", "--output-format", "stream-json"]

                # Resume previous conversation
                should_resume = resume if resume is not None else (self._execution_count > 0 and self._conversation_id)
                if should_resume and self._conversation_id:
                    args.extend(["--resume", self._conversation_id])
                    logger.info(f"[{self.session_id}] 🔄 Resuming conversation: {self._conversation_id}")

                # Skip permission prompts
                should_skip_permissions = skip_permissions
                if should_skip_permissions is None:
                    env_skip = os.environ.get('CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS', 'true').lower()
                    should_skip_permissions = env_skip in ('true', '1', 'yes', 'on')

                if should_skip_permissions:
                    args.append("--dangerously-skip-permissions")
                    logger.info(f"[{self.session_id}] 🤖 Autonomous mode: permission bypass enabled")

                # Model selection
                effective_model = self.model or os.environ.get('ANTHROPIC_MODEL')
                if effective_model:
                    args.extend(["--model", effective_model])
                    logger.info(f"[{self.session_id}] 🤖 Using model: {effective_model}")

                # Max turns
                effective_max_turns = max_turns or self.max_turns
                if effective_max_turns:
                    args.extend(["--max-turns", str(effective_max_turns)])

                # Disable built-in tools via config system
                from service.config.manager import get_config_manager
                from service.config.sub_config.general.limits_config import LimitsConfig
                limits_cfg = get_config_manager().load_config(LimitsConfig)
                if limits_cfg.disallowed_tools:
                    for tool_name in limits_cfg.disallowed_tools.split(","):
                        tool_name = tool_name.strip()
                        if tool_name:
                            args.extend(["--disallowedTools", tool_name])

                # System prompt
                effective_system_prompt = system_prompt or self.system_prompt
                if effective_system_prompt:
                    args.extend(["--append-system-prompt", effective_system_prompt])
                    logger.info(f"[{self.session_id}] 📝 System prompt applied ({len(effective_system_prompt)} chars)")

                # Build command
                cmd = build_direct_node_command(node_config, args)

                logger.info(f"[{self.session_id}] 🚀 Executing with stream-json output...")
                logger.info(f"[{self.session_id}] Prompt length: {len(prompt)} chars")

                # Try pre-warmed process first, fall back to cold start
                warm = await self._take_warm_process(cmd, env)
                if warm is not None:
                    self._current_process = warm
                else:
                    self._current_process = await create_subprocess_cross_platform(
                        cmd,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env=env,
                        cwd=self.working_dir,
                        limit=STDIO_BUFFER_LIMIT
                    )

                # Stream output with real-time parsing
                result = await self._stream_execute(
                    process=self._current_process,
                    prompt=prompt,
                    timeout=timeout,
                    stream_parser=stream_parser
                )

                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                # Get execution summary
                summary = stream_parser.get_summary()

                # Update conversation ID for resume support
                if summary.session_id:
                    self._conversation_id = summary.session_id
                    logger.info(f"[{self.session_id}] 📝 Captured conversation ID: {self._conversation_id}")

                if result["success"]:
                    self._execution_count += 1
                    logger.info(f"[{self.session_id}] ✅ Execution #{self._execution_count} completed in {duration_ms}ms")
                    logger.info(f"[{self.session_id}] 🔧 Tool calls: {len(summary.tool_calls)}, Cost: ${summary.total_cost_usd:.6f}")

                    # Log tool call details with more context
                    for i, tool_call in enumerate(summary.tool_calls, 1):
                        tool_name = tool_call.get("name", "unknown")
                        tool_input = tool_call.get("input", {})
                        detail = self._format_tool_detail(tool_name, tool_input)
                        logger.info(f"[{self.session_id}]   [{i}] {tool_name}: {detail}")

                # Save work log with tool details
                await self._append_work_log(
                    prompt=prompt,
                    output=summary.final_output,
                    duration_ms=duration_ms,
                    success=result["success"],
                    tool_calls=summary.tool_calls,
                    cost_usd=summary.total_cost_usd
                )

                return {
                    "success": result["success"],
                    "output": summary.final_output,
                    "error": result.get("error") or summary.error_message,
                    "duration_ms": duration_ms,
                    "cost_usd": summary.total_cost_usd,
                    "execution_count": self._execution_count,
                    "tool_calls": summary.tool_calls,
                    "num_turns": summary.num_turns,
                    "usage": summary.usage,
                    "model": summary.model,
                    "stop_reason": summary.stop_reason
                }

            except Exception as e:
                logger.error(f"[{self.session_id}] Execution error: {e}", exc_info=True)
                return {
                    "success": False,
                    "error": str(e)
                }
            finally:
                self._current_process = None
                # Pre-warm next subprocess in the background
                try:
                    self._schedule_prewarm(cmd, env)
                except NameError:
                    pass  # cmd/env not yet built when error occurred early

    async def _stream_execute(
        self,
        process: asyncio.subprocess.Process,
        prompt: str,
        timeout: float,
        stream_parser: StreamParser
    ) -> Dict:
        """
        Execute with streaming output parsing.

        Reads stdout line by line and parses each JSON event.
        """
        stdout_lines: List[str] = []
        stderr_lines: List[str] = []

        async def read_stdout():
            """Read stdout and parse stream-json lines."""
            while True:
                try:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    line_str = line.decode('utf-8', errors='replace').strip()
                    if line_str:
                        stdout_lines.append(line_str)
                        # Parse each JSON line for real-time events
                        stream_parser.parse_line(line_str)
                except Exception as e:
                    logger.warning(f"[{self.session_id}] stdout read error: {e}")
                    break

        async def read_stderr():
            """Read stderr for error messages."""
            while True:
                try:
                    line = await process.stderr.readline()
                    if not line:
                        break
                    line_str = line.decode('utf-8', errors='replace').strip()
                    if line_str:
                        stderr_lines.append(line_str)
                        logger.debug(f"[{self.session_id}] stderr: {line_str}")
                except Exception as e:
                    logger.warning(f"[{self.session_id}] stderr read error: {e}")
                    break

        try:
            # Write prompt to stdin and close
            process.stdin.write(prompt.encode('utf-8'))
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()

            # Read stdout and stderr concurrently with timeout
            await asyncio.wait_for(
                asyncio.gather(read_stdout(), read_stderr()),
                timeout=timeout
            )

            # Wait for process to complete
            await asyncio.wait_for(process.wait(), timeout=10.0)

        except asyncio.TimeoutError:
            logger.error(f"[{self.session_id}] Execution timed out after {timeout}s")
            await self._kill_current_process()
            return {
                "success": False,
                "error": f"Execution timed out after {timeout} seconds"
            }

        success = process.returncode == 0
        error = None

        if not success and stderr_lines:
            error = "\n".join(stderr_lines)

        return {
            "success": success,
            "error": error,
            "stdout_lines": stdout_lines,
            "stderr_lines": stderr_lines
        }

    def _format_tool_detail(self, tool_name: str, tool_input: Dict) -> str:
        """
        Format tool input into a concise, informative detail string.

        Args:
            tool_name: Name of the tool (Bash, Read, Write, etc.)
            tool_input: Tool input dictionary with parameters

        Returns:
            Formatted detail string
        """
        if not tool_input:
            return "(no input)"

        try:
            # Bash/shell commands
            if tool_name.lower() in ("bash", "shell", "execute"):
                command = tool_input.get("command", tool_input.get("cmd", ""))
                if command:
                    # Truncate long commands
                    if len(command) > 100:
                        return f"`{command[:100]}...`"
                    return f"`{command}`"

            # Read file operations
            elif tool_name.lower() in ("read", "readfile", "read_file", "view"):
                file_path = tool_input.get("file_path", tool_input.get("path", tool_input.get("file", "")))
                start_line = tool_input.get("start_line", tool_input.get("offset", ""))
                end_line = tool_input.get("end_line", tool_input.get("limit", ""))
                if file_path:
                    # Get just filename for brevity
                    filename = file_path.split("/")[-1].split("\\")[-1]
                    if start_line and end_line:
                        return f"{filename} (lines {start_line}-{end_line})"
                    elif start_line:
                        return f"{filename} (from line {start_line})"
                    return filename

            # Write file operations
            elif tool_name.lower() in ("write", "writefile", "write_file", "edit", "edit_file"):
                file_path = tool_input.get("file_path", tool_input.get("path", tool_input.get("file", "")))
                content = tool_input.get("content", tool_input.get("text", ""))
                if file_path:
                    filename = file_path.split("/")[-1].split("\\")[-1]
                    if content:
                        lines = content.count("\n") + 1
                        return f"{filename} ({lines} lines)"
                    return filename

            # Glob/search operations
            elif tool_name.lower() in ("glob", "search", "find", "list", "ls"):
                pattern = tool_input.get("pattern", tool_input.get("query", tool_input.get("path", "")))
                if pattern:
                    if len(pattern) > 60:
                        return f"`{pattern[:60]}...`"
                    return f"`{pattern}`"

            # Grep operations
            elif tool_name.lower() in ("grep", "ripgrep", "rg"):
                pattern = tool_input.get("pattern", tool_input.get("query", tool_input.get("regex", "")))
                path = tool_input.get("path", tool_input.get("directory", ""))
                if pattern:
                    result = f"`{pattern[:40]}`" if len(pattern) > 40 else f"`{pattern}`"
                    if path:
                        result += f" in {path.split('/')[-1].split(chr(92))[-1]}"
                    return result

            # MCP tool calls (mcp__server__tool format)
            elif tool_name.startswith("mcp__") or "__" in tool_name:
                # Try to extract most relevant parameter
                for key in ["query", "path", "file_path", "command", "url", "content", "message"]:
                    if key in tool_input:
                        value = str(tool_input[key])
                        if len(value) > 80:
                            return f"{key}={value[:80]}..."
                        return f"{key}={value}"

            # Default: show first meaningful parameter
            for key, value in tool_input.items():
                if key.startswith("_"):
                    continue
                value_str = str(value)
                if len(value_str) > 80:
                    return f"{key}={value_str[:80]}..."
                return f"{key}={value_str}"

            return "(empty input)"

        except Exception as e:
            return f"(parse error: {e})"

    async def _append_work_log(
        self,
        prompt: str,
        output: str,
        duration_ms: int,
        success: bool,
        tool_calls: Optional[List[Dict]] = None,
        cost_usd: Optional[float] = None
    ):
        """
        Append execution log to WORK_LOG.md in storage directory.

        This creates a persistent record of all work performed by this session,
        including detailed tool usage information.
        """
        try:
            log_path = Path(self._storage_path) / "WORK_LOG.md"
            timestamp = now_kst().strftime("%Y-%m-%d %H:%M:%S")
            status_emoji = "✅" if success else "❌"

            # Truncate long content for log readability
            prompt_preview = prompt[:200] + "..." if len(prompt) > 200 else prompt
            output_preview = output[:500] + "..." if len(output) > 500 else output

            # Format tool calls
            tool_section = ""
            if tool_calls:
                tool_section = "\n### Tool Calls\n"
                for i, tool in enumerate(tool_calls, 1):
                    tool_name = tool.get("name", "unknown")
                    tool_input = tool.get("input", {})
                    # Truncate tool input for readability
                    input_str = json.dumps(tool_input, ensure_ascii=False)
                    if len(input_str) > 200:
                        input_str = input_str[:200] + "..."
                    tool_section += f"- **[{i}] {tool_name}**: `{input_str}`\n"

            # Format cost
            cost_str = f"**Cost:** ${cost_usd:.6f}\n" if cost_usd else ""

            log_entry = f"""
---

## [{status_emoji}] Execution #{self._execution_count} - {timestamp}

**Duration:** {duration_ms}ms
{cost_str}
### Prompt
```
{prompt_preview}
```
{tool_section}
### Output
```
{output_preview}
```

"""

            # Create file with header if it doesn't exist
            if not log_path.exists():
                header = f"""# Work Log - Session {self.session_id}

**Session Name:** {self.session_name or 'Unnamed'}
**Created:** {self.created_at.strftime("%Y-%m-%d %H:%M:%S")}
**Model:** {self.model or 'Default'}

This file contains a log of all work performed by this session.

"""
                log_path.write_text(header, encoding='utf-8')

            # Append log entry
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(log_entry)

            logger.debug(f"[{self.session_id}] Work log updated: {log_path}")

        except Exception as e:
            logger.warning(f"[{self.session_id}] Failed to write work log: {e}")

    async def _kill_current_process(self):
        """Forcefully terminate the currently running process (cross-platform)."""
        if self._current_process:
            try:
                if IS_WINDOWS:
                    # On Windows, use terminate() first, then kill() if needed
                    # kill() on Windows is equivalent to terminate()
                    self._current_process.terminate()
                    try:
                        await asyncio.wait_for(self._current_process.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        # Force kill if graceful termination fails
                        self._current_process.kill()
                        await self._current_process.wait()
                else:
                    # On Unix, try SIGTERM first, then SIGKILL
                    try:
                        self._current_process.terminate()
                        await asyncio.wait_for(self._current_process.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        self._current_process.kill()
                        await self._current_process.wait()
            except ProcessLookupError:
                # Process already terminated
                logger.debug(f"[{self.session_id}] Process already terminated")
            except Exception as e:
                logger.warning(f"[{self.session_id}] Failed to kill process: {e}")

    def list_storage_files(self, subpath: str = "") -> List[Dict]:
        """
        List all files in the storage directory recursively.

        Files matching .gitignore patterns and default ignore patterns
        (node_modules, .venv, etc.) are automatically excluded.

        Args:
            subpath: Subdirectory path (empty string for root).

        Returns:
            List of file information dictionaries.
        """
        return _list_storage_files(
            storage_path=self._storage_path,
            subpath=subpath,
            session_id=self.session_id,
            include_gitignore=True
        )

    def read_storage_file(self, file_path: str, encoding: str = "utf-8") -> Optional[Dict]:
        """
        Read storage file content.

        If the requested path starts with the shared folder link name
        (e.g. '_shared/'), the read is delegated to the shared folder's
        real path so that symlink/junction path validation succeeds.

        Args:
            file_path: File path (relative to storage root).
            encoding: File encoding.

        Returns:
            File content dictionary or None.
        """
        # Normalize separators
        normalized = file_path.replace("\\", "/")

        # Detect shared-folder reads and delegate to the real shared path
        if self._shared_folder_link_name and self._shared_folder_path:
            prefix = self._shared_folder_link_name + "/"
            if normalized.startswith(prefix) or normalized == self._shared_folder_link_name:
                relative = normalized[len(prefix):] if normalized.startswith(prefix) else ""
                if not relative:
                    return None  # Can't read a directory
                result = _read_storage_file(
                    storage_path=self._shared_folder_path,
                    file_path=relative,
                    encoding=encoding,
                    session_id=self.session_id,
                )
                # Restore the original path in the result so the UI shows it correctly
                if result:
                    result["file_path"] = file_path
                return result

        return _read_storage_file(
            storage_path=self._storage_path,
            file_path=file_path,
            encoding=encoding,
            session_id=self.session_id
        )

    async def stop(self):
        """Stop session and cleanup resources."""
        try:
            logger.info(f"[{self.session_id}] Stopping session...")

            # Discard pre-warmed process
            await self._discard_warm_process()

            # Terminate currently running process
            await self._kill_current_process()

            self.status = SessionStatus.STOPPED
            logger.info(f"[{self.session_id}] Session stopped")

        except Exception as e:
            logger.error(f"[{self.session_id}] Error stopping session: {e}")
            self.status = SessionStatus.STOPPED

    async def cleanup_storage(self):
        """Delete storage directory."""
        try:
            storage_path = Path(self._storage_path)
            if storage_path.exists():
                shutil.rmtree(storage_path)
                logger.info(f"[{self.session_id}] Storage cleaned up: {self._storage_path}")
        except Exception as e:
            logger.error(f"[{self.session_id}] Failed to cleanup storage: {e}")

    def is_alive(self) -> bool:
        """Check if session is active."""
        return self.status == SessionStatus.RUNNING
