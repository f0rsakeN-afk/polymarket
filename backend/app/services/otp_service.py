import hashlib
import hmac
import logging
import random

from app.redis import get_redis, redis_cb

logger = logging.getLogger("polymarket")

CODE_TTL = 600  # 10 minutes


class OTPService:
    @staticmethod
    def _generate_code() -> str:
        return str(random.randint(100000, 999999))

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
        Generate a 6-digit code and store hash in Redis.
        Returns the plain code — email dispatch is handled by the Celery worker.
        """
        code = OTPService._generate_code()
        secret = OTPService._get_secret(email, purpose)
        key = f"otp:{purpose}:{email}"

        r = get_redis()
        await redis_cb.call(
            lambda: r.set(key, f"{code}:{OTPService._hash_code(code, secret)}", ex=CODE_TTL)
        )
        logger.info(f"OTP issued for {email}, purpose={purpose}")
        return code

    @staticmethod
    async def verify_code(email: str, purpose: str, code: str) -> bool:
        """
        Verify a code against stored hash. Deletes on success.
        Returns True if valid, False otherwise.
        """
        secret = OTPService._get_secret(email, purpose)
        key = f"otp:{purpose}:{email}"

        r = get_redis()
        stored = await redis_cb.call(lambda: r.get(key))

        if not stored:
            return False

        plain, expected_hash = stored.split(":", 1)
        if not hmac.compare_digest(OTPService._hash_code(plain, secret), expected_hash):
            return False
        if not hmac.compare_digest(plain, code):
            return False

        # Invalidate after successful use
        await redis_cb.call(lambda: r.delete(key))
        return True

    @staticmethod
    async def invalidate(email: str, purpose: str):
        key = f"otp:{purpose}:{email}"
        r = get_redis()
        await redis_cb.call(lambda: r.delete(key))
