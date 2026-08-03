import base64
import hashlib

import pyotp

from app.config import settings


class TOTPService:
    """
    TOTP 2FA using pyotp (RFC 6238 compliant).
    Encryption key is separate from JWT_SECRET — rotated independently.
    """

    @staticmethod
    def generate_secret() -> str:
        """Generate a base32-encoded random secret (160 bits)."""
        return pyotp.random_base32()

    @staticmethod
    def get_totp_uri(secret: str, email: str, issuer: str = "Polymarket") -> str:
        """Return an otpauth:// URI for QR code scanning (Google Authenticator, Authy, etc.)."""
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=email, issuer_name=issuer)

    @staticmethod
    def verify_code(secret: str, code: str, valid_window: int = 1) -> bool:
        """
        Verify a 6-digit TOTP code with ±1 step (30s) clock drift tolerance.
        """
        if not code.isdigit() or len(code) != 6:
            return False
        totp = pyotp.TOTP(secret, valid_window=valid_window)
        return totp.verify(code, valid_window=valid_window)

    @staticmethod
    def encrypt_secret(secret: str) -> str:
        """
        Encrypt TOTP secret at rest using AES-128 (Fernet).
        Key is derived from the dedicated TOTP_ENCRYPTION_KEY (not JWT_SECRET).
        """
        import cryptography.fernet

        key = base64.urlsafe_b64encode(
            hashlib.sha256(settings.totp_encryption_key.encode()).digest()
        )
        f = cryptography.fernet.Fernet(key)
        return f.encrypt(secret.encode()).decode()

    @staticmethod
    def decrypt_secret(encrypted: str) -> str:
        """Decrypt TOTP secret."""
        import cryptography.fernet

        key = base64.urlsafe_b64encode(
            hashlib.sha256(settings.totp_encryption_key.encode()).digest()
        )
        f = cryptography.fernet.Fernet(key)
        return f.decrypt(encrypted.encode()).decode()
