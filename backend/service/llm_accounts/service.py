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
from service.llm_accounts import claude_auth, codex_auth, single_use
from service.llm_accounts.kinds import (
    ACCOUNT_KINDS,
    EFFORTS,
    KINDS,
    default_model_for,
    model_choices,
)
from service.llm_accounts.secrets import SecretStore, get_secret_store

logger = logging.getLogger(__name__)

__all__ = ["AccountService", "get_account_service", "route_context_window"]


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


#: Capability flags an ACCOUNT may declare about its endpoint. Deliberately
#: short: these are the three that change whether a turn works at all, and a
#: flag nobody can explain in one line does not belong in a settings page.
#: Anything else stays the client class's business.
#: Executor clients whose constructor takes a ``capabilities`` declaration.
#: The OpenAI-compatible family and vLLM: one class each, serving endpoints
#: that have nothing in common behind the wire format.
CAPABILITY_AWARE_PROVIDERS: Tuple[str, ...] = ("custom", "local", "ollama", "lmstudio", "vllm")

DECLARABLE_CAPABILITIES: Tuple[str, ...] = (
    "supports_vision",
    "supports_tools",
    "supports_tool_choice",
    # No switch of its own: a gateway that takes an image the USER attached
    # and rejects the one a TOOL returned is a real quirk (hermes-agent
    # carries it for one vendor) whose symptom is a 400 nothing in the page
    # can explain. Declarable through the API so the escape hatch exists;
    # left off the page because it would sit there meaning nothing to almost
    # everyone who reads it.
    "supports_vision_tool_results",
)


_EFFECTIVE_CAPABILITIES: Dict[str, Dict[str, bool]] = {}


def effective_capabilities(kind: str) -> Dict[str, bool]:
    """What an account of this kind gets when it declares nothing itself.

    A kind's ``capabilities`` is a SPARSE override of the executor client
    class's own defaults, which makes it the wrong thing to draw a settings
    checkbox from: the OpenAI-compatible classes already say yes to tools, so
    a box drawn from the kind alone renders that as "off" and invites the user
    to turn on something already on — or to read the whole page as a lie.

    So the answer is the class's declaration with the kind's laid over it,
    asked of the library rather than remembered here, because a default
    copied into this file is one that goes stale the next release.
    """
    if kind in _EFFECTIVE_CAPABILITIES:
        return dict(_EFFECTIVE_CAPABILITIES[kind])
    info = KINDS.get(kind)
    resolved: Dict[str, bool] = {}
    if info is not None and info.engine_provider in CAPABILITY_AWARE_PROVIDERS:
        try:
            from geny_executor.llm_client.registry import ClientRegistry

            declared = ClientRegistry.get(info.engine_provider).capabilities
            resolved = {
                flag: bool(getattr(declared, flag))
                for flag in DECLARABLE_CAPABILITIES
                if hasattr(declared, flag)
            }
        except Exception as exc:  # noqa: BLE001 — a settings page, not a turn
            logger.info("could not read client defaults for %s: %s", kind, exc)
        resolved.update(_clean_capabilities(dict(info.capabilities)))
    _EFFECTIVE_CAPABILITIES[kind] = resolved
    return dict(resolved)


def _clean_capabilities(raw: Any) -> Dict[str, bool]:
    """Keep only the declarable flags, as real booleans.

    An allow-list rather than a pass-through because this value leaves the
    database and becomes constructor input to a client class: a stray key
    from an old row or a hand-edited API call should read as "not declared",
    never as a crash on the first turn after a restart.
    """
    if not isinstance(raw, dict):
        return {}
    return {k: bool(v) for k, v in raw.items() if k in DECLARABLE_CAPABILITIES}


def _clean_window(raw: Any) -> Optional[int]:
    """A positive integer, or ``None``. Zero and junk both mean "unset"."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _window_record(raw: Any) -> Dict[str, Any]:
    """The stored ``{"declared": int|None, "discovered": {model: int}}``."""
    data = raw if isinstance(raw, dict) else {}
    discovered = data.get("discovered")
    clean: Dict[str, int] = {}
    if isinstance(discovered, dict):
        for model, window in discovered.items():
            value = _clean_window(window)
            if value is not None:
                clean[str(model)] = value
    return {"declared": _clean_window(data.get("declared")), "discovered": clean}


def route_context_window(targets: List[Dict[str, Any]]) -> Optional[int]:
    """How much context a ROUTE can hold: the smallest of its hops.

    A route is one conversation that must be able to continue on any hop —
    that is what the fallbacks are for. Sizing to the primary means the
    failover, which happens exactly when things are already going wrong,
    walks into an overflow it cannot recover from.

    ``None`` when no hop knows its own window; the caller then keeps the
    library default and should say so rather than imply it measured it.
    """
    from geny_executor.llm_client.context_window import binding_context_window

    return binding_context_window(t.get("contextWindow") for t in (targets or []))


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
    #
    # ``AppDatabaseManager`` hands back MODEL objects, not dicts. Everything
    # above this line reads rows as mappings, so the conversion happens here,
    # once — a single boundary rather than an ``isinstance`` at every field
    # access. (Learned the hard way: the fake database in the tests returned
    # dicts, so the whole service passed its tests and failed on the first
    # real query in production.)

    @staticmethod
    def _as_row(record: Any) -> Dict[str, Any]:
        if isinstance(record, dict):
            return record
        return {k: v for k, v in vars(record).items() if not k.startswith("_")}

    def _rows(self) -> List[Dict[str, Any]]:
        rows = [self._as_row(r) for r in (self._db.find_all(LLMAccountModel, limit=500) or [])]
        return sorted(rows, key=lambda r: (r.get("sort_order") or 0, r.get("id") or 0))

    def _row(self, account_id: str) -> Optional[Dict[str, Any]]:
        found = self._db.find_by_condition(LLMAccountModel, {"account_id": account_id}, limit=1)
        return self._as_row(found[0]) if found else None

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
            "capabilities": _clean_capabilities(_json_loads(row.get("capabilities_json"), {})),
            "defaultCapabilities": effective_capabilities(kind),
            "contextWindow": _window_record(_json_loads(row.get("context_window_json"), {})),
            "createdAt": row.get("created_at"),
        }
        if kind == "claude_code":
            public["claude"] = {
                "authMethod": row.get("claude_auth_method") or "login",
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
            effort=str(payload.get("effort") or ""),
            identity_json="",
            models_json="",
            status_json="",
            capabilities_json=json.dumps(_clean_capabilities(payload.get("capabilities"))),
            context_window_json=json.dumps(
                {"declared": _clean_window(payload.get("contextWindow")), "discovered": {}}
            ),
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
        if "capabilities" in patch:
            model.capabilities_json = json.dumps(_clean_capabilities(patch["capabilities"]))
        if "contextWindow" in patch:
            # Only the DECLARED half is the operator's to set; what discovery
            # measured stays until discovery runs again.
            record = _window_record(_json_loads(model.context_window_json, {}))
            record["declared"] = _clean_window(patch["contextWindow"])
            model.context_window_json = json.dumps(record)
        claude = patch.get("claude") or {}
        if "authMethod" in claude:
            model.claude_auth_method = str(claude["authMethod"] or "login")
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
               models: Any = None, has_secret: Optional[bool] = None,
               windows: Optional[Dict[str, Any]] = None) -> None:
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
        if windows is not None:
            record = _window_record(_json_loads(model.context_window_json, {}))
            record["discovered"] = {
                str(k): v for k, v in (windows or {}).items() if _clean_window(v)
            }
            model.context_window_json = json.dumps(record)
        if has_secret is not None:
            model.has_secret = bool(has_secret)
        self._db.update(model)

    # ── credentials for one account ──────────────────────────────────
    def secret_of(self, account_id: str) -> str:
        return self._secrets.get_str(account_id)

    def codex_tokens(self, account_id: str) -> Dict[str, Any]:
        return self._secrets.get_dict(account_id)

    def claude_options(self, account_id: str, *, label: str = "") -> Dict[str, Any]:
        """Everything ``geny_claude_code`` needs to drive THIS account.

        Synchronous on purpose, and shared with :meth:`resolve_hop` so
        there is one definition of what a Claude Code account is. The
        sync half matters: offline work (memory curation) needs these
        options but must not drive an async hop — every caller there
        sits inside a running event loop.
        """
        row = self._row(account_id) or {}
        method = row.get("claude_auth_method") or "login"
        options: Dict[str, Any] = {
            "binary_path": claude_auth.claude_binary(),
            "auth_method": method,
            "config_dir": self.claude_config_dir(account_id),
            "scratch_dir": self.claude_scratch_dir(account_id),
            "account_label": label or row.get("label") or "",
        }
        if method == "token":
            options["oauth_token"] = self._secrets.get_str(account_id)
        elif method == "api_key":
            options["anthropic_api_key"] = self._secrets.get_str(account_id)
        return options

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
    async def _fresh_single_use_tokens(self, account_id: str) -> Dict[str, Any]:
        """Codex tokens, refreshed if due — without ever spending one twice.

        A Codex refresh token is revoked the moment it is redeemed, so the
        read, the POST and the write-back have to be one atomic step against
        every other turn AND every other Geny process sharing the secret
        file. Without that, two turns starting together both read the same
        token, both POST it, and the loser's ``invalid_grant`` locks the
        account out until someone signs in again.

        The order is the only one that is safe:

          1. take the cross-process lock;
          2. re-read the store INSIDE it — a waiter finds the winner's fresh
             token here and returns without POSTing at all;
          3. refuse to POST a token already known spent;
          4. POST, then write back;
          5. if the write-back fails, say so and remember the fingerprint,
             because the old pair is dead server-side and replaying it is
             what turns a transient disk error into a lost account.
        """
        store_path = getattr(self._secrets, "path", None)
        # What we believe before queuing for the lock. A waiter compares
        # against this: if it changed while we waited, the holder did the
        # refresh and there is nothing left to redeem.
        before = self._secrets.get_dict(account_id).get("refresh_token")

        async with single_use.refresh_guard(store_path):
            self._secrets.reload()
            tokens = self._secrets.get_dict(account_id)
            if not tokens:
                return {}

            refresh_token = tokens.get("refresh_token")
            if before and refresh_token and refresh_token != before:
                # Someone rotated while we waited. Their token is new by
                # definition, so redeeming again would spend a good one for
                # nothing — and on a bad day spend the same one twice.
                logger.debug(
                    "codex account %s was refreshed by another holder", account_id
                )
                return tokens

            if single_use.is_spent(refresh_token, store_path=store_path):
                # Redeemed once already with no replacement stored. POSTing it
                # again only confirms the loss; hand the hop over and let the
                # wire report an auth failure the router can fail over from.
                logger.error(
                    "codex account %s holds a refresh token that was already "
                    "consumed — sign in again to restore it", account_id,
                )
                return tokens

            try:
                fresh, refreshed = await codex_auth.ensure_fresh(tokens)
            except ValueError as exc:
                # A dead refresh token is an auth failure the router can fail
                # over from — hand the hop over with what we have.
                logger.warning("codex refresh failed for %s: %s", account_id, exc)
                return tokens

            if not refreshed:
                return fresh

            try:
                self._secrets.set(account_id, fresh)
            except OSError as exc:
                single_use.mark_spent(refresh_token, store_path=store_path)
                raise single_use.CredentialPersistError(store_path, exc) from exc

            self._stamp(account_id, identity=codex_auth.identity_of(fresh))
            return fresh

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
        if not model:
            # No catalogue, no discovery, nothing typed: the hop would go out
            # with an empty model id and come back as whatever each vendor
            # says about that. Dropping it makes the route degrade to its next
            # hop, which is the behaviour every other unusable account gets.
            logger.info("account %s (%s) has no model yet — hop dropped", account_id, kind)
            return None
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

        # What this endpoint serves. The kind's declaration is the default
        # (OpenRouter fronts vision models; a bare compatible endpoint is
        # assumed not to), and the account overrides it, because the two
        # kinds that need this most — ``openai_compatible`` and ``vllm`` —
        # are exactly the ones where only the operator knows what is loaded.
        # Sent only to the clients that take the kwarg: the vendor clients
        # (anthropic / openai / google / the two subscription ones) have no
        # ambiguity to resolve and would reject an unexpected argument.
        window = self.context_window_of(account_id, model)
        if window:
            # Read by the session to size compaction, not by the client — the
            # wire has no field for it.
            target["contextWindow"] = window

        if info.engine_provider in CAPABILITY_AWARE_PROVIDERS:
            declared = {
                **info.capabilities,
                **_clean_capabilities(_json_loads(row.get("capabilities_json"), {})),
            }
            if declared:
                target["options"]["capabilities"] = declared

        if kind == "claude_code":
            # There is no second mode. A Claude Code account generates
            # tokens; this harness runs the tools. The "agent" mode that
            # handed the loop back to the CLI is gone (2026-09-19) — an
            # account is a model, and a model that runs its own tools
            # cannot share a conversation, a permission ladder or a
            # memory with the rest of them. Rows that still say "agent"
            # are simply read as token accounts.
            target["options"].update(
                self.claude_options(account_id, label=target["label"])
            )
        elif kind == "codex":
            # The guarded path is chosen by the CLASSIFICATION, not by this
            # branch knowing it is Codex: adding another rotating kind is one
            # edit, in the set that documents why the guard exists.
            tokens = (
                await self._fresh_single_use_tokens(account_id)
                if kind in single_use.SINGLE_USE_REFRESH_KINDS
                else self._secrets.get_dict(account_id)
            )
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
            # Two ways a hop resolves to nothing, and telling the user the
            # wrong one sends them to the wrong switch.
            reason = (
                "계정이 꺼져 있습니다"
                if not row.get("enabled", True)
                else "쓸 모델이 없습니다 — [모델 목록 새로고침] 을 눌러 주세요"
            )
            return {"ok": False, "latencyMs": 0, "error": reason}
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
        models = [m for m in (found.models if found else []) if getattr(m, "id", "")]
        ids = [m.id for m in models]
        # The endpoints that state their window are exactly the ones whose
        # window we could not otherwise know — an aggregator routing to
        # hundreds of models, a vLLM server running at whatever length it was
        # launched with. Recording it here is what lets a session size its
        # compaction to the model instead of to a 200k assumption.
        windows = {
            m.id: getattr(m, "context_window", None)
            for m in models
            if getattr(m, "context_window", None)
        }
        self._stamp(account_id, models=ids, windows=windows or {})
        return ids

    # ── how much context this account's models hold ──────────────────
    def context_window_of(self, account_id: str, model: str) -> Optional[int]:
        """The resolved window for one ``(account, model)``, or ``None``.

        Resolution order is the library's: what the operator declared, then
        what the endpoint said, then what is known about the model family.
        ``None`` means nobody knows — which the caller should say out loud
        rather than silently assume 200k for.
        """
        from geny_executor.llm_client.context_window import resolve_context_window

        row = self._row(account_id)
        if not row:
            return None
        info = KINDS.get(row.get("kind") or "")
        record = _window_record(_json_loads(row.get("context_window_json"), {}))
        return resolve_context_window(
            declared=record.get("declared"),
            discovered=record["discovered"].get(model),
            model=model,
            provider=info.engine_provider if info else "",
        )


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
