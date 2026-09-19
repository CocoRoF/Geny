"""A single-use refresh token must never be spent twice.

Codex revokes the refresh token the moment it is redeemed. Three ordinary
situations turn that into a permanent lockout, and each one has a test here:

  * two turns refresh the same account at once — the loser replays a dead
    token and the account is out until someone signs in again;
  * two PROCESSES do, sharing the secret file, where no in-process lock helps;
  * the POST succeeds but the write-back fails, leaving a pair that is dead
    server-side on disk, replayed forever after.

The fix is the order, not the lock alone: re-read INSIDE the lock, so a
waiter finds the winner's fresh token and never POSTs at all.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict

import pytest

from service.llm_accounts import single_use


class _Store:
    """A SecretStore stand-in backed by a real file, so two instances see
    each other exactly as two processes would."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._cache: Dict[str, Any] | None = None
        self.writes = 0
        self.fail_write = False

    def reload(self) -> None:
        self._cache = None

    def _load(self) -> Dict[str, Any]:
        if self._cache is None:
            try:
                self._cache = json.loads(self.path.read_text())
            except OSError:
                self._cache = {}
        return self._cache

    def get_dict(self, account_id: str) -> Dict[str, Any]:
        return dict(self._load().get(account_id) or {})

    def set(self, account_id: str, value: Any) -> None:
        if self.fail_write:
            raise OSError("disk full")
        data = dict(self._load())
        data[account_id] = value
        self.path.write_text(json.dumps(data))
        self._cache = data
        self.writes += 1


class _Service:
    """Just the method under test, with its two collaborators stubbed."""

    def __init__(self, store: _Store, refresher) -> None:
        self._secrets = store
        self._refresher = refresher
        self.stamped = 0

    def _stamp(self, account_id: str, **kw: Any) -> None:
        self.stamped += 1

    async def _fresh_single_use_tokens(self, account_id: str) -> Dict[str, Any]:
        from service.llm_accounts.service import AccountService

        return await AccountService._fresh_single_use_tokens(self, account_id)


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "llm_accounts.json"
    path.write_text(json.dumps({"acct": {"refresh_token": "r1", "access_token": "a1"}}))
    # a fresh spent-registry per test
    monkeypatch.setattr(single_use, "_SPENT", single_use.OrderedDict())
    return _Store(path)


def _refresher(calls: list, *, stale: str = "r1", new: str = "r2", hold_s: float = 0.0):
    """A refresher that behaves like the real one: it only redeems a token
    that is actually due, and it takes time, because the lock is held across
    an HTTPS round trip and that is where a second turn piles up."""

    async def ensure_fresh(tokens, **_kw):
        token = tokens.get("refresh_token")
        if token != stale:
            return tokens, False          # not due — the real skew check
        if hold_s:
            await asyncio.sleep(hold_s)   # the POST, and the window it opens
        calls.append(token)
        return {"refresh_token": new, "access_token": f"a-{new}"}, True

    return ensure_fresh


def _patch(monkeypatch, fn):
    from service.llm_accounts import service as svc_mod

    monkeypatch.setattr(svc_mod.codex_auth, "ensure_fresh", fn)
    monkeypatch.setattr(svc_mod.codex_auth, "identity_of", lambda t: {})


class TestOneRedemption:
    def test_two_concurrent_turns_redeem_the_token_once(self, store, monkeypatch):
        """THE bug: without the in-lock re-read both turns POST `r1`, and the
        loser is told `invalid_grant` on a token it had every reason to think
        was good."""
        calls: list = []
        _patch(monkeypatch, _refresher(calls, hold_s=0.05))
        svc = _Service(store, None)

        async def run():
            return await asyncio.gather(
                svc._fresh_single_use_tokens("acct"),
                svc._fresh_single_use_tokens("acct"),
            )

        first, second = asyncio.run(run())
        assert calls == ["r1"], f"the token was POSTed {len(calls)} times: {calls}"
        assert first["refresh_token"] == second["refresh_token"] == "r2"

    def test_a_second_process_sees_the_rotation_and_skips_the_post(
        self, store, monkeypatch, tmp_path
    ):
        """Two processes share the file; the second must re-read inside the
        lock rather than trust what it loaded before."""
        calls: list = []
        _patch(monkeypatch, _refresher(calls))
        svc_a = _Service(store, None)
        asyncio.run(svc_a._fresh_single_use_tokens("acct"))
        assert calls == ["r1"]

        # a genuinely separate store object — a different process
        other = _Store(tmp_path / "llm_accounts.json")
        other.get_dict("acct")  # warm its cache with the pre-rotation view
        svc_b = _Service(other, None)
        tokens = asyncio.run(svc_b._fresh_single_use_tokens("acct"))

        assert calls == ["r1"], "the second process replayed a spent token"
        assert tokens["refresh_token"] == "r2"


class TestAFailedWriteBackIsNotSwallowed:
    def test_it_raises_rather_than_stranding_the_account(self, store, monkeypatch):
        calls: list = []
        _patch(monkeypatch, _refresher(calls))
        store.fail_write = True
        svc = _Service(store, None)

        with pytest.raises(single_use.CredentialPersistError):
            asyncio.run(svc._fresh_single_use_tokens("acct"))

    def test_the_spent_token_is_remembered_so_nothing_replays_it(
        self, store, monkeypatch
    ):
        calls: list = []
        _patch(monkeypatch, _refresher(calls))
        store.fail_write = True
        svc = _Service(store, None)
        with pytest.raises(single_use.CredentialPersistError):
            asyncio.run(svc._fresh_single_use_tokens("acct"))

        assert single_use.is_spent("r1", store_path=store.path)

        # the next attempt must NOT POST it again
        store.fail_write = False
        calls.clear()
        tokens = asyncio.run(svc._fresh_single_use_tokens("acct"))
        assert calls == [], "a token known spent was redeemed again"
        assert tokens["refresh_token"] == "r1"

    def test_the_sidecar_carries_no_secret(self, store, monkeypatch):
        single_use.mark_spent("super-secret-token", store_path=store.path)
        text = (store.path.with_name(store.path.name + ".spent-rotations.json")).read_text()
        assert "super-secret-token" not in text
        assert single_use.fingerprint("super-secret-token") in text


class TestClassification:
    def test_codex_rotates_and_claude_code_does_not(self) -> None:
        """claude_code's login is a config dir the CLI owns and rotates
        itself — Geny never POSTs a refresh for it, so it is not in the set."""
        assert "codex" in single_use.SINGLE_USE_REFRESH_KINDS
        assert "claude_code" not in single_use.SINGLE_USE_REFRESH_KINDS

    def test_the_set_is_what_selects_the_guarded_path(self) -> None:
        """Not decoration: resolve_hop consults it. A set nothing reads is a
        comment that looks like a rule, and the next rotating provider would
        be added to it and still go unguarded."""
        import inspect

        from service.llm_accounts.service import AccountService

        source = inspect.getsource(AccountService.resolve_hop)
        assert "SINGLE_USE_REFRESH_KINDS" in source


class TestTheLockDegradesRatherThanBlocks:
    def test_no_store_path_still_refreshes(self, monkeypatch) -> None:
        async def go():
            async with single_use.refresh_guard(None) as held:
                return held

        assert asyncio.run(go()) is False
