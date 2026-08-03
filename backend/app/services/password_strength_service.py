import re


class PasswordStrengthService:
    """
    Fast, dependency-free password strength checker.
    Enforces complexity requirements — no blocklists.
    Returns (is_strong: bool, reason: str | None)
    """

    @staticmethod
    def check(password: str) -> tuple[bool, str | None]:
        """
        Returns (True, None) if strong enough, or (False, reason) if rejected.
        """
        if not password:
            return False, "Password cannot be empty"

        if len(password) < 8:
            return False, "Password must be at least 8 characters"
        if len(password) > 128:
            return False, "Password must be at most 128 characters"

        # Character class checks
        has_lower = bool(re.search(r"[a-z]", password))
        has_upper = bool(re.search(r"[A-Z]", password))
        has_digit = bool(re.search(r"\d", password))
        has_special = bool(re.search(r"[^\w\s]", password))

        classes = sum([has_lower, has_upper, has_digit, has_special])

        # 8-11 chars need all 4 classes
        if len(password) < 12 and classes < 3:
            return False, "Mix uppercase, lowercase, numbers, and symbols"
        # 12+ chars need at least 2 classes
        if len(password) >= 12 and classes < 2:
            return False, "Add numbers or symbols to strengthen"

        # Sequential characters (abc, 123)
        if re.search(r"(abc|bcd|cde|def|efg|fgh|ghi|hij|ijk|jkl|klm|lmn|mno|nop|opq|pqr|qrs|rst|stu|tuv|uvw|vwx|wxy|xyz)", password.lower()):
            return False, "Avoid sequential characters like 'abc' or 'xyz'"
        if re.search(r"(012|123|234|345|456|567|678|789|890)", password):
            return False, "Avoid sequential numbers like '123' or '456'"

        # Repeated characters (aaa, 111)
        if re.search(r"(.)\1{2,}", password):
            return False, "Avoid repeated characters like 'aaa' or '111'"

        return True, None
