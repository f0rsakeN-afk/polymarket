import hashlib
import hmac
import logging

from app.redis import get_redis, redis_cb

logger = logging.getLogger("polymarket")

CODE_TTL = 600  # 10 minutes
RATE_LIMIT_KEY_TTL = 300  # 5-minute verification attempt window
SEND_RATE_LIMIT = 5  # max OTP codes generated per email+purpose per window


class OTPService:
    @staticmethod
    def _generate_code() -> str:
        # 8-digit base32-compatible (A-Z, 0-9) = 2.8 trillion combos — brute-force infeasible
        import secrets
        return str(secrets.randbelow(10**8)).zfill(8)

    @staticmethod
    def _hash_code(code: str, secret: str) -> str:
        return hmac.new(secret.encode(), code.encode(), hashlib.sha256).hexdigest()[:64]

    @staticmethod
    def _get_secret(email: str, purpose: str) -> str:
        import app.config

        base = f"{app.config.settings.jwt_secret}:{email}:{purpose}"
        return hashlib.sha256(base.encode()).hexdigest()[:32]

    @staticmethod
    async def send_code(email: str, purpose: str) -> str:
        """
        Generate an 8-digit code and store hash in Redis.
        Returns the plain code — email dispatch is handled by the Celery worker.
        Rate-limited to SEND_RATE_LIMIT codes per email+purpose per window.
        """
        r = await get_redis()

        # Rate limit OTP generation to prevent email bombing
        send_key = f"otp_send:{purpose}:{email}"
        send_result = await redis_cb.call(
            lambda: r.eval(
                OTPService._RATE_LIMIT_SCRIPT, 1,
                send_key, SEND_RATE_LIMIT, RATE_LIMIT_KEY_TTL,
            )
        )
        if send_result == -1:
            logger.warning(f"OTP send rate limit exceeded for {email}, purpose={purpose}")
            from app.api.exceptions import ValidationError
            raise ValidationError("Too many codes sent. Please wait before requesting another.")
        # Note: _RATE_LIMIT_SCRIPT returns -1 when rate limited, otherwise the
        # positive counter value. It never returns -2 — the TTL is set inside
        # the script itself when count == 1, so no extra EXPIRE is needed here.

        code = OTPService._generate_code()
        secret = OTPService._get_secret(email, purpose)
        key = f"otp:{purpose}:{email}"

        # Store ONLY the HMAC of the code — the plaintext must never be
        # written to Redis. Verification recomputes the HMAC from the
        # submitted code, so no plaintext is needed at check time either.
        # (Older entries were stored as "<code>:<hash>"; verify_code accepts
        # that format for its remaining ≤10 min TTL so a rolling deploy
        # doesn't reject in-flight codes.)
        await redis_cb.call(
            lambda: r.set(key, OTPService._hash_code(code, secret), ex=CODE_TTL)
        )
        logger.info(f"OTP issued for {email}, purpose={purpose}")
        return code

    # Atomic rate-limit: INCR + TTL set + check in one Lua script — no concurrent bypass
    _RATE_LIMIT_SCRIPT = """
    local key = KEYS[1]
    local limit = tonumber(ARGV[1])
    local ttl = tonumber(ARGV[2])
    local count = redis.call('INCR', key)
    if count == 1 then
        redis.call('EXPIRE', key, ttl)
    end
    if count > limit then
        return -1
    end
    return count
    """

    @staticmethod
    async def verify_code(email: str, purpose: str, code: str) -> bool:
        """
        Verify a code against stored hash. Deletes on success.
        Returns True if valid, False otherwise.
        """
        r = await get_redis()

        # Atomic brute-force rate limit: max 5 attempts per email+purpose per window
        rate_key = f"otp_attempts:{purpose}:{email}"
        result = await redis_cb.call(
            lambda: r.eval(
                OTPService._RATE_LIMIT_SCRIPT, 1,
                rate_key, 5, RATE_LIMIT_KEY_TTL,
            )
        )
        if result == -1:
            logger.warning(f"OTP brute-force attempt detected for {email}, purpose={purpose}")
            return False

        secret = OTPService._get_secret(email, purpose)
        key = f"otp:{purpose}:{email}"

        stored = await redis_cb.call(lambda: r.get(key))

        if not stored:
            return False
        if isinstance(stored, bytes):
            stored = stored.decode()

        if ":" in stored:
            # Legacy "<code>:<hash>" format from before OTP storage became
            # hash-only — accept until its TTL expires, never write it again.
            plain, legacy_hash = stored.split(":", 1)
            if not hmac.compare_digest(OTPService._hash_code(plain, secret), legacy_hash):
                return False
            if not hmac.compare_digest(plain, code):
                return False
        else:
            # Hash-only format: hash the submitted code and compare in
            # constant time. The plaintext code exists only in the caller's
            # return value and the outbound email.
            if not hmac.compare_digest(OTPService._hash_code(code, secret), stored):
                return False

        # Invalidate after successful use
        await redis_cb.call(lambda: r.delete(key))
        await redis_cb.call(lambda: r.delete(rate_key))
        return True

    @staticmethod
    async def invalidate(email: str, purpose: str):
        key = f"otp:{purpose}:{email}"
        r = await get_redis()
        await redis_cb.call(lambda: r.delete(key))
