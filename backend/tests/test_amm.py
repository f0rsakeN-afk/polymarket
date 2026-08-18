"""Production-grade AMM engine tests."""
import pytest
from decimal import Decimal

from app.amm.engine import BinaryAMM, AMMQuote


# ── Construction ───────────────────────────────────────────────────────────────

def test_initial_prices_equal_pool():
    """Equal shares → both prices at 0.5."""
    amm = BinaryAMM(yes_shares=Decimal("100"), no_shares=Decimal("100"), fee_rate=Decimal("0"))
    assert float(amm.price("yes")) == pytest.approx(0.5, abs=0.001)
    assert float(amm.price("no")) == pytest.approx(0.5, abs=0.001)


def test_empty_pool_defaults_to_half():
    """Zero shares → price defaults to 0.5 (no divide-by-zero)."""
    amm = BinaryAMM(yes_shares=Decimal("0"), no_shares=Decimal("0"), fee_rate=Decimal("0"))
    assert float(amm.price("yes")) == 0.5
    assert float(amm.price("no")) == 0.5


def test_yes_heavily_backed_yes_price_high():
    """
    price(YES) = yes / (yes + no).
    If YES is heavily backed (yes >> no), YES price → 1.
    If YES is heavily backed, NO price → 0 (inverse).
    """
    amm = BinaryAMM(yes_shares=Decimal("900"), no_shares=Decimal("100"), fee_rate=Decimal("0"))
    assert float(amm.price("yes")) > 0.8   # heavily backed YES → high price
    assert float(amm.price("no")) < 0.2   # inverse


def test_no_heavily_backed_no_price_high():
    """
    price(NO) = no / (yes + no).
    If NO is heavily backed (no >> yes), NO price → 1.
    """
    amm = BinaryAMM(yes_shares=Decimal("100"), no_shares=Decimal("900"), fee_rate=Decimal("0"))
    assert float(amm.price("no")) > 0.8   # heavily backed NO → high price
    assert float(amm.price("yes")) < 0.2  # inverse


# ── Buy — state mutation ───────────────────────────────────────────────────────

def test_buy_yes_mutates_state():
    """Buying YES increases YES shares, no_shares unchanged. Fee leaves pool, no shares minted for it."""
    amm = BinaryAMM(yes_shares=Decimal("50"), no_shares=Decimal("50"), fee_rate=Decimal("0"))
    initial_yes, initial_no = amm.yes_shares, amm.no_shares

    amm.buy("yes", Decimal("10"))

    assert amm.yes_shares > initial_yes
    assert amm.no_shares == initial_no  # no side unchanged in corrected buy


def test_buy_yes_returns_shares():
    """Buyer receives YES shares at fair price (C*(1-fee)/price(YES))."""
    amm = BinaryAMM(yes_shares=Decimal("50"), no_shares=Decimal("50"), fee_rate=Decimal("0"))
    result = amm.buy("yes", Decimal("10"))
    assert result.shares_out > 0
    assert result.collateral_in == Decimal("10")
    # At 50/50 odds, $10 buys ~20 shares (fair price = $0.50/share)
    assert float(result.shares_out) == pytest.approx(20.0, abs=0.01)


def test_buy_yes_fee_deducted():
    """Fee reduces net collateral, reducing shares out."""
    with_fee = BinaryAMM(yes_shares=Decimal("50"), no_shares=Decimal("50"), fee_rate=Decimal("0.02"))
    without_fee = BinaryAMM(yes_shares=Decimal("50"), no_shares=Decimal("50"), fee_rate=Decimal("0"))

    r_fee = with_fee.buy("yes", Decimal("100"))
    r_no_fee = without_fee.buy("yes", Decimal("100"))

    assert r_fee.shares_out < r_no_fee.shares_out
    assert r_fee.fee == Decimal("100") * Decimal("0.02")


def test_buy_yes_price_effect():
    """After buying YES: YES price rises, NO price falls."""
    amm = BinaryAMM(yes_shares=Decimal("50"), no_shares=Decimal("50"), fee_rate=Decimal("0"))
    yes_before = float(amm.price("yes"))
    no_before = float(amm.price("no"))

    amm.buy("yes", Decimal("20"))

    assert float(amm.price("yes")) > yes_before
    assert float(amm.price("no")) < no_before


def test_buy_no_mutates_state():
    """Buying NO increases NO shares, YES shares unchanged."""
    amm = BinaryAMM(yes_shares=Decimal("50"), no_shares=Decimal("50"), fee_rate=Decimal("0"))
    initial_yes, initial_no = amm.yes_shares, amm.no_shares

    amm.buy("no", Decimal("10"))

    assert amm.no_shares > initial_no
    assert amm.yes_shares == initial_yes


def test_buy_no_price_effect():
    """After buying NO: NO price rises, YES price falls."""
    amm = BinaryAMM(yes_shares=Decimal("50"), no_shares=Decimal("50"), fee_rate=Decimal("0"))
    yes_before = float(amm.price("yes"))
    no_before = float(amm.price("no"))

    amm.buy("no", Decimal("20"))

    assert float(amm.price("no")) > no_before
    assert float(amm.price("yes")) < yes_before


# ── Sell — state mutation ─────────────────────────────────────────────────────

def test_sell_yes_mutates_state():
    """Selling YES decreases YES shares, NO shares unchanged."""
    amm = BinaryAMM(yes_shares=Decimal("50"), no_shares=Decimal("50"), fee_rate=Decimal("0"))
    initial_yes, initial_no = amm.yes_shares, amm.no_shares

    result = amm.sell("yes", Decimal("10"))

    assert amm.yes_shares < initial_yes
    assert amm.no_shares == initial_no  # NO side unchanged
    assert result.shares_out == Decimal("10")
    assert result.collateral_in > 0  # positive collateral received


def test_sell_no_mutates_state():
    """Selling NO decreases NO shares, YES shares unchanged."""
    amm = BinaryAMM(yes_shares=Decimal("50"), no_shares=Decimal("50"), fee_rate=Decimal("0"))
    initial_yes, initial_no = amm.yes_shares, amm.no_shares

    result = amm.sell("no", Decimal("10"))

    assert amm.no_shares < initial_no
    assert amm.yes_shares == initial_yes  # YES side unchanged
    assert result.shares_out == Decimal("10")
    assert result.collateral_in > 0


def test_sell_yes_insufficient_shares():
    """Cannot sell more YES than pool holds."""
    amm = BinaryAMM(yes_shares=Decimal("5"), no_shares=Decimal("50"), fee_rate=Decimal("0"))
    with pytest.raises(ValueError, match="Not enough YES"):
        amm.sell("yes", Decimal("100"))


def test_sell_no_insufficient_shares():
    """Cannot sell more NO than pool holds."""
    amm = BinaryAMM(yes_shares=Decimal("50"), no_shares=Decimal("5"), fee_rate=Decimal("0"))
    with pytest.raises(ValueError, match="Not enough NO"):
        amm.sell("no", Decimal("100"))


def test_sell_yes_fee_deducted():
    """Fee reduces collateral received on sell."""
    with_fee = BinaryAMM(yes_shares=Decimal("100"), no_shares=Decimal("100"), fee_rate=Decimal("0.02"))
    without_fee = BinaryAMM(yes_shares=Decimal("100"), no_shares=Decimal("100"), fee_rate=Decimal("0"))

    r_fee = with_fee.sell("yes", Decimal("10"))
    r_no_fee = without_fee.sell("yes", Decimal("10"))

    assert r_fee.collateral_in < r_no_fee.collateral_in
    assert r_fee.fee > 0


def test_sell_yes_price_effect():
    """After selling YES: YES price falls, NO price rises."""
    amm = BinaryAMM(yes_shares=Decimal("50"), no_shares=Decimal("50"), fee_rate=Decimal("0"))
    yes_before = float(amm.price("yes"))
    no_before = float(amm.price("no"))

    amm.sell("yes", Decimal("10"))

    assert float(amm.price("yes")) < yes_before  # YES price falls
    assert float(amm.price("no")) > no_before    # NO price rises (inverse)


# ── Slippage guards ──────────────────────────────────────────────────────────

def test_buy_min_shares_out_enforced():
    """If output below minimum, raises."""
    amm = BinaryAMM(yes_shares=Decimal("50"), no_shares=Decimal("50"), fee_rate=Decimal("0"))
    with pytest.raises(ValueError, match="Slippage"):
        amm.buy("yes", Decimal("1"), min_shares_out=Decimal("100"))


def test_sell_min_collateral_enforced():
    """If collateral below minimum, raises."""
    amm = BinaryAMM(yes_shares=Decimal("50"), no_shares=Decimal("50"), fee_rate=Decimal("0"))
    with pytest.raises(ValueError, match="Slippage"):
        amm.sell("yes", Decimal("10"), min_collateral_out=Decimal("999"))


# ── Quote fields ─────────────────────────────────────────────────────────────

def test_quote_has_all_fields():
    amm = BinaryAMM(yes_shares=Decimal("50"), no_shares=Decimal("50"), fee_rate=Decimal("0.01"))
    q = amm.buy("yes", Decimal("10"))
    assert isinstance(q, AMMQuote)
    assert q.shares_out > 0
    assert q.collateral_in == Decimal("10")
    assert q.fee > 0
    assert 0 <= float(q.price) <= 1
    assert 0 <= float(q.yes_price_after) <= 1
    assert 0 <= float(q.no_price_after) <= 1


def test_multiple_trades_accumulate():
    """Multiple buys change price incrementally (YES price rises with demand)."""
    amm = BinaryAMM(yes_shares=Decimal("50"), no_shares=Decimal("50"), fee_rate=Decimal("0"))
    p1 = float(amm.price("yes"))
    amm.buy("yes", Decimal("10"))
    p2 = float(amm.price("yes"))
    amm.buy("yes", Decimal("10"))
    p3 = float(amm.price("yes"))

    assert p2 > p1  # price rose
    assert p3 > p2  # continued to rise


# ── Password strength ──────────────────────────────────────────────────────────

def test_password_too_short():
    from app.services.password_strength_service import PasswordStrengthService
    strong, reason = PasswordStrengthService.check("ab")
    assert strong is False


def test_password_weak():
    from app.services.password_strength_service import PasswordStrengthService
    strong, _ = PasswordStrengthService.check("password123")
    assert strong is False


def test_password_strong():
    from app.services.password_strength_service import PasswordStrengthService
    strong, _ = PasswordStrengthService.check("MyStr0ng!Pass#2024")
    assert strong is True


# ── TOTP ──────────────────────────────────────────────────────────────────────

def test_totp_generate_secret():
    from app.services.totp_service import TOTPService
    secret = TOTPService.generate_secret()
    assert len(secret) == 32


def test_totp_verify_valid_code():
    import pyotp
    from app.services.totp_service import TOTPService
    secret = TOTPService.generate_secret()
    code = pyotp.TOTP(secret).now()
    assert TOTPService.verify_code(secret, code) is True


def test_totp_verify_invalid_code():
    from app.services.totp_service import TOTPService
    secret = TOTPService.generate_secret()
    assert TOTPService.verify_code(secret, "000000") is False
    assert TOTPService.verify_code(secret, "12345678") is False


def test_totp_encrypt_decrypt_roundtrip():
    from app.services.totp_service import TOTPService
    secret = TOTPService.generate_secret()
    encrypted = TOTPService.encrypt_secret(secret)
    decrypted = TOTPService.decrypt_secret(encrypted)
    assert decrypted == secret
    assert encrypted != secret


def test_totp_uri_format():
    from app.services.totp_service import TOTPService
    secret = TOTPService.generate_secret()
    uri = TOTPService.get_totp_uri(secret, "test@example.com")
    assert uri.startswith("otpauth://totp/")
    assert "secret=" in uri
