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
    Share-pool AMM for binary outcome prediction markets.

    price(YES) = yes_shares / (yes_shares + no_shares)
    price(NO)  = no_shares  / (yes_shares + no_shares)
    (prices always sum to 1 — which is exactly what the split/merge
    primitives require, since 1 USDC mints one YES + one NO pair.)

    NOTE ON THE INVARIANT: this is NOT an x*y = k constant-product pool, and
    no such invariant can hold here. price is a *ratio of reserves*, and a
    buy only ever grows one side — for x*y = k to survive, buying YES would
    have to shrink the NO reserve, which the operation does not do. The
    quantity yes_shares * no_shares therefore *rises* on a buy and falls on a
    sell. The real invariant this class defends is the no-arbitrage one
    described below.

    Buying outcome with reserve R (R = yes_shares for YES, no_shares for NO):
      - Deposits collateral C, pays fee = C * fee_rate, nets C_net = C - fee
      - Receives S shares solved so that the buyer pays the POST-trade price
        on every share:

            C_net = S * (R + S) / (T + S)          (T = R + other side)

        closed form:  S = (C_net - R + sqrt((R - C_net)^2 + 4 * C_net * T)) / 2

      - Reserve R grows by S → the outcome's price RISES.

    Selling S shares of the outcome:
      - Receives C = S * (R / T) * (1 - fee_rate) — the PRE-trade price
      - Reserve R shrinks by S → the outcome's price FALLS.

    Why buy charges at the POST-trade price while sell credits the PRE-trade
    price: both are the *adverse* price for the trader, so a round trip
    through the pool can never be profitable. Specifically, for any size:

        buy then sell the same shares  →  you get back (1 - fee_rate)^2
        sell then buy the same shares  →  you get back (1 - fee_rate)^2

    i.e. the only thing a round trip can ever cost is the fees. Charging the
    pre-trade spot price on a buy (the old behaviour) charged ZERO price
    impact, so buying pushed the price up and selling immediately handed the
    buyer the higher price — a buy→sell loop returned MORE than it cost and
    drained the pool. That is the bug this formula fixes.
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
        """Core buy logic — mutates pool state and returns quote.

        Shares are sized from the post-trade price, so price impact is paid
        by the buyer on the whole order (see the class docstring for the
        derivation). Falls back to spot pricing only when the pool is empty,
        which is impossible here (total == 0 already raised).
        """
        if collateral <= 0:
            raise ValueError("Collateral must be positive")
        total = self.yes_shares + self.no_shares
        if total == 0:
            raise ValueError("Pool not bootstrapped")
        fee = collateral * self.fee_rate
        collateral_net = collateral - fee
        if collateral_net <= 0:
            raise ValueError(f"Fee rate {float(self.fee_rate)*100}% consumes entire collateral")

        reserve = self.yes_shares if outcome == "yes" else self.no_shares
        if reserve == 0:
            raise ValueError(
                f"Cannot buy {outcome.upper()}: no {outcome.upper()} liquidity in pool"
            )

        # S^2 + S*(R - C_net) - C_net*T = 0  →  positive root.
        discriminant = (reserve - collateral_net) ** 2 + Decimal(4) * collateral_net * total
        shares_out = (collateral_net - reserve + discriminant.sqrt()) / Decimal(2)
        shares_out = max(Decimal(0), shares_out)
        if min_shares_out is not None and shares_out < min_shares_out:
            raise ValueError(f"Slippage exceeded: output {shares_out} < minimum {min_shares_out}")

        if outcome == "yes":
            new_yes = self.yes_shares + shares_out
            new_no = self.no_shares
        else:
            new_yes = self.yes_shares
            new_no = self.no_shares + shares_out

        current_price = self.price(outcome)

        q = Decimal("0.00000001")
        self.yes_shares = new_yes.quantize(q, rounding=ROUND_DOWN)
        self.no_shares = new_no.quantize(q, rounding=ROUND_DOWN)

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

        q = Decimal("0.00000001")
        self.yes_shares = new_yes.quantize(q, rounding=ROUND_DOWN)
        self.no_shares = new_no.quantize(q, rounding=ROUND_DOWN)

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
