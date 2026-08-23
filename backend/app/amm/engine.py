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

    price(YES) = yes_shares / (yes_shares + no_shares)
    price(NO)  = no_shares  / (yes_shares + no_shares)

    Invariant after each trade: yes_shares * no_shares = k

    Buying YES:
      - Deposits collateral C → receives YES shares S = C * (1-fee) / price(YES)
      - Pool: yes += S, no unchanged → k preserved
      - YES price RISES (more YES collateral → higher probability)

    Selling YES:
      - Deposits S YES shares → receives collateral C = S * price(YES) * (1-fee)
      - Pool: yes -= S, no unchanged → k preserved
      - YES price FALLS (less YES collateral → lower probability)
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
            return self.yes_shares / total
        return self.no_shares / total

    def _execute_buy(
        self,
        outcome: Literal["yes", "no"],
        collateral: Decimal,
        min_shares_out: Decimal | None = None,
    ) -> AMMQuote:
        """Core buy logic — mutates pool state and returns quote."""
        if collateral <= 0:
            raise ValueError("Collateral must be positive")
        total = self.yes_shares + self.no_shares
        if total == 0:
            raise ValueError("Pool not bootstrapped")
        fee = collateral * self.fee_rate
        collateral_net = collateral - fee
        if collateral_net <= 0:
            raise ValueError(f"Fee rate {float(self.fee_rate)*100}% consumes entire collateral")

        if outcome == "yes":
            if self.yes_shares == 0:
                raise ValueError("Cannot buy YES: no YES liquidity in pool")
            shares_out = collateral_net * total / self.yes_shares
            new_yes = self.yes_shares + shares_out
            new_no = self.no_shares
        else:
            if self.no_shares == 0:
                raise ValueError("Cannot buy NO: no NO liquidity in pool")
            shares_out = collateral_net * total / self.no_shares
            new_yes = self.yes_shares
            new_no = self.no_shares + shares_out

        shares_out = max(Decimal(0), shares_out)
        if min_shares_out is not None and shares_out < min_shares_out:
            raise ValueError(f"Slippage exceeded: output {shares_out} < minimum {min_shares_out}")

        current_price = self.price(outcome)

        self.yes_shares = new_yes
        self.no_shares = new_no

        after_total = self.yes_shares + self.no_shares
        after_price_yes = self.yes_shares / after_total if after_total > 0 else Decimal("0.5")
        after_price_no = self.no_shares / after_total if after_total > 0 else Decimal("0.5")

        return AMMQuote(
            shares_out=shares_out.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            collateral_in=collateral,
            fee=fee.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            price=current_price,
            slippage=abs(after_price_yes - current_price) if outcome == "yes" else abs(after_price_no - current_price),
            yes_price_after=after_price_yes,
            no_price_after=after_price_no,
        )

    def _execute_sell(
        self,
        outcome: Literal["yes", "no"],
        shares: Decimal,
        min_collateral_out: Decimal | None = None,
    ) -> AMMQuote:
        """Core sell logic — mutates pool state and returns quote."""
        if shares <= 0:
            raise ValueError("Shares must be positive")
        total = self.yes_shares + self.no_shares
        if total == 0:
            raise ValueError("Pool not bootstrapped")

        if outcome == "yes":
            if self.yes_shares == 0:
                raise ValueError("Cannot sell YES: no YES liquidity in pool")
            if shares > self.yes_shares:
                raise ValueError(f"Not enough YES shares: held={self.yes_shares}, requested={shares}")
            collateral_raw = shares * self.yes_shares / total * (1 - self.fee_rate)
            new_yes = self.yes_shares - shares
            new_no = self.no_shares
        else:
            if self.no_shares == 0:
                raise ValueError("Cannot sell NO: no NO liquidity in pool")
            if shares > self.no_shares:
                raise ValueError(f"Not enough NO shares: held={self.no_shares}, requested={shares}")
            collateral_raw = shares * self.no_shares / total * (1 - self.fee_rate)
            new_yes = self.yes_shares
            new_no = self.no_shares - shares

        if collateral_raw <= 0:
            raise ValueError(f"Fee rate {float(self.fee_rate)*100}% consumes entire collateral")
        fee = collateral_raw * self.fee_rate / (1 - self.fee_rate)
        collateral_net = collateral_raw

        if min_collateral_out is not None and collateral_net < min_collateral_out:
            raise ValueError(f"Slippage exceeded: collateral {collateral_net} < minimum {min_collateral_out}")

        current_price = self.price(outcome)

        self.yes_shares = new_yes
        self.no_shares = new_no

        after_total = self.yes_shares + self.no_shares
        after_price_yes = self.yes_shares / after_total if after_total > 0 else Decimal("0.5")
        after_price_no = self.no_shares / after_total if after_total > 0 else Decimal("0.5")

        return AMMQuote(
            shares_out=shares.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            collateral_in=collateral_net.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            fee=fee.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
            price=current_price,
            slippage=Decimal(0),
            yes_price_after=after_price_yes,
            no_price_after=after_price_no,
        )

    def buy(self, outcome: Literal["yes", "no"], collateral: Decimal, min_shares_out: Decimal | None = None) -> AMMQuote:
        """Buy shares of an outcome by depositing collateral. Pool state is updated."""
        return self._execute_buy(outcome, collateral, min_shares_out)

    def sell(self, outcome: Literal["yes", "no"], shares: Decimal, min_collateral_out: Decimal | None = None) -> AMMQuote:
        """Sell shares back to the pool for collateral. Pool state is updated."""
        return self._execute_sell(outcome, shares, min_collateral_out)
