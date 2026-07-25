from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from dataclasses import dataclass
from typing import Literal


@dataclass
class AMMQuote:
    shares_out: Decimal
    collateral_in: Decimal
    fee: Decimal
    price: Decimal
    slippage: Decimal
    yes_price_after: Decimal
    no_price_after: Decimal


class BinaryAMM:
    """
    Constant product AMM for binary outcome markets.

    x * y = k
    x = YES shares in pool
    y = NO shares in pool
    k = constant product

    price(YES) = y / (x + y)
    price(NO)  = x / (x + y)
    """

    def __init__(
        self,
        yes_shares: Decimal,
        no_shares: Decimal,
        fee_rate: Decimal = Decimal("0.02"),
    ):
        self.yes_shares = max(Decimal("0"), yes_shares)
        self.no_shares = max(Decimal("0"), no_shares)
        self.fee_rate = fee_rate

    def _k(self) -> Decimal:
        return self.yes_shares * self.no_shares

    def price(self, outcome: Literal["yes", "no"]) -> Decimal:
        total = self.yes_shares + self.no_shares
        if total == 0:
            return Decimal("0.5")
        if outcome == "yes":
            return self.no_shares / total
        return self.yes_shares / total

    def buy(
        self,
        outcome: Literal["yes", "no"],
        collateral: Decimal,
        min_shares_out: Decimal | None = None,
    ) -> AMMQuote:
        """
        Buy shares of an outcome by depositing collateral.

        After fee: collateral_after = collateral * (1 - fee_rate)
        New YES pool = YES + collateral_after
        k stays constant → new NO pool = k / new_YES_pool
        Shares out = old_NO_pool - new_NO_pool
        """
        fee = collateral * self.fee_rate
        collateral_after_fee = collateral - fee

        if outcome == "yes":
            new_yes = self.yes_shares + collateral_after_fee
            new_no = self._k() / new_yes if new_yes > 0 else Decimal("0")
            shares_out = max(Decimal("0"), self.no_shares - new_no)
        else:
            new_no = self.no_shares + collateral_after_fee
            new_yes = self._k() / new_no if new_no > 0 else Decimal("0")
            shares_out = max(Decimal("0"), self.yes_shares - new_yes)

        if shares_out < 0:
            shares_out = Decimal("0")

        if min_shares_out is not None and shares_out < min_shares_out:
            raise ValueError(f"Slippage too high: {shares_out} < {min_shares_out}")

        price_before = self.price(outcome)
        price_after = self.price(outcome)  # same since state hasn't changed yet

        current_price = self.price(outcome)

        return AMMQuote(
            shares_out=shares_out.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            collateral_in=collateral,
            fee=fee.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            price=current_price,
            slippage=Decimal("0"),
            yes_price_after=self.yes_shares / (self.yes_shares + self.no_shares),
            no_price_after=self.no_shares / (self.yes_shares + self.no_shares),
        )

    def sell(
        self,
        outcome: Literal["yes", "no"],
        shares: Decimal,
        min_collateral_out: Decimal | None = None,
    ) -> AMMQuote:
        """
        Sell shares back to the AMM for collateral.

        New YES pool = YES - shares (for selling YES)
        k stays constant → new NO pool = k / new_YES_pool
        Collateral out = old_NO_pool - new_NO_pool
        """
        if outcome == "yes":
            if shares > self.yes_shares:
                raise ValueError("Not enough YES shares in pool")
            new_yes = self.yes_shares - shares
            new_no = self._k() / new_yes if new_yes > 0 else Decimal("0")
            collateral_raw = self.no_shares - new_no
        else:
            if shares > self.no_shares:
                raise ValueError("Not enough NO shares in pool")
            new_no = self.no_shares - shares
            new_yes = self._k() / new_no if new_no > 0 else Decimal("0")
            collateral_raw = self.yes_shares - new_yes

        fee = collateral_raw * self.fee_rate
        collateral_out = collateral_raw - fee

        if min_collateral_out is not None and collateral_out < min_collateral_out:
            raise ValueError(f"Slippage too high: {collateral_out} < {min_collateral_out}")

        current_price = self.price(outcome)

        return AMMQuote(
            shares_out=shares.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            collateral_in=collateral_out.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            fee=fee.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            price=current_price,
            slippage=Decimal("0"),
            yes_price_after=new_yes / (new_yes + new_no),
            no_price_after=new_no / (new_yes + new_no),
        )

    def apply_trade(self, outcome: Literal["yes", "no"], collateral: Decimal) -> AMMQuote:
        """Execute trade and update pool state."""
        quote = self.buy(outcome, collateral)

        if outcome == "yes":
            self.yes_shares += collateral - quote.fee
            self.no_shares = self._k() / self.yes_shares if self.yes_shares > 0 else Decimal("0")
        else:
            self.no_shares += collateral - quote.fee
            self.yes_shares = self._k() / self.no_shares if self.no_shares > 0 else Decimal("0")

        return quote
