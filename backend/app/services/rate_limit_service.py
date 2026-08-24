"""
Redis-backed sliding window rate limiter with progressive friction.
Atomic operations via Lua scripts to avoid race conditions.
"""
import logging
import time
from dataclasses import dataclass
from enum import Enum

from app.config import settings
from app.redis import get_redis, redis_cb

logger = logging.getLogger("polymarket")


class LimitType(Enum):
    GENERAL = "general"           # per IP — 60/min
    AUTH_DECISION = "auth"       # per email+IP — 5/min (login, verify, reset)
    AUTH_FAST = "auth_fast"     # per email+IP — 3/min (resend/forgot)
    STRICT = "strict"           # per IP — 10/min (mutations)


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int | None
    is_slowdown: bool  # True when delay was applied (not hard block)


# ─── Lua scripts ────────────────────────────────────────────────────────────────

# Sorted-set sliding window: stores timestamps, counts entries within the window.
# KEYS[1] = key, ARGV[1] = limit, ARGV[2] = window_seconds, ARGV[3] = now_ts
SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local window_start = now - window

-- Remove expired entries (all with score < window_start)
redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

-- Count current entries in window
local count = redis.call('ZCARD', key)

if count >= limit then
    -- Over limit — return over_limit=1, remaining=0
    return {1, 0}
end

-- Add this request with current timestamp as score
redis.call('ZADD', key, now, now .. ':' .. math.random())
-- Set TTL to window so stale keys self-cleanup
redis.call('EXPIRE', key, window + 1)

local remaining = math.max(0, limit - count - 1)
return {0, remaining}
"""

# Progressive friction: tracks failed attempts and returns a delay to apply.
# Lockout activates at max_attempts (checked BEFORE increment — not after).
# Delays: attempt max_attempts → 1s, max_attempts+1 → 2s, etc. (capped at 16s).
# KEYS[1] = friction_key, ARGV[1] = max_attempts, ARGV[2] = lockout_seconds, ARGV[3] = now
PROGRESSIVE_FRICTION_SCRIPT = """
local key = KEYS[1]
local max_attempts = tonumber(ARGV[1])
local lockout = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local data = redis.call('HMGET', key, 'attempts', 'unlock_at')
local attempts = tonumber(data[1]) or 0
local unlock_at = tonumber(data[2]) or 0

-- Currently in friction delay window
if unlock_at > now then
    local remaining = unlock_at - now
    return {0, remaining, 1}  -- is_locked=1
end

-- Check BEFORE increment — lockout fires at max_attempts, not max_attempts+1
local delay = 0
local is_locked = 0

if attempts >= max_attempts then
    -- Exponential backoff: 1, 2, 4, 8, 16 (capped)
    delay = math.min(2 ^ (attempts - max_attempts), 16)
    unlock_at = now + delay
    is_locked = 1
end

attempts = attempts + 1

redis.call('HSET', key, 'attempts', attempts, 'unlock_at', unlock_at)
redis.call('EXPIRE', key, lockout)

return {attempts, delay, is_locked}
"""

RESET_FRICTION_SCRIPT = """
redis.call('DEL', KEYS[1])
return 1
"""


class RateLimitService:
    """
    Sliding window rate limiter using Redis sorted sets (ZSET).
    Tracks exact timestamps per request for accurate window behavior.

    Progressive friction adds per-attempt delays to slow brute-force attacks
    without hard-blocking legitimate users.
    """

    _LIMITS = {
        LimitType.GENERAL:      (60,  60),   # 60/min per IP
        LimitType.AUTH_DECISION: (5,  60),   # 5/min per email+IP
        LimitType.AUTH_FAST:    (3,  60),   # 3/min per email+IP
        LimitType.STRICT:       (10, 60),   # 10/min per IP
    }

    @staticmethod
    def _key(limit_type: LimitType, identifier: str) -> str:
        return f"rl:{limit_type.value}:{identifier}"

    @staticmethod
    def _friction_key(identifier: str) -> str:
        return f"rl:friction:{identifier}"

    @staticmethod
    def _normalize_ip(ip: str) -> str:
        """Normalize IPv6 to /64 prefix to avoid fragmentation from same subnet."""
        if ":" not in ip:
            return ip
        parts = ip.split(":")
        # Strip empty segments from :: expansion
        meaningful = [p for p in parts if p]
        if len(meaningful) >= 4:
            # Enough explicit parts — take first 4 groups
            return ":".join(p.zfill(4) for p in meaningful[:4]) + "::"
        if len(meaningful) < 4:
            # Less than 4 explicit parts means :: is present — rebuild /64 from what's there
            # e.g. "2001:db8::1" → "2001:0db8::"
            filled = [p.zfill(4) for p in meaningful] + ["0000"] * (4 - len(meaningful))
            return ":".join(filled[:4]) + "::"
        return ip

    @staticmethod
    async def check(limit_type: LimitType, identifier: str, ip: str | None = None) -> RateLimitResult:
        """
        Sliding window check. Returns whether the request is allowed.
        Uses ZSET to store exact request timestamps.
        """
        if not settings.rate_limit_enabled:
            return RateLimitResult(allowed=True, limit=0, remaining=0, retry_after=None, is_slowdown=False)

        limit, window = RateLimitService._LIMITS[limit_type]
        now = time.time()
        r = await get_redis()

        # Composite key for auth limits: email@normalized_ip
        if limit_type in (LimitType.AUTH_DECISION, LimitType.AUTH_FAST) and ip:
            ip = RateLimitService._normalize_ip(ip)
            key = RateLimitService._key(limit_type, f"{identifier}@{ip}")
        else:
            if ip:
                ip = RateLimitService._normalize_ip(ip)
            key = RateLimitService._key(limit_type, identifier)

        try:
            script_result = await redis_cb.call(
                lambda: r.eval(SLIDING_WINDOW_SCRIPT, 1, key, limit, window, now)
            )
            over_limit, remaining = int(script_result[0]), int(script_result[1])
        except Exception as e:
            logger.warning(f"Rate limit Redis error (check): {e}")
            return RateLimitResult(allowed=False, limit=limit, remaining=0, retry_after=60, is_slowdown=True)  # Fail closed

        if over_limit:
            return RateLimitResult(
                allowed=False,
                limit=limit,
                remaining=0,
                retry_after=window,
                is_slowdown=False,
            )

        return RateLimitResult(
            allowed=True,
            limit=limit,
            remaining=remaining,
            retry_after=None,
            is_slowdown=False,
        )

    @staticmethod
    async def check_with_friction(
        identifier: str,
        ip: str,
        limit_type: LimitType = LimitType.AUTH_DECISION,
    ) -> tuple[RateLimitResult, bool]:
        """
        Check sliding window AND progressive friction.
        Returns (result, was_slowed). Call reset_friction() on success.
        """
        if not settings.rate_limit_enabled:
            return RateLimitResult(allowed=True, limit=999, remaining=999, retry_after=None, is_slowdown=False), False

        # Normalize IP for friction key
        normalized_ip = RateLimitService._normalize_ip(ip)
        friction_key = RateLimitService._friction_key(f"{identifier}@{normalized_ip}")
        now = time.time()
        r = await get_redis()

        max_attempts = settings.rate_limit_auth_max_attempts
        lockout = settings.rate_limit_auth_lockout_seconds

        try:
            result = await redis_cb.call(
                lambda: r.eval(
                    PROGRESSIVE_FRICTION_SCRIPT, 1,
                    friction_key, max_attempts, lockout, now,
                )
            )
            _, delay, is_locked = int(result[0]), float(result[1]), int(result[2])
        except Exception as e:
            logger.warning(f"Rate limit Redis error (friction): {e}")
            return RateLimitResult(allowed=True, limit=5, remaining=5, retry_after=None, is_slowdown=False), False

        if is_locked:
            return RateLimitResult(
                allowed=True,
                limit=max_attempts,
                remaining=0,
                retry_after=int(delay),
                is_slowdown=True,
            ), True

        # Check sliding window too
        rl_result = await RateLimitService.check(limit_type, identifier, normalized_ip)
        return rl_result, False

    @staticmethod
    async def reset_friction(identifier: str, ip: str):
        """Clear friction counter on successful auth."""
        if not settings.rate_limit_enabled:
            return
        normalized_ip = RateLimitService._normalize_ip(ip)
        friction_key = RateLimitService._friction_key(f"{identifier}@{normalized_ip}")
        r = await get_redis()
        try:
            await redis_cb.call(lambda: r.eval(RESET_FRICTION_SCRIPT, 1, friction_key))
        except Exception as e:
            logger.warning(f"Rate limit reset error: {e}")

    @staticmethod
    async def record_failure(identifier: str, ip: str):
        """Record a failed auth attempt. Increments friction counter."""
        if not settings.rate_limit_enabled:
            return
        normalized_ip = RateLimitService._normalize_ip(ip)
        friction_key = RateLimitService._friction_key(f"{identifier}@{normalized_ip}")
        r = await get_redis()
        try:
            await redis_cb.call(
                lambda: r.eval(
                    PROGRESSIVE_FRICTION_SCRIPT, 1,
                    friction_key,
                    settings.rate_limit_auth_max_attempts,
                    settings.rate_limit_auth_lockout_seconds,
                    time.time(),
                )
            )
        except Exception as e:
            logger.warning(f"Rate limit record_failure error: {e}")
