"""
Claude CLI Discovery

Utilities for finding and configuring Claude CLI (Node.js based).
"""
import os
import shutil
from logging import getLogger
from pathlib import Path
from typing import Optional, List

from service.claude_manager.platform_utils import IS_WINDOWS, IS_MACOS, IS_LINUX

logger = getLogger(__name__)


class ClaudeNodeConfig:
    """
    Configuration for direct Node.js execution of Claude CLI.

    This bypasses cmd.exe/PowerShell entirely on Windows,
    avoiding command line length limits and escaping issues.
    """
    def __init__(self, node_path: str, cli_js_path: str, base_dir: str):
        self.node_path = node_path
        self.cli_js_path = cli_js_path
        self.base_dir = base_dir

    def __repr__(self):
        return f"ClaudeNodeConfig(node='{self.node_path}', cli='{self.cli_js_path}')"


def find_claude_node_config() -> Optional[ClaudeNodeConfig]:
    """
    Find Node.js and Claude CLI JavaScript file paths for direct execution.

    This completely bypasses cmd.exe/PowerShell on Windows by finding:
    1. node.exe path
    2. @anthropic-ai/claude-code/cli.js path

    Returns:
        ClaudeNodeConfig with paths, or None if not found.
    """
    node_path = None
    cli_js_path = None
    base_dir = None

    if IS_WINDOWS:
        # Strategy 1: Find claude.cmd and parse it to get paths
        claude_cmd_paths = []

        # Check common npm global installation paths
        for ext in ['.cmd', '.ps1', '']:
            found = shutil.which(f"claude{ext}")
            if found:
                claude_cmd_paths.append(Path(found))

        # Additional common paths
        appdata = os.environ.get('APPDATA')
        if appdata:
            claude_cmd_paths.append(Path(appdata) / 'npm' / 'claude.cmd')
        claude_cmd_paths.append(Path.home() / 'AppData' / 'Roaming' / 'npm' / 'claude.cmd')

        # nvm4w common paths
        nvm_paths = [
            Path('C:/nvm4w/nodejs'),
            Path('C:/Program Files/nodejs'),
            Path.home() / 'AppData' / 'Local' / 'nvm',
        ]
        for nvm_path in nvm_paths:
            if nvm_path.exists():
                claude_cmd_paths.append(nvm_path / 'claude.cmd')

        # Find the first existing claude.cmd and derive paths
        for cmd_path in claude_cmd_paths:
            if cmd_path.exists():
                base_dir = cmd_path.parent
                potential_node = base_dir / 'node.exe'
                potential_cli = base_dir / 'node_modules' / '@anthropic-ai' / 'claude-code' / 'cli.js'

                if potential_cli.exists():
                    # Found cli.js, now find node
                    cli_js_path = str(potential_cli)

                    if potential_node.exists():
                        node_path = str(potential_node)
                    else:
                        # Use node from PATH
                        node_path = shutil.which('node') or shutil.which('node.exe')

                    if node_path and cli_js_path:
                        logger.info(f"Found Claude via cmd wrapper: node={node_path}, cli={cli_js_path}")
                        return ClaudeNodeConfig(node_path, cli_js_path, str(base_dir))

        # Strategy 2: Direct search for cli.js in common npm locations
        npm_module_paths = []
        if appdata:
            npm_module_paths.append(Path(appdata) / 'npm' / 'node_modules' / '@anthropic-ai' / 'claude-code' / 'cli.js')

        for nvm_path in nvm_paths:
            npm_module_paths.append(nvm_path / 'node_modules' / '@anthropic-ai' / 'claude-code' / 'cli.js')

        for cli_path in npm_module_paths:
            if cli_path.exists():
                cli_js_path = str(cli_path)
                base_dir = str(cli_path.parent.parent.parent.parent)  # up to npm root
                node_path = shutil.which('node') or shutil.which('node.exe')

                if node_path:
                    logger.info(f"Found Claude via direct search: node={node_path}, cli={cli_js_path}")
                    return ClaudeNodeConfig(node_path, cli_js_path, base_dir)

    else:
        # Unix-like systems: find claude binary and derive cli.js path
        claude_path = shutil.which('claude')

        if claude_path:
            # Read the shebang/script to find cli.js
            claude_path = Path(claude_path).resolve()

            # Common cli.js locations relative to claude binary
            possible_cli_paths = [
                claude_path.parent / 'node_modules' / '@anthropic-ai' / 'claude-code' / 'cli.js',
                claude_path.parent.parent / 'lib' / 'node_modules' / '@anthropic-ai' / 'claude-code' / 'cli.js',
                Path.home() / '.npm-global' / 'lib' / 'node_modules' / '@anthropic-ai' / 'claude-code' / 'cli.js',
                Path('/usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js'),
                Path('/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js'),
            ]

            for cli_path in possible_cli_paths:
                if cli_path.exists():
                    cli_js_path = str(cli_path)
                    base_dir = str(cli_path.parent.parent.parent.parent)
                    node_path = shutil.which('node')

                    if node_path:
                        logger.info(f"Found Claude on Unix: node={node_path}, cli={cli_js_path}")
                        return ClaudeNodeConfig(node_path, cli_js_path, base_dir)

        # Fallback: just use 'claude' command directly (for compatibility)
        claude_path = shutil.which('claude')
        if claude_path:
            node_path = shutil.which('node')
            if node_path:
                # Return with claude_path as cli.js - will be handled specially
                logger.info(f"Falling back to claude binary: {claude_path}")
                return ClaudeNodeConfig(node_path, str(claude_path), str(Path(claude_path).parent))

    logger.warning("Claude CLI (Node.js configuration) not found")
    return None


def find_claude_executable() -> Optional[str]:
    """
    Find the Claude CLI executable path (legacy, for compatibility).

    Use find_claude_node_config() for new code.
    """
    config = find_claude_node_config()
    if config:
        if IS_WINDOWS:
            return config.node_path  # Return node.exe on Windows
        else:
            return shutil.which('claude')  # Return claude binary on Unix
    return None


def build_direct_node_command(config: ClaudeNodeConfig, args: List[str]) -> List[str]:
    """
    Build command for direct Node.js execution (bypasses cmd.exe/PowerShell entirely).

    Args:
        config: ClaudeNodeConfig with node and cli.js paths.
        args: Claude CLI arguments.

    Returns:
        List of command arguments starting with node.exe.
    """
    # Direct execution: node.exe cli.js [args...]
    # No cmd.exe, no PowerShell, no shell escaping issues
    return [config.node_path, config.cli_js_path] + args
