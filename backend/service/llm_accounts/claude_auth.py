"""Many Claude Code logins on one server, side by side.

Each ``login`` account owns a directory that becomes ``CLAUDE_CONFIG_DIR``
for every CLI call made on its behalf. The CLI keys its credential file on
that directory, so signing in to a second account never signs the first one
out and never touches the operator's own ``~/.claude``.

Other channels: a long-lived ``claude setup-token``
(``CLAUDE_CODE_OAUTH_TOKEN``), a Console key (``ANTHROPIC_API_KEY``), or
``system`` — whatever the machine's own CLI is already logged into. Every
auth-bearing variable inherited from the server's environment is stripped
first, so a key exported into the container can never silently decide which
account pays.

Nothing here reads or copies OAuth tokens: the official CLI authenticates
itself, and this module only tells it which account directory to use.

**Logging in from a browser that is not on this machine.** The CLI would
rather open a browser and catch a localhost callback; on a server there is
no browser and the callback cannot reach it. So it prints a URL and waits
for the code on stdin — which is exactly the flow the UI drives: the login
job streams every line out, the user opens the URL wherever they are, and
pastes the code back through :meth:`LoginJobs.send_input`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "CLAUDE_AUTH_ENV",
    "LoginJobs",
    "account_env",
    "claude_binary",
    "logout",
    "probe",
    "status",
]

#: Auth channels the CLI honours from the environment. Stripped from the
#: inherited environment so an unrelated exported key cannot choose the
#: account. The last five are session stamps a parent Claude Code process
#: leaves behind — dropped even in ``system`` mode, where the rest stay.
CLAUDE_AUTH_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS",
    "AWS_BEARER_TOKEN_BEDROCK",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CONFIG_DIR",
    "CLAUDE_SECURESTORAGE_CONFIG_DIR",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_BRIDGE_SESSION_ID",
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
)
_SESSION_STAMPS = CLAUDE_AUTH_ENV[-5:]

_ANSI = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]|\x1B\][^\x07]*\x07")
_URL = re.compile(r"https?://[^\s\"'<>()\[\]]+")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def find_urls(text: str) -> List[str]:
    return [u.rstrip(".,);") for u in _URL.findall(strip_ansi(text))]


def claude_binary() -> str:
    return (
        (os.environ.get("CLAUDE_CODE_BINARY") or "").strip()
        or shutil.which("claude")
        or "claude"
    )


def account_env(
    *,
    auth_method: str,
    config_dir: Optional[str] = None,
    oauth_token: Optional[str] = None,
    api_key: Optional[str] = None,
    base: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """The environment one CLI call runs with, for one account."""
    parent = dict(base if base is not None else os.environ)
    strip = _SESSION_STAMPS if auth_method == "system" else CLAUDE_AUTH_ENV
    upper = {k.upper() for k in strip}
    env = {k: v for k, v in parent.items() if k.upper() not in upper}
    if auth_method == "login" and config_dir:
        Path(config_dir).mkdir(parents=True, exist_ok=True)
        env["CLAUDE_CONFIG_DIR"] = config_dir
        # Claude Code 2.1.220+ derives its secure-storage name from this too
        env["CLAUDE_SECURESTORAGE_CONFIG_DIR"] = config_dir
    elif auth_method == "token" and oauth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
        if config_dir:
            env["CLAUDE_CONFIG_DIR"] = config_dir
    elif auth_method == "api_key" and api_key:
        env["ANTHROPIC_API_KEY"] = api_key
        if config_dir:
            env["CLAUDE_CONFIG_DIR"] = config_dir
    env["DISABLE_AUTOUPDATER"] = "1"
    env["CLAUDE_CODE_SKIP_PROMPT_HISTORY"] = "1"
    env.setdefault("CI", "1")
    return env


async def _run(
    binary: str, args: List[str], *, env: Dict[str, str], cwd: Optional[str] = None,
    timeout_s: float = 20.0,
) -> Dict[str, Any]:
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env, cwd=cwd,
        )
    except (FileNotFoundError, OSError) as exc:
        return {"code": -1, "stdout": "", "stderr": str(exc), "timed_out": False, "missing": True}
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        timed_out = False
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        out, err = b"", b""
        timed_out = True
    return {
        "code": proc.returncode,
        "stdout": out.decode("utf-8", "replace"),
        "stderr": err.decode("utf-8", "replace"),
        "timed_out": timed_out,
        "missing": False,
    }


async def probe(binary: Optional[str] = None) -> Dict[str, Any]:
    """Is a `claude` binary reachable, and which version."""
    path = binary or claude_binary()
    resolved = shutil.which(path) or (path if Path(path).exists() else "")
    if not resolved:
        return {"found": False, "path": "", "version": ""}
    result = await _run(resolved, ["--version"], env=dict(os.environ), timeout_s=15.0)
    version = strip_ansi(result["stdout"]).strip().splitlines()[0] if result["stdout"] else ""
    return {"found": True, "path": resolved, "version": version}


def parse_status(stdout: str, stderr: str) -> Dict[str, Any]:
    text = strip_ansi(stdout).strip()
    start = text.find("{")
    if start >= 0:
        try:
            raw = json.loads(text[start:])
            if isinstance(raw, dict):
                def s(*keys: str) -> Optional[str]:
                    for key in keys:
                        value = raw.get(key)
                        if isinstance(value, str) and value:
                            return value
                    return None
                return {
                    "loggedIn": bool(raw.get("loggedIn") or raw.get("logged_in")),
                    "method": s("authMethod", "auth_method"),
                    "email": s("email"),
                    "organization": s("orgName", "organizationName"),
                    "subscription": s("subscriptionType", "subscription_type"),
                }
        except json.JSONDecodeError:
            pass
    all_text = f"{text}\n{strip_ansi(stderr)}"
    logged_in = bool(
        re.search(r"logged in|authenticated as|login method", all_text, re.I)
    ) and not re.search(r"not logged in|not authenticated", all_text, re.I)
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", all_text)
    return {
        "loggedIn": logged_in,
        "email": email.group(0) if email else None,
        "error": None if logged_in else (all_text.strip()[:400] or None),
    }


async def status(binary: str, env: Dict[str, str]) -> Dict[str, Any]:
    result = await _run(binary, ["auth", "status", "--json"], env=env)
    if result["code"] != 0 and re.search(r"unknown option|unexpected argument", result["stderr"], re.I):
        result = await _run(binary, ["auth", "status"], env=env)
    parsed = parse_status(result["stdout"], result["stderr"])
    if result["missing"]:
        parsed["error"] = "claude CLI 를 찾을 수 없습니다"
    elif result["timed_out"]:
        parsed["error"] = "claude auth status 가 응답하지 않았습니다"
    return parsed


async def logout(binary: str, env: Dict[str, str]) -> bool:
    return (await _run(binary, ["auth", "logout"], env=env))["code"] == 0


async def smoke_test(binary: str, env: Dict[str, str], model: str, scratch: str) -> Dict[str, Any]:
    """One real, token-only generation.

    The only honest "is this account usable" check: ``auth status`` happily
    reports a logged-in account whose plan has lapsed.
    """
    Path(scratch).mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()
    started = loop.time()
    args = [
        "-p", "--output-format", "json", "--model", model,
        "--tools", "", "--max-turns", "1",
        "--system-prompt", "You are a connectivity probe. Answer with the single word OK.",
        "ping",
    ]
    result = await _run(binary, args, env=env, cwd=scratch, timeout_s=90.0)
    if result["code"] != 0 and re.search(r"--tools", result["stderr"], re.I):
        legacy = [a for i, a in enumerate(args) if a != "--tools" and args[i - 1] != "--tools"]
        result = await _run(binary, legacy, env=env, cwd=scratch, timeout_s=90.0)
    latency_ms = int((loop.time() - started) * 1000)
    out = strip_ansi(result["stdout"])
    start = out.find("{")
    if start >= 0:
        try:
            parsed = json.loads(out[start:])
            if parsed.get("is_error"):
                return {"ok": False, "latencyMs": latency_ms,
                        "error": str(parsed.get("result") or parsed.get("subtype"))}
            usage = parsed.get("modelUsage") or {}
            return {
                "ok": True, "latencyMs": latency_ms,
                "reply": str(parsed.get("result") or "")[:200],
                "model": next(iter(usage), model),
            }
        except json.JSONDecodeError:
            pass
    if result["timed_out"]:
        why = "시간 초과 (90초)"
    else:
        why = strip_ansi(result["stderr"] or result["stdout"]).strip()[:500] or f"exit {result['code']}"
    return {"ok": False, "latencyMs": latency_ms, "error": why}


class LoginJobs:
    """``claude auth login`` as a streamed, interruptible job.

    The CLI wants to open a browser and catch a localhost callback. On a
    server it can do neither, so it prints a URL and reads the code from
    stdin — which is why stdin stays open for :meth:`send_input`.
    """

    def __init__(self, emit: Callable[[Dict[str, Any]], None]) -> None:
        self._emit = emit
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def active(self, account_id: str) -> Optional[str]:
        for job_id, job in self._jobs.items():
            if job["account_id"] == account_id:
                return job_id
        return None

    async def start(
        self,
        *,
        binary: str,
        account_id: str,
        env: Dict[str, str],
        console: bool = False,
        on_done: Optional[Callable[[bool], Awaitable[None]]] = None,
        job_id: Optional[str] = None,
        plain: bool = False,
    ) -> str:
        job_id = job_id or uuid.uuid4().hex
        # ``--claudeai`` pins the subscription flow on CLIs that ask which
        # one; older ones do not know the flag and are retried without it.
        flavour = ["--console"] if console else ([] if plain else ["--claudeai"])
        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "auth", "login", *flavour,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except (FileNotFoundError, OSError) as exc:
            self._emit({"jobId": job_id, "accountId": account_id, "type": "done",
                        "ok": False, "error": f"claude 실행 실패: {exc}"})
            return job_id
        self._jobs[job_id] = {"proc": proc, "account_id": account_id}
        # Through ``spawn_background``: a bare ``create_task`` is held only by
        # a weak reference, so this pump can be collected mid-login and take
        # the flow with it — no URL, no verdict, no error. The one thing worse
        # than a failed login is one that never says anything.
        from service.utils.background import spawn_background

        spawn_background(
            self._pump(
                job_id, account_id, proc, binary=binary, env=env, console=console,
                plain=plain, on_done=on_done,
            ),
            name=f"claude.login:{account_id}",
        )
        return job_id

    async def _pump(
        self, job_id: str, account_id: str, proc: Any, *, binary: str,
        env: Dict[str, str], console: bool, plain: bool,
        on_done: Optional[Callable[[bool], Awaitable[None]]],
    ) -> None:
        transcript: List[str] = []
        opened: set = set()

        async def read(stream: Any, name: str) -> None:
            while True:
                raw = await stream.readline()
                if not raw:
                    return
                text = raw.decode("utf-8", "replace")
                transcript.append(text)
                line = strip_ansi(text).rstrip()
                if line.strip():
                    self._emit({"jobId": job_id, "accountId": account_id, "type": "line",
                                "stream": name, "text": line})
                for url in find_urls(text):
                    if url in opened:
                        continue
                    opened.add(url)
                    self._emit({"jobId": job_id, "accountId": account_id,
                                "type": "url", "url": url})

        await asyncio.gather(read(proc.stdout, "stdout"), read(proc.stderr, "stderr"))
        code = await proc.wait()
        if self._jobs.get(job_id, {}).get("proc") is not proc:
            return  # cancelled or replaced
        self._jobs.pop(job_id, None)
        joined = "".join(transcript)
        if code != 0 and not plain and not console and re.search(
            r"unknown option|unknown argument|unexpected argument", joined, re.I
        ):
            await self.start(binary=binary, account_id=account_id, env=env,
                             console=console, on_done=on_done, job_id=job_id, plain=True)
            return
        ok = code == 0
        if on_done is not None:
            with contextlib.suppress(Exception):
                await on_done(ok)
        tail = " ".join(strip_ansi(joined).strip().split("\n")[-3:])[:400]
        self._emit({"jobId": job_id, "accountId": account_id, "type": "done",
                    "ok": ok, "error": None if ok else (tail or f"exit {code}")})

    def send_input(self, job_id: str, text: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        proc = job["proc"]
        if proc.stdin is None:
            return False
        try:
            proc.stdin.write(f"{text.strip()}\n".encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError):
            return False
        return True

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.pop(job_id, None)
        if not job:
            return False
        proc = job["proc"]
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        return True
