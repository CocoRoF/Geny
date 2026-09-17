"""Every way this server can reach a model, and how a route becomes a call.

An **account** is one credential: a Claude Code login, a second Claude Code
login, a ChatGPT (Codex) login, an API key, a local server. A **route** is
what a session uses — a primary ``(account, model)`` and ordered fallbacks.

The pipeline always names one provider, ``geny_router``; this service turns
a route into the targets that provider resolves per call. That is what makes
switching model mid-conversation cheap: the history stays canonical, so the
next turn simply goes to a different account with the same tools, memory,
hooks and permission policy.

Accounts live in the database (non-secret config) and the secret store
(keys, setup tokens, Codex token sets). A Claude ``login`` account also owns
``<accounts-root>/claude/<id>/`` as its ``CLAUDE_CONFIG_DIR``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from service.database.models.llm_account import LLMAccountModel
from service.llm_accounts import claude_auth, codex_auth
from service.llm_accounts.kinds import (
    ACCOUNT_KINDS,
    EFFORTS,
    KINDS,
    default_model_for,
    model_choices,
)
from service.llm_accounts.secrets import SecretStore, get_secret_store

logger = logging.getLogger(__name__)

__all__ = ["AccountService", "get_account_service"]


def accounts_root() -> Path:
    env = (os.environ.get("GENY_LLM_ACCOUNTS_ROOT") or "").strip()
    return Path(env) if env else Path.home() / ".geny" / "accounts"


def _json_loads(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


class _EventBus:
    """Login events fanned out to every listening UI.

    A login is watched from wherever the user started it — the web settings
    page, the connector, sometimes both — so the bus is a broadcast, not a
    queue: a slow listener drops frames instead of stalling the flow, since
    the ``done`` frame is also reflected in the account row.
    """

    def __init__(self, history: int = 200) -> None:
        self._queues: Set[asyncio.Queue] = set()
        self._recent: List[Dict[str, Any]] = []
        self._history = history
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        with self._lock:
            self._queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._queues.discard(queue)

    def publish(self, event: Dict[str, Any]) -> None:
        stamped = {**event, "ts": int(time.time() * 1000)}
        with self._lock:
            self._recent.append(stamped)
            del self._recent[: max(0, len(self._recent) - self._history)]
            queues = list(self._queues)
        for queue in queues:
            try:
                queue.put_nowait(stamped)
            except asyncio.QueueFull:
                logger.debug("llm account event dropped for a slow listener")

    def replay(self, job_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            events = list(self._recent)
        return [e for e in events if not job_id or e.get("jobId") == job_id]


class AccountService:
    """CRUD over accounts, the login flows, and route resolution."""

    def __init__(self, app_db: Any, secrets: Optional[SecretStore] = None) -> None:
        self._db = app_db
        self._secrets = secrets or get_secret_store()
        self.events = _EventBus()
        self._claude_jobs = claude_auth.LoginJobs(self.events.publish)
        self._codex_jobs = codex_auth.DeviceLoginJobs(self.events.publish)
        self._cli_cache: Optional[Dict[str, Any]] = None

    # ── paths ────────────────────────────────────────────────────────
    def claude_config_dir(self, account_id: str) -> str:
        return str(accounts_root() / "claude" / account_id / "config")

    def claude_scratch_dir(self, account_id: str) -> str:
        return str(accounts_root() / "claude" / account_id / "scratch")

    # ── storage ──────────────────────────────────────────────────────
    def _rows(self) -> List[Dict[str, Any]]:
        rows = self._db.find_all(LLMAccountModel, limit=500) or []
        return sorted(rows, key=lambda r: (r.get("sort_order") or 0, r.get("id") or 0))

    def _row(self, account_id: str) -> Optional[Dict[str, Any]]:
        found = self._db.find_by_condition(LLMAccountModel, {"account_id": account_id}, limit=1)
        return found[0] if found else None

    def _to_public(self, row: Dict[str, Any]) -> Dict[str, Any]:
        kind = row.get("kind") or ""
        info = KINDS.get(kind)
        discovered = _json_loads(row.get("models_json"), [])
        account_id = row.get("account_id") or ""
        public: Dict[str, Any] = {
            "id": account_id,
            "kind": kind,
            "label": row.get("label") or (info.short if info else kind),
            "enabled": bool(row.get("enabled", True)),
            "baseUrl": row.get("base_url") or "",
            "effort": row.get("effort") or "",
            "identity": _json_loads(row.get("identity_json"), {}) or {},
            "status": _json_loads(row.get("status_json"), {}) or {},
            "models": discovered if isinstance(discovered, list) else [],
            "modelChoices": model_choices(kind, discovered if isinstance(discovered, list) else []),
            "hasSecret": bool(row.get("has_secret")),
            "engineProvider": info.engine_provider if info else "",
            "createdAt": row.get("created_at"),
        }
        if kind == "claude_code":
            public["claude"] = {
                "authMethod": row.get("claude_auth_method") or "login",
                "mode": row.get("claude_mode") or "token",
            }
            public["configDir"] = self.claude_config_dir(account_id)
        return public

    def list_accounts(self) -> List[Dict[str, Any]]:
        return [self._to_public(r) for r in self._rows()]

    def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        row = self._row(account_id)
        return self._to_public(row) if row else None

    def create_account(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        kind = str(payload.get("kind") or "").strip()
        if kind not in KINDS:
            raise ValueError(f"알 수 없는 계정 종류입니다: {kind or '(없음)'}")
        info = KINDS[kind]
        base_url = str(payload.get("baseUrl") or "").strip() or info.default_base_url
        if info.needs_base_url and not base_url:
            raise ValueError(f"{info.label} 계정에는 주소(base URL)가 필요합니다")
        secret = str(payload.get("secret") or "").strip()
        if info.secret == "api_key" and not secret:
            raise ValueError(f"{info.label} 계정에는 API 키가 필요합니다")

        account_id = uuid.uuid4().hex[:16]
        claude = payload.get("claude") or {}
        existing = len(self._rows())
        model = LLMAccountModel(
            account_id=account_id,
            kind=kind,
            label=str(payload.get("label") or "").strip() or self._auto_label(kind),
            enabled=True,
            base_url=base_url,
            claude_auth_method=str(claude.get("authMethod") or "login"),
            claude_mode=str(claude.get("mode") or "token"),
            effort=str(payload.get("effort") or ""),
            identity_json="",
            models_json="",
            status_json="",
            has_secret=bool(secret),
            sort_order=existing,
        )
        self._db.insert(model)
        if secret:
            self._secrets.set(account_id, secret)
        return self.get_account(account_id) or {}

    def _auto_label(self, kind: str) -> str:
        info = KINDS.get(kind)
        base = info.short if info else kind
        used = {r.get("label") for r in self._rows()}
        if base not in used:
            return base
        for n in range(2, 100):
            candidate = f"{base} {n}"
            if candidate not in used:
                return candidate
        return f"{base} {uuid.uuid4().hex[:4]}"

    def update_account(self, account_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        row = self._row(account_id)
        if not row:
            raise KeyError(account_id)
        model = LLMAccountModel.from_dict(dict(row))
        if "label" in patch:
            model.label = str(patch["label"] or "").strip() or model.label
        if "enabled" in patch:
            model.enabled = bool(patch["enabled"])
        if "baseUrl" in patch:
            model.base_url = str(patch["baseUrl"] or "").strip()
        if "effort" in patch:
            effort = str(patch["effort"] or "").strip()
            if effort and effort not in EFFORTS:
                raise ValueError(f"알 수 없는 추론 강도입니다: {effort}")
            model.effort = effort
        claude = patch.get("claude") or {}
        if "authMethod" in claude:
            model.claude_auth_method = str(claude["authMethod"] or "login")
        if "mode" in claude:
            model.claude_mode = str(claude["mode"] or "token")
        if "secret" in patch:
            secret = str(patch["secret"] or "").strip()
            self._secrets.set(account_id, secret or None)
            model.has_secret = bool(secret)
        self._db.update(model)
        return self.get_account(account_id) or {}

    def delete_account(self, account_id: str) -> bool:
        row = self._row(account_id)
        if not row:
            return False
        self._secrets.delete(account_id)
        # The CLI keeps a whole credential directory per login account; leaving
        # it behind would quietly re-authenticate a recreated account with the
        # deleted one's identity.
        shutil.rmtree(accounts_root() / "claude" / account_id, ignore_errors=True)
        return bool(self._db.delete(LLMAccountModel, row.get("id")))

    def reorder(self, account_ids: List[str]) -> List[Dict[str, Any]]:
        order = {aid: i for i, aid in enumerate(account_ids)}
        for row in self._rows():
            aid = row.get("account_id")
            if aid in order and (row.get("sort_order") or 0) != order[aid]:
                model = LLMAccountModel.from_dict(dict(row))
                model.sort_order = order[aid]
                self._db.update(model)
        return self.list_accounts()

    # ── observed state ───────────────────────────────────────────────
    def _stamp(self, account_id: str, *, identity: Any = None, status: Any = None,
               models: Any = None, has_secret: Optional[bool] = None) -> None:
        row = self._row(account_id)
        if not row:
            return
        model = LLMAccountModel.from_dict(dict(row))
        if identity is not None:
            model.identity_json = json.dumps(identity, ensure_ascii=False)
        if status is not None:
            model.status_json = json.dumps(status, ensure_ascii=False)
        if models is not None:
            model.models_json = json.dumps(models, ensure_ascii=False)
        if has_secret is not None:
            model.has_secret = bool(has_secret)
        self._db.update(model)

    # ── credentials for one account ──────────────────────────────────
    def secret_of(self, account_id: str) -> str:
        return self._secrets.get_str(account_id)

    def codex_tokens(self, account_id: str) -> Dict[str, Any]:
        return self._secrets.get_dict(account_id)

    def claude_env(self, row: Dict[str, Any]) -> Dict[str, str]:
        account_id = row.get("account_id") or ""
        method = row.get("claude_auth_method") or "login"
        return claude_auth.account_env(
            auth_method=method,
            config_dir=self.claude_config_dir(account_id),
            oauth_token=self._secrets.get_str(account_id) if method == "token" else None,
            api_key=self._secrets.get_str(account_id) if method == "api_key" else None,
        )

    # ── route resolution ─────────────────────────────────────────────
    async def resolve_route(self, route: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Turn a stored route into the hops ``geny_router`` resolves per call.

        Disabled accounts and accounts that no longer exist are dropped
        rather than raising: a route outlives the accounts it names, and a
        conversation should degrade to its next hop, not stop.
        """
        refs: List[Dict[str, Any]] = []
        primary = route.get("primary")
        if isinstance(primary, dict):
            refs.append(primary)
        for hop in route.get("fallbacks") or []:
            if isinstance(hop, dict):
                refs.append(hop)

        targets: List[Dict[str, Any]] = []
        for ref in refs:
            target = await self.resolve_hop(ref)
            if target is not None:
                targets.append(target)
        return targets

    async def resolve_hop(self, ref: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        account_id = str(ref.get("accountId") or "")
        row = self._row(account_id)
        if not row or not row.get("enabled", True):
            return None
        kind = row.get("kind") or ""
        info = KINDS.get(kind)
        if info is None:
            return None
        discovered = _json_loads(row.get("models_json"), [])
        model = str(ref.get("model") or "").strip() or default_model_for(
            kind, discovered if isinstance(discovered, list) else []
        )
        effort = str(ref.get("effort") or row.get("effort") or "").strip()

        target: Dict[str, Any] = {
            "accountId": account_id,
            "label": row.get("label") or info.short,
            "kind": kind,
            "engineProvider": info.engine_provider,
            "model": model,
            "options": {},
        }
        if row.get("base_url"):
            target["baseUrl"] = row["base_url"]
        if effort:
            target["options"]["effort"] = effort

        if kind == "claude_code":
            method = row.get("claude_auth_method") or "login"
            if (row.get("claude_mode") or "token") == "agent":
                # The CLI runs its own loop. Kept for the rare task that wants
                # Claude Code's native tools; the harness then only sees the
                # announcement, so it is not the default.
                target["engineProvider"] = "claude_code_cli"
            target["options"].update({
                "binary_path": claude_auth.claude_binary(),
                "auth_method": method,
                "config_dir": self.claude_config_dir(account_id),
                "scratch_dir": self.claude_scratch_dir(account_id),
                "account_label": target["label"],
            })
            if method == "token":
                target["options"]["oauth_token"] = self._secrets.get_str(account_id)
            elif method == "api_key":
                target["options"]["anthropic_api_key"] = self._secrets.get_str(account_id)
        elif kind == "codex":
            tokens = self._secrets.get_dict(account_id)
            if tokens:
                try:
                    tokens, refreshed = await codex_auth.ensure_fresh(tokens)
                    if refreshed:
                        self._secrets.set(account_id, tokens)
                        self._stamp(account_id, identity=codex_auth.identity_of(tokens))
                except ValueError as exc:
                    # A dead refresh token is an auth failure the router can
                    # fail over from — hand the hop over with what we have and
                    # let the wire report it.
                    logger.warning("codex refresh failed for %s: %s", account_id, exc)
            target["options"].update({
                "tokens": tokens,
                "account_label": target["label"],
            })
            target["baseUrl"] = row.get("base_url") or codex_auth.BASE_URL
        else:
            secret = self._secrets.get_str(account_id)
            if secret:
                target["apiKey"] = secret
        return target

    def default_route(self) -> Dict[str, Any]:
        """The route a new session gets: the first enabled account, then the
        rest as fallbacks, in the order the user arranged them."""
        enabled = [r for r in self._rows() if r.get("enabled", True)]
        if not enabled:
            return {"primary": None, "fallbacks": []}

        def ref(row: Dict[str, Any]) -> Dict[str, Any]:
            discovered = _json_loads(row.get("models_json"), [])
            return {
                "accountId": row.get("account_id"),
                "model": default_model_for(
                    row.get("kind") or "", discovered if isinstance(discovered, list) else []
                ),
            }

        return {"primary": ref(enabled[0]), "fallbacks": [ref(r) for r in enabled[1:]]}

    # ── Claude Code login ────────────────────────────────────────────
    async def cli_info(self, refresh: bool = False) -> Dict[str, Any]:
        if self._cli_cache is None or refresh:
            self._cli_cache = await claude_auth.probe()
        return self._cli_cache

    async def claude_status(self, account_id: str) -> Dict[str, Any]:
        row = self._row(account_id)
        if not row:
            raise KeyError(account_id)
        cli = await self.cli_info()
        if not cli["found"]:
            return {"loggedIn": False, "error": "claude CLI 를 찾을 수 없습니다", "cli": cli}
        result = await claude_auth.status(cli["path"], self.claude_env(row))
        result["cli"] = cli
        identity = {k: result.get(k) for k in ("email", "organization", "subscription")}
        self._stamp(account_id, identity={k: v for k, v in identity.items() if v})
        return result

    async def start_claude_login(self, account_id: str, *, console: bool = False) -> Dict[str, Any]:
        row = self._row(account_id)
        if not row:
            raise KeyError(account_id)
        if (row.get("kind") or "") != "claude_code":
            raise ValueError("Claude Code 계정에서만 쓸 수 있습니다")
        cli = await self.cli_info(refresh=True)
        if not cli["found"]:
            raise ValueError("claude CLI 를 찾을 수 없습니다 — 서버에 Claude Code 를 설치하세요")
        # A login writes into this account's own directory, never the
        # operator's ~/.claude.
        env = claude_auth.account_env(
            auth_method="login", config_dir=self.claude_config_dir(account_id)
        )

        async def on_done(ok: bool) -> None:
            if not ok:
                return
            self.update_account(account_id, {"claude": {"authMethod": "login"}})
            with_status = await self.claude_status(account_id)
            self._stamp(account_id, status={
                "ok": bool(with_status.get("loggedIn")),
                "checkedAt": int(time.time() * 1000),
                "detail": with_status.get("email") or with_status.get("method") or "",
            })

        job_id = await self._claude_jobs.start(
            binary=cli["path"], account_id=account_id, env=env,
            console=console, on_done=on_done,
        )
        return {"jobId": job_id}

    def send_login_input(self, job_id: str, text: str) -> bool:
        return self._claude_jobs.send_input(job_id, text)

    def cancel_login(self, job_id: str) -> bool:
        return self._claude_jobs.cancel(job_id) or self._codex_jobs.cancel(job_id)

    async def claude_logout(self, account_id: str) -> bool:
        row = self._row(account_id)
        if not row:
            raise KeyError(account_id)
        cli = await self.cli_info()
        ok = cli["found"] and await claude_auth.logout(cli["path"], self.claude_env(row))
        self._stamp(account_id, identity={}, status={
            "ok": False, "checkedAt": int(time.time() * 1000), "detail": "로그아웃됨",
        })
        return ok

    # ── Codex login ──────────────────────────────────────────────────
    async def start_codex_login(self, account_id: str) -> Dict[str, Any]:
        row = self._row(account_id)
        if not row:
            raise KeyError(account_id)
        if (row.get("kind") or "") != "codex":
            raise ValueError("Codex 계정에서만 쓸 수 있습니다")

        async def on_tokens(tokens: Dict[str, Any]) -> None:
            self._secrets.set(account_id, tokens)
            identity = codex_auth.identity_of(tokens)
            self._stamp(account_id, identity=identity, has_secret=True, status={
                "ok": True, "checkedAt": int(time.time() * 1000),
                "detail": identity.get("email") or identity.get("plan") or "",
            })

        return await self._codex_jobs.start(account_id, on_tokens)

    def import_codex_cli_login(self, account_id: str) -> bool:
        """Adopt an existing ``~/.codex/auth.json`` on this machine.

        A copy, not a share: the refresh token is single-use, so two holders
        of the same one rotate each other out.
        """
        row = self._row(account_id)
        if not row:
            raise KeyError(account_id)
        home = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
        path = Path(home) / "auth.json"
        if not path.exists():
            return False
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        tokens = raw.get("tokens") if isinstance(raw, dict) else None
        if not isinstance(tokens, dict) or not tokens.get("access_token"):
            return False
        self._secrets.set(account_id, tokens)
        identity = codex_auth.identity_of(tokens)
        self._stamp(account_id, identity=identity, has_secret=True, status={
            "ok": True, "checkedAt": int(time.time() * 1000),
            "detail": identity.get("email") or "가져옴",
        })
        return True

    # ── liveness ─────────────────────────────────────────────────────
    async def test_account(self, account_id: str, model: Optional[str] = None) -> Dict[str, Any]:
        """One real generation — the only honest answer to "does this work".

        ``auth status`` reports a logged-in account whose plan has lapsed as
        fine, and an API key that was rotated yesterday as present.
        """
        row = self._row(account_id)
        if not row:
            raise KeyError(account_id)
        kind = row.get("kind") or ""
        discovered = _json_loads(row.get("models_json"), [])
        chosen = model or default_model_for(kind, discovered if isinstance(discovered, list) else [])
        started = time.monotonic()
        try:
            if kind == "claude_code":
                cli = await self.cli_info()
                if not cli["found"]:
                    result = {"ok": False, "latencyMs": 0, "error": "claude CLI 를 찾을 수 없습니다"}
                else:
                    result = await claude_auth.smoke_test(
                        cli["path"], self.claude_env(row), chosen,
                        self.claude_scratch_dir(account_id),
                    )
            else:
                result = await self._test_through_client(row, chosen)
        except Exception as exc:  # noqa: BLE001 — a test reports, never raises
            result = {"ok": False, "latencyMs": int((time.monotonic() - started) * 1000),
                      "error": str(exc)[:400]}
        self._stamp(account_id, status={
            "ok": bool(result.get("ok")),
            "checkedAt": int(time.time() * 1000),
            "detail": result.get("error") or result.get("reply") or "",
        })
        return result

    async def _test_through_client(self, row: Dict[str, Any], model: str) -> Dict[str, Any]:
        """Build the same client a turn would and ask it for one word."""
        from geny_executor.core.config import ModelConfig
        from geny_executor.llm_client.router import build_client

        target = await self.resolve_hop({"accountId": row.get("account_id"), "model": model})
        if target is None:
            return {"ok": False, "latencyMs": 0, "error": "계정이 꺼져 있습니다"}
        started = time.monotonic()
        client = build_client(target, notify=None, session_id=None, timeout_s=90.0)
        try:
            response = await client.create_message(
                model_config=ModelConfig(model=model, max_tokens=64),
                messages=[{"role": "user", "content": "ping"}],
                system="You are a connectivity probe. Answer with the single word OK.",
            )
        finally:
            closer = getattr(client, "aclose", None)
            if callable(closer):
                await closer()
        latency_ms = int((time.monotonic() - started) * 1000)
        text = "".join(b.text or "" for b in response.content if b.type == "text")
        return {"ok": True, "latencyMs": latency_ms, "reply": text[:200], "model": response.model or model}

    async def discover_models(self, account_id: str) -> List[str]:
        """Ask the provider what it serves. Subscription backends have no such
        endpoint, so their catalogue stays the static one."""
        row = self._row(account_id)
        if not row:
            raise KeyError(account_id)
        kind = row.get("kind") or ""
        if kind in ("claude_code", "codex"):
            return []
        try:
            from geny_executor.llm_client.model_discovery import discover_models as _discover
        except ImportError:
            return []
        info = KINDS.get(kind)
        try:
            found = await _discover(
                info.engine_provider if info else kind,
                api_key=self._secrets.get_str(account_id),
                base_url=row.get("base_url") or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("model discovery failed for %s: %s", account_id, exc)
            return []
        ids = [m.id for m in (found.models if found else []) if getattr(m, "id", "")]
        self._stamp(account_id, models=ids)
        return ids


_service: Optional[AccountService] = None
_service_lock = threading.Lock()


def get_account_service(app_db: Any = None) -> AccountService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                if app_db is None:
                    from service.database import AppDatabaseManager, database_config
                    app_db = AppDatabaseManager(database_config)
                    app_db.initialize_connection()
                _service = AccountService(app_db)
    return _service
