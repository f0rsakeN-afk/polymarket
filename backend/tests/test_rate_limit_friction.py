"""Rate limiting, and specifically the places it looks like it is working.

The friction limiter is the thing standing between a leaked password and an
unlimited guessing oracle, so the tests here are mostly about *whether it
actually holds* rather than about the counters being incremented.

`conftest` disables rate limiting suite-wide, so every test that asserts real
throttling has to switch it on for itself. That is not boilerplate: a throttling
assertion written against a disabled limiter passes with the throttling removed,
which is a test that reports safety it has not checked.
"""

import pytest

from app.config import settings
from app.services.rate_limit_service import LimitType, RateLimitService


@pytest.fixture(autouse=True)
def _rate_limiting_on(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    yield


@pytest.fixture(autouse=True)
def _clear_counters():
    """Wipe `rl:*` around each test.

    `record_failure` writes to shared Redis, so a test that deliberately guesses
    wrong throttles the next one - which is how a correct test fails because of
    an unrelated one, and how a suite starts depending on its own ordering.
    """
    from app.redis import get_redis_sync

    def _wipe() -> None:
        redis = get_redis_sync()
        for key in redis.scan_iter(match="rl:*"):
            redis.delete(key)

    _wipe()
    yield
    _wipe()


@pytest.mark.asyncio
async def test_a_locked_account_is_never_told_the_wait_is_zero():
    """The bug that let a lockout be walked straight through.

    Callers gate on `if is_slowed and rl_result.retry_after`. The friction script
    returns a fractional remaining delay, and `int()` truncated it - so with less
    than a second left, `retry_after` came back `0`, the gate evaluated false, and
    the request fell through to credential verification anyway. The lockout was
    bypassed for most of its own duration.

    A caller that has been locked must always be told to wait, so the wait is
    floored at a whole second.
    """
    ip = "203.0.113.10"

    for _ in range(settings.rate_limit_auth_max_attempts):
        await RateLimitService.record_failure("locked@example.com", ip)

    saw_zero = False
    for _ in range(12):
        result, is_slowed = await RateLimitService.check_with_friction("locked@example.com", ip)
        if is_slowed:
            assert result.retry_after is not None and result.retry_after >= 1, (
                f"locked, but told the wait was {result.retry_after!r} - the caller's "
                "`if is_slowed and retry_after` gate would be false and the "
                "lockout would not apply"
            )
        if result.retry_after == 0:
            saw_zero = True

    assert not saw_zero, "a locked caller was told to wait zero seconds"


@pytest.mark.asyncio
async def test_friction_engages_only_after_the_configured_attempts():
    """Before the threshold it must not interfere - or every correct password
    would look like an attack."""
    ip = "203.0.113.11"
    threshold = settings.rate_limit_auth_max_attempts

    # `check_with_friction` increments the counter as well as `record_failure`,
    # so probing mid-loop would count twice per attempt and lock early.
    for _ in range(threshold - 1):
        await RateLimitService.record_failure("early@example.com", ip)

    _, is_slowed = await RateLimitService.check_with_friction("early@example.com", ip)
    assert not is_slowed, f"locked before {threshold} failures"

    await RateLimitService.record_failure("early@example.com", ip)
    _, is_slowed = await RateLimitService.check_with_friction("early@example.com", ip)
    assert is_slowed, f"never locked after {threshold} failures"


@pytest.mark.asyncio
async def test_the_friction_key_is_the_account_not_the_address():
    """Rotating source addresses must not buy a fresh allowance.

    A per-IP limit alone is trivially defeated: every new source address starts
    with a full allowance. This is the reason the limiter is keyed on the account
    as well as the address.
    """
    # Each attempt from a different address, exactly what an attacker with a
    # handful of egress ranges would do. A per-(email, IP) limit gives every one
    # of these a clean slate; only an account-scoped window bounds the total.
    limit, _window = RateLimitService._LIMITS[LimitType.ACCOUNT_AUTH]

    outcomes = []
    for attempt in range(limit + 3):
        await RateLimitService.record_failure(
            "rotator@example.com", f"198.51.100.{attempt}"
        )
        result, _slowed = await RateLimitService.check_with_friction(
            "rotator@example.com", f"198.51.100.{attempt}"
        )
        outcomes.append(result.allowed)

    assert not all(outcomes), (
        f"a fresh IP bought a clean slate on every attempt ({limit + 3} guesses, "
        "none refused) - the account's password can be guessed without limit by "
        "rotating source addresses"
    )


@pytest.mark.asyncio
async def test_success_clears_the_friction_so_a_real_user_is_not_penalised():
    """A user who fat-fingersed their password twice must not be locked out of
    their own account for the next quarter of an hour."""
    ip = "203.0.113.12"

    for _ in range(settings.rate_limit_auth_max_attempts):
        await RateLimitService.record_failure("typo@example.com", ip)
    _, is_slowed = await RateLimitService.check_with_friction("typo@example.com", ip)
    assert is_slowed

    await RateLimitService.reset_friction("typo@example.com", ip)

    result, is_slowed = await RateLimitService.check_with_friction("typo@example.com", ip)
    assert not is_slowed, "a correct attempt after a few typos is still treated as an attack"


@pytest.mark.asyncio
async def test_redis_failure_fails_open_rather_than_locking_everyone_out():
    """Availability beats throttling when the limiter itself is broken.

    A rate limiter that hard-fails when Redis is unreachable turns a partial
    outage into a total one - nobody can sign in. Guessing is throttled by the
    window too, so failing open here is the lesser risk, and it is a *visible*
    one: the service logs a warning.
    """
    from app.services import rate_limit_service as module

    async def _explode(*_args, **_kwargs):
        raise RuntimeError("redis is gone")

    monkey = getattr(module, "redis_cb")
    original = monkey.call
    monkey.call = staticmethod(_explode)
    try:
        result, is_slowed = await RateLimitService.check_with_friction("x@example.com", "1.1.1.1")
        assert result.allowed is True
        assert is_slowed is False
    finally:
        monkey.call = original


@pytest.mark.asyncio
async def test_the_sliding_window_still_applies_independently():
    """Friction and the window are two different mechanisms.

    Friction delays; the window refuses. If friction alone were relied upon, a
    caller who simply waited out the delay would get unlimited attempts.
    """
    limit, window = RateLimitService._LIMITS[LimitType.AUTH_DECISION]
    ip = "203.0.113.13"

    results = [
        await RateLimitService.check(LimitType.AUTH_DECISION, "window@example.com", ip)
        for _ in range(limit + 2)
    ]

    assert any(not r.allowed for r in results), (
        f"the {window}s window for {limit} attempts never refused anybody"
    )