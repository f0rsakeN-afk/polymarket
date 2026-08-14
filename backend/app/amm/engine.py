from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
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
    Constant-product AMM for binary outcome prediction markets.

    Invariant:  yes_shares * no_shares = k

    price(YES) = no_shares / (yes_shares + no_shares)
    price(NO)  = yes_shares / (yes_shares + no_shares)

    Buying YES:
      - Deposits collateral into YES pool
      - Receives YES shares (from NO side of the pool)
      - YES price rises, NO price falls

    Selling YES:
      - Deposits YES shares into pool
      - Receives collateral from NO side
      - YES price falls, NO price rises
    """

    def __init__(
        self,
        yes_shares: Decimal,
        no_shares: Decimal,
        fee_rate: Decimal = Decimal("0.02"),
    ):
        self.yes_shares = max(Decimal(0), yes_shares)
        self.no_shares = max(Decimal(0), no_shares)
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

    def _execute_buy(
        self,
        outcome: Literal["yes", "no"],
        collateral: Decimal,
        min_shares_out: Decimal | None = None,
    ) -> AMMQuote:
        """Core buy logic — mutates pool state and returns quote."""
        fee = collateral * self.fee_rate
        collateral_net = collateral - fee
        k = self._k()

        if outcome == "yes":
            new_yes = self.yes_shares + collateral_net
            new_no = k / new_yes if new_yes > 0 else Decimal(0)
            shares_out = max(Decimal(0), self.no_shares - new_no)
        else:
            new_no = self.no_shares + collateral_net
            new_yes = k / new_no if new_no > 0 else Decimal(0)
            shares_out = max(Decimal(0), self.yes_shares - new_yes)

        if min_shares_out is not None and shares_out < min_shares_out:
            raise ValueError(f"Slippage exceeded: output {shares_out} < minimum {min_shares_out}")

        current_price = self.price(outcome)

        self.yes_shares = new_yes
        self.no_shares = new_no

        after_total = self.yes_shares + self.no_shares

        return AMMQuote(
            shares_out=shares_out.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            collateral_in=collateral,
            fee=fee.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            price=current_price,
            slippage=Decimal(0),
            yes_price_after=self.yes_shares / after_total if after_total > 0 else Decimal("0.5"),
            no_price_after=self.no_shares / after_total if after_total > 0 else Decimal("0.5"),
        )

    def _execute_sell(
        self,
        outcome: Literal["yes", "no"],
        shares: Decimal,
        min_collateral_out: Decimal | None = None,
    ) -> AMMQuote:
        """Core sell logic — mutates pool state and returns quote."""
        k = self._k()

        if outcome == "yes":
            if shares > self.yes_shares:
                raise ValueError(f"Not enough YES shares: held={self.yes_shares}, requested={shares}")
            new_yes = self.yes_shares - shares
            new_no = k / new_yes if new_yes > 0 else Decimal(0)
            collateral_raw = new_no - self.no_shares
        else:
            if shares > self.no_shares:
                raise ValueError(f"Not enough NO shares: held={self.no_shares}, requested={shares}")
            new_no = self.no_shares - shares
            new_yes = k / new_no if new_no > 0 else Decimal(0)
            collateral_raw = new_yes - self.yes_shares

        fee = collateral_raw * self.fee_rate
        collateral_net = collateral_raw - fee

        if min_collateral_out is not None and collateral_net < min_collateral_out:
            raise ValueError(f"Slippage exceeded: collateral {collateral_net} < minimum {min_collateral_out}")

        current_price = self.price(outcome)

        self.yes_shares = new_yes
        self.no_shares = new_no

        after_total = self.yes_shares + self.no_shares

        return AMMQuote(
            shares_out=shares.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            collateral_in=collateral_net.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            fee=fee.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            price=current_price,
            slippage=Decimal(0),
            yes_price_after=self.yes_shares / after_total if after_total > 0 else Decimal("0.5"),
            no_price_after=self.no_shares / after_total if after_total > 0 else Decimal("0.5"),
        )

    def buy(self, outcome: Literal["yes", "no"], collateral: Decimal, min_shares_out: Decimal | None = None) -> AMMQuote:
        """Buy shares of an outcome by depositing collateral. Pool state is updated."""
        return self._execute_buy(outcome, collateral, min_shares_out)

    def sell(self, outcome: Literal["yes", "no"], shares: Decimal, min_collateral_out: Decimal | None = None) -> AMMQuote:
        """Sell shares back to the pool for collateral. Pool state is updated."""
        return self._execute_sell(outcome, shares, min_collateral_out)
