"""The one account: rotating its password, and surviving being guessed at.

A single-admin service on a public host has one username — usually the
obvious one — and one password. Two things follow, and neither was true
before:

* The password has to be changeable, and changing it has to REVOKE. A
  rotation that leaves every other device signed in has revoked nothing; a
  stolen 30-day token would outlive the change by a month.
* Login attempts have to cost something. bcrypt at 12 rounds makes each guess
  expensive for the server too, which is why the answer is to answer slower
  and then stop answering, not to hash harder.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import bcrypt
import jwt
import pytest

from service.auth.auth_service import AuthService, LoginThrottle, TooManyAttempts


class _FakeDb:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    def find_all(self, model_class: Any) -> List[Dict[str, Any]]:
        return list(self.rows)

    def find_by_condition(self, model_class: Any, conditions: Dict[str, Any], **kwargs: Any):
        return [r for r in self.rows if all(r.get(k) == v for k, v in conditions.items())]

    def insert(self, model: Any) -> Dict[str, Any]:
        row = {k: v for k, v in model.__dict__.items() if not k.startswith("_")}
        row["id"] = len(self.rows) + 1
        self.rows.append(row)
        return row

    def update_record(self, table: str, record_id: int, updates: Dict[str, Any]) -> None:
        for row in self.rows:
            if row.get("id") == record_id:
                row.update(updates)


@pytest.fixture()
def service(tmp_path, monkeypatch: pytest.MonkeyPatch) -> AuthService:
    monkeypatch.setenv("GENY_AUTH_SECRET", "test-secret-not-a-real-one")
    svc = AuthService(_FakeDb())
    svc.setup("admin", "first-password", "Admin")
    return svc


# ── rotating the password ────────────────────────────────────────────


class TestChangePassword:
    def test_the_new_password_works_and_the_old_one_stops(self, service: AuthService) -> None:
        service.change_password("admin", "first-password", "second-password")
        assert service.login("admin", "second-password")["username"] == "admin"
        with pytest.raises(ValueError):
            service.login("admin", "first-password")

    def test_the_current_password_is_required(self, service: AuthService) -> None:
        """The caller already holds a token — which is exactly what a thief
        would hold, and what this is protecting against."""
        with pytest.raises(ValueError, match="Invalid credentials"):
            service.change_password("admin", "not-it", "second-password")

    def test_the_new_password_must_actually_be_new(self, service: AuthService) -> None:
        with pytest.raises(ValueError):
            service.change_password("admin", "first-password", "first-password")

    def test_a_too_short_password_is_refused(self, service: AuthService) -> None:
        with pytest.raises(ValueError):
            service.change_password("admin", "first-password", "ab")

    def test_every_earlier_token_stops_verifying(self, service: AuthService) -> None:
        """A 30-day token outliving the rotation by a month is the whole
        reason to store when the password changed."""
        old = service.login("admin", "first-password")["access_token"]
        assert service.get_user_from_token(old) is not None

        service.change_password("admin", "first-password", "second-password")

        assert service.get_user_from_token(old) is None
        with pytest.raises(jwt.InvalidTokenError):
            service.verify_token(old)

    def test_the_caller_keeps_its_own_session(self, service: AuthService) -> None:
        """The device performing the rotation should not have to sign back in
        to the change it just made."""
        fresh = service.change_password("admin", "first-password", "second-password")
        assert service.get_user_from_token(fresh["access_token"]) is not None

    def test_a_token_minted_after_the_change_verifies(self, service: AuthService) -> None:
        service.change_password("admin", "first-password", "second-password")
        token = service.login("admin", "second-password")["access_token"]
        assert service.get_user_from_token(token) is not None

    def test_a_never_rotated_account_accepts_its_tokens(self, service: AuthService) -> None:
        token = service.login("admin", "first-password")["access_token"]
        assert service.get_user_from_token(token) is not None


# ── throttling ───────────────────────────────────────────────────────


class TestThrottle:
    def test_the_first_attempt_is_free(self) -> None:
        assert LoginThrottle().check("1.2.3.4") is None

    def test_a_failure_makes_the_next_attempt_wait(self) -> None:
        throttle = LoginThrottle()
        throttle.record_failure("1.2.3.4")
        assert (throttle.check("1.2.3.4") or 0) > 0

    def test_the_wait_grows_with_each_failure(self) -> None:
        throttle = LoginThrottle()
        throttle.record_failure("1.2.3.4")
        first = throttle.check("1.2.3.4") or 0
        throttle.record_failure("1.2.3.4")
        throttle.record_failure("1.2.3.4")
        assert (throttle.check("1.2.3.4") or 0) > first

    def test_it_stops_growing(self) -> None:
        throttle = LoginThrottle()
        for _ in range(5):
            throttle.record_failure("1.2.3.4")
        assert (throttle.check("1.2.3.4") or 0) <= LoginThrottle.MAX_DELAY_S

    def test_enough_failures_lock_the_source_out(self) -> None:
        throttle = LoginThrottle()
        for _ in range(LoginThrottle.MAX_FAILURES):
            throttle.record_failure("1.2.3.4")
        wait = throttle.check("1.2.3.4") or 0
        assert wait > LoginThrottle.MAX_DELAY_S

    def test_the_lockout_ends(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A permanent lockout would bar the only account from its own
        service after one bad afternoon."""
        throttle = LoginThrottle()
        for _ in range(LoginThrottle.MAX_FAILURES):
            throttle.record_failure("1.2.3.4")
        base = time.monotonic()
        monkeypatch.setattr(time, "monotonic", lambda: base + LoginThrottle.LOCKOUT_S + 1)
        assert throttle.check("1.2.3.4") is None

    def test_a_success_clears_the_record(self) -> None:
        """Someone who mistyped twice is not punished for the rest of the
        hour."""
        throttle = LoginThrottle()
        throttle.record_failure("1.2.3.4")
        throttle.record_failure("1.2.3.4")
        throttle.record_success("1.2.3.4")
        assert throttle.check("1.2.3.4") is None

    def test_sources_are_throttled_independently(self) -> None:
        throttle = LoginThrottle()
        for _ in range(LoginThrottle.MAX_FAILURES):
            throttle.record_failure("1.2.3.4")
        assert throttle.check("5.6.7.8") is None


class TestLoginIsThrottled:
    def test_a_wrong_password_costs_the_next_attempt(self, service: AuthService) -> None:
        with pytest.raises(ValueError):
            service.login("admin", "wrong", source="1.2.3.4")
        with pytest.raises(TooManyAttempts):
            service.login("admin", "first-password", source="1.2.3.4")

    def test_the_refusal_says_how_long_to_wait(self, service: AuthService) -> None:
        with pytest.raises(ValueError):
            service.login("admin", "wrong", source="1.2.3.4")
        with pytest.raises(TooManyAttempts) as caught:
            service.login("admin", "wrong", source="1.2.3.4")
        assert caught.value.retry_after_s >= 1

    def test_an_unknown_username_is_throttled_too(self, service: AuthService) -> None:
        """Otherwise guessing the username is free and only the password
        costs anything."""
        with pytest.raises(ValueError):
            service.login("nobody", "whatever", source="1.2.3.4")
        assert (service.throttle.check("1.2.3.4") or 0) > 0

    def test_a_success_leaves_no_penalty_behind(self, service: AuthService) -> None:
        service.login("admin", "first-password", source="1.2.3.4")
        assert service.throttle.check("1.2.3.4") is None

    def test_another_source_is_unaffected(self, service: AuthService) -> None:
        with pytest.raises(ValueError):
            service.login("admin", "wrong", source="1.2.3.4")
        assert service.login("admin", "first-password", source="9.9.9.9")["username"] == "admin"


class TestTokenGeneration:
    def test_a_token_from_before_this_feature_still_works(self, service: AuthService) -> None:
        """Every connector in the field holds a token with no `pwd` claim.
        Rejecting those would sign every device out on deploy day."""
        legacy = jwt.encode(
            {
                "sub": "admin",
                "display_name": "Admin",
                "exp": datetime.now(timezone.utc) + timedelta(days=1),
                "iat": datetime.now(timezone.utc),
            },
            service.secret_key,
            algorithm=service.ALGORITHM,
        )
        assert service.get_user_from_token(legacy) is not None

    def test_a_legacy_token_dies_at_the_first_rotation(self, service: AuthService) -> None:
        legacy = jwt.encode(
            {
                "sub": "admin",
                "display_name": "Admin",
                "exp": datetime.now(timezone.utc) + timedelta(days=1),
                "iat": datetime.now(timezone.utc),
            },
            service.secret_key,
            algorithm=service.ALGORITHM,
        )
        service.change_password("admin", "first-password", "second-password")
        assert service.get_user_from_token(legacy) is None

    def test_a_second_rotation_revokes_the_first_one_s_token(self, service: AuthService) -> None:
        after_first = service.change_password("admin", "first-password", "second-password")
        service.change_password("admin", "second-password", "third-password")
        assert service.get_user_from_token(after_first["access_token"]) is None

    def test_a_refreshed_token_carries_the_current_generation(self, service: AuthService) -> None:
        service.change_password("admin", "first-password", "second-password")
        refreshed = service.refresh_token("admin")
        assert service.get_user_from_token(refreshed["access_token"]) is not None
