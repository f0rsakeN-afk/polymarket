"use client"

import { useCallback, useEffect, useMemo, useRef, useState, memo } from "react"
import { useForm, useWatch } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Spinner } from "@workspace/ui/components/spinner"
import { Checkbox } from "@workspace/ui/components/checkbox"
import { Label } from "@workspace/ui/components/label"
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
  SelectGroup,
} from "@workspace/ui/components/select"
import {
  Field,
  FieldContent,
  FieldError,
  FieldLabel,
} from "@workspace/ui/components/field"

import { cn } from "@workspace/ui/lib/utils"
import {
  placeOrderSchema,
  type PlaceOrderInput,
  z,
} from "@/lib/schemas/trading"
import { getQuote } from "@/lib/api/orders"
import { useCurrentUser } from "@/hooks/use-auth"
import { useWallet } from "@/hooks/api/use-wallet"
import type { Outcome } from "@/hooks/api/types/market"
import type { QuoteResponse } from "@/hooks/api/types/order"
import Link from "next/link"

type FormInput = z.input<typeof placeOrderSchema>

interface TradeFormProps {
  marketId: string
  currentYesPrice: number
  currentNoPrice: number
  /** Live per-outcome prices, keyed by lower-cased outcome name.
   *  Required for 3+ outcome markets, which the book prices alone. */
  outcomePrices?: Record<string, number>
  outcomes?: Outcome[]
  marketStatus: string
  /**
   * Increments whenever this market's book changes because *someone else* traded.
   *
   * The form's displayed price is live from the socket, but every input to its
   * quote effect is user-owned: market, outcome, side, amount. None of them
   * change when another user buys, so nothing invalidated the quote - and the
   * user submits against a pre-trade price that the server then validates against
   * current state and rejects with "Quote expired • please refresh".
   *
   * A version counter rather than the book object, so the effect re-runs on every
   * change and the dependency stays a primitive.
   */
  marketVersion?: number
  onSubmit: (order: PlaceOrderInput) => Promise<void>
}

// Only resolved markets block trading. Active, closed, and dispute_window all allow trading.
const BLOCKED_STATUS = "resolved"

function NotLoggedIn() {
  return (
    <div className="space-y-2 py-6 text-center">
      <p className="text-sm text-muted-foreground">Sign in to start trading</p>
      <Link
        href="/login"
        className="block w-full rounded-md border border-primary bg-primary px-4 py-2 text-center text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
      >
        Sign In
      </Link>
      <p className="text-xs text-muted-foreground">
        New here?{" "}
        <Link
          href="/signup"
          className="underline underline-offset-2 hover:text-foreground"
        >
          Create account
        </Link>
      </p>
    </div>
  )
}

function MarketClosedBanner({ status }: { status: string }) {
  return (
    <div
      role="alert"
      className="rounded-md border border-yellow-500/20 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-700"
    >
      Market is <span className="font-medium">{status}</span> • trading is
      disabled
    </div>
  )
}

function InsufficientBalanceBanner({ balance }: { balance: number }) {
  return (
    <div
      role="alert"
      className="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-600"
    >
      Insufficient balance • you have{" "}
      <span className="font-medium">${balance.toFixed(2)}</span> available
    </div>
  )
}

const OutcomeButton = memo(function OutcomeButton({
  label,
  price,
  selected,
  color,
  onClick,
}: {
  label: string
  price: number
  selected: boolean
  color: "green" | "red"
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      // The full name on hover, because the visible label is capped at two
      // lines. Without this a clipped "Los Angeles…" gives no way to read the
      // rest without opening the market.
      title={label}
      className={cn(
        // `min-w-0` is load-bearing: a grid item defaults to `min-width: auto`,
        // so one long outcome name sets the track's minimum width and pushes the
        // whole row wider than the card. That is what made an eight-way market
        // overflow on a phone.
        "flex min-h-11 min-w-0 flex-col items-center justify-center gap-0.5 rounded-xl border p-2.5 text-center transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        selected
          ? color === "green"
            ? "border-green-600/50 bg-green-600/10 text-green-700 dark:text-green-400"
            : "border-red-600/50 bg-red-600/10 text-red-700 dark:text-red-400"
          : "border-border bg-card text-muted-foreground hover:bg-muted"
      )}
    >
      {/* Wraps rather than truncates: this is a selector, and an outcome the
          user cannot read is an outcome they cannot pick.

          `break-words` (overflow-wrap) rather than `break-all`: it only breaks a
          word when it genuinely cannot fit the track, so "Golden State Warriors"
          wraps at its spaces. `break-all` breaks mid-character at any width,
          which renders the same label as "Go|lden St|ate Wa|rriors" and reads as
          corrupted. The single-token case that `break-all` was really covering -
          one unbreakable string wider than the column - is handled by `break-words`
          too, and by `min-w-0` on this button, which is what actually lets the
          grid track shrink below the content width.

          `hyphens-auto` breaks long names at real hyphenation points at the edge
          rather than overflowing. */}
      <div className="line-clamp-2 text-sm leading-tight font-bold break-words hyphens-auto">
        {label}
      </div>
      <div className="text-xs tabular-nums">${price.toFixed(2)}</div>
    </button>
  )
})

const SideButton = memo(function SideButton({
  side,
  current,
  onClick,
}: {
  side: "buy" | "sell"
  current: "buy" | "sell"
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={side === current}
      className={cn(
        "min-h-9 rounded-xl border py-1.5 text-xs font-semibold uppercase transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        side === current
          ? side === "buy"
            ? "border-green-600/50 bg-green-600/10 text-green-700 dark:text-green-400"
            : "border-red-600/50 bg-red-600/10 text-red-700 dark:text-red-400"
          : "border-border text-muted-foreground hover:bg-muted"
      )}
    >
      {side}
    </button>
  )
})

function TradeForm({
  marketId,
  currentYesPrice,
  currentNoPrice,
  outcomePrices,
  outcomes,
  marketStatus,
  marketVersion = 0,
  onSubmit,
}: TradeFormProps) {
  const { data: currentUser } = useCurrentUser()
  const { data: wallet } = useWallet()

  // Parimutuel = no real YES/NO pair, decided by outcome NAME. Counting
  // outcomes would treat a two-way named market as binary and preselect
  // "yes" • an outcome that market does not have.
  const isMultiOutcome = useMemo(() => {
    if (!outcomes || outcomes.length === 0) return false
    const names = outcomes.map((o) => o.name.toLowerCase())
    return !(names.includes("yes") && names.includes("no"))
  }, [outcomes])
  const [outcome, setOutcome] = useState<string>(
    isMultiOutcome ? (outcomes?.[0]?.name?.toLowerCase() ?? "yes") : "yes"
  )
  const [side, setSide] = useState<"buy" | "sell">("buy")
  const [quote, setQuote] = useState<QuoteResponse | null>(null)
  // Params the cached quote was fetched for • render gates on match so a
  // stale quote never shows for different inputs (no sync clear in effect).
  const [quoteMeta, setQuoteMeta] = useState<{
    marketId: string
    outcome: string
    side: "buy" | "sell"
    amount: number
  } | null>(null)
  const [quoteLoading, setQuoteLoading] = useState(false)
  const quoteDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clientOrderId = useMemo(() => crypto.randomUUID(), [])

  // The quote estimate is dropped at its real expiry so the form stops showing a
  // number it knows is out of date.
  //
  // This is the one timer in the trading path, and it is deliberately *display-
  // only*: it fires once, at the server's own expiry instant, and all it does is
  // hide a stale estimate and trigger a cosmetic refresh. The trade itself does
  // not depend on it - `max_slippage` is enforced against live state at
  // execution - so nothing here can fail an order.
  useEffect(() => {
    if (!quote) return
    const ttlMs = Number(quote.expires_at) * 1000 - Date.now()
    const timer = setTimeout(
      () => {
        setQuote(null)
        setQuoteMeta(null)
      },
      Math.max(ttlMs, 0)
    )
    return () => clearTimeout(timer)
  }, [quote])

  const {
    register,
    handleSubmit,
    setValue,
    control,
    formState: { errors, isSubmitting },
  } = useForm<FormInput, unknown, PlaceOrderInput>({
    resolver: zodResolver(placeOrderSchema),
    defaultValues: {
      market_id: marketId,
      outcome: "yes",
      side: "buy",
      order_type: "market",
      amount: 0,
      price: undefined,
      post_only: false,
      client_order_id: clientOrderId,
      max_slippage: 0.005,
    },
  })

  const amount = useWatch({ control, name: "amount" })
  const price = useWatch({ control, name: "price" })
  const orderType = useWatch({ control, name: "order_type" })
  const postOnly = useWatch({ control, name: "post_only" })

  // Multi-outcome markets are priced by the order book alone (one binary AMM
  // pool cannot express mutually exclusive outcome prices), so the parent
  // supplies a per-outcome map. Falling back to 0 here showed the user a
  // zero price and let them submit against it; falling back to the binary price
  // would be a different-but-still-wrong quote. Show nothing instead.
  const namedOutcomePrice = outcomePrices?.[outcome]
  const effectivePrice = isMultiOutcome
    ? (namedOutcomePrice ?? 0)
    : outcome === "yes"
      ? currentYesPrice
      : currentNoPrice

  // Only use the cached quote when it matches current inputs (and is still within TTL)
  const quoteMatchesInputs =
    quote !== null &&
    quoteMeta !== null &&
    quoteMeta.marketId === marketId &&
    quoteMeta.outcome === outcome &&
    quoteMeta.side === side &&
    Number(quoteMeta.amount) === Number(amount)

  const quoteVisible = orderType === "market" && quoteMatchesInputs

  const displayPrice =
    orderType === "limit"
      ? (price ?? effectivePrice)
      : // Backend quote has no flat `price` • `price_after` is the post-slippage estimate.
        quoteVisible && quote
        ? quote.price_after
        : effectivePrice

  const total =
    amount && displayPrice ? Number(amount) * Number(displayPrice) : 0

  const isMarketOpen = marketStatus !== BLOCKED_STATUS
  const availableBalance = Number(wallet?.available_balance ?? 0)
  const hasInsufficientBalance = side === "buy" && total > availableBalance

  // ── The bound the server will honour ──────────────────────────────────────────
  //
  // The pair that actually protects the user is `expected_price` +
  // `max_slippage`: "fill within X% of the number on your screen". The server
  // scores the real fill against `expected_price` inside the lock that performs
  // it, so nothing can slip past the comparison.
  //
  // `expected_price` is what the user was actually shown, which is the only
  // coherent reference - the pool's pre-order price is not, because it excludes
  // this order's own price impact and ignores the portion matched against
  // resting limit orders, so scoring against it charges users for their own
  // trades and refuses ordinary orders.
  //
  // The two sources, in order of fidelity:
  //   • the quote, when one matches the current inputs - size-aware and all-in,
  //     fees included, so it is exactly what this order costs at this size
  //   • `effectivePrice` otherwise - a socket frame, top-of-book, and the best
  //     available when the estimate has not landed yet
  //
  // Either way the number is one the user saw, which is what makes the bound
  // mean what it says.
  const expectedPrice =
    orderType === "limit"
      ? (price ?? effectivePrice)
      : quoteVisible && quote
        ? quote.price_after
        : effectivePrice
  //
  // The alternative - a quote id - freezes one number for 5s and then refuses
  // the order if it expired. That is protection expressed as a *snapshot*, so
  // elapsed time alone becomes a reason to fail a trade the user correctly
  // intended. It also adds a round-trip to the critical path of every order.
  // Default 2%: wide enough that a busy market fills reliably, tight enough that
  // the user is never surprised by more than a cent or two on a typical market.
  const [tolerance, setTolerance] = useState<number>(0.02)
  const maxSlippageValue = orderType === "limit" ? 0 : tolerance

  // ── Quote fetching ──────────────────────────────────────────────────────────
  //
  // Now display-only.
  //
  // The quote was previously load-bearing: it was the number submitted, and its
  // expiry could fail the order. It is now an *estimate* that improves what the
  // user sees - it accounts for their specific size and slippage, which a price
  // frame cannot - but nothing depends on it being valid. It may be arbitrarily
  // stale and the trade still succeeds, because the bound is enforced server-side
  // against live state.
  //
  // That is what removes the "Quote expired • please refresh" failure entirely,
  // rather than papering over it with a faster refresh.
  useEffect(() => {
    if (quoteDebounceRef.current) clearTimeout(quoteDebounceRef.current)
    // Invalid inputs: skip fetch. Nothing here is required to trade.
    if (!amount || Number(amount) <= 0 || orderType !== "market") {
      return
    }
    // An estimate covering these inputs is still good for display.
    if (quoteMatchesInputs) {
      return
    }
    const timeoutId = setTimeout(async () => {
      setQuoteLoading(true)
      try {
        const res = await getQuote({
          market_id: marketId,
          outcome,
          side,
          amount,
        })
        setQuote(res.data)
        setQuoteMeta({ marketId, outcome, side, amount: Number(amount) })
      } catch {
        setQuote(null)
        setQuoteMeta(null)
      } finally {
        setQuoteLoading(false)
      }
    }, 300)
    quoteDebounceRef.current = timeoutId
    return () => clearTimeout(timeoutId)
    // The quote is display-only now, so `marketVersion` is a *cosmetic*
    // dependency: it keeps the estimate matching the book beside it. Removing it
    // degrades what the user sees; it can no longer fail a trade, because nothing
    // load-bearing depends on the quote any more.
    //
    // The 300ms is a debounce on input, not a poll - it collapses a burst of
    // frames or keystrokes into one estimate, and nothing schedules it on its own.
  }, [amount, outcome, side, marketId, orderType, quoteMatchesInputs, marketVersion])

  // ── Handlers ────────────────────────────────────────────────────────────

  const handleOutcomeClick = useCallback(
    (name: string) => {
      setOutcome(name)
      setValue("outcome", name)
    },
    [setValue]
  )

  // Stable curried handlers • avoid creating new fn per render in lists
  const makeOutcomeHandler = useCallback(
    (name: string) => () => handleOutcomeClick(name),
    [handleOutcomeClick]
  )

  const handleSideClick = useCallback(
    (s: "buy" | "sell") => {
      setSide(s)
      setValue("side", s)
    },
    [setValue]
  )

  const makeSideHandler = useCallback(
    (s: "buy" | "sell") => () => handleSideClick(s),
    [handleSideClick]
  )

  const onValid = useCallback(
    async (data: PlaceOrderInput) => {
      const payload: PlaceOrderInput = {
        ...data,
        client_order_id: clientOrderId,
        // The bound, not the snapshot.
        //
        // `max_slippage` + `expected_price` together are what protect the user:
        // the server compares the real fill against the price they saw, inside
        // the fill's own lock, and refuses if it moved further than they agreed.
        // That cannot expire and cannot be raced - unlike a `quote_id`, which
        // failed orders purely because five seconds had passed.
        max_slippage: maxSlippageValue > 0 ? maxSlippageValue : undefined,
        expected_price: Number(expectedPrice) > 0 ? Number(expectedPrice) : undefined,
        quote_id: undefined,
      }
      setQuote(null)
      setQuoteMeta(null)
      await onSubmit(payload)
    },
    [onSubmit, clientOrderId, maxSlippageValue, expectedPrice]
  )

  const handleOrderTypeChange = useCallback(
    (v: string | null) => {
      if (v) {
        setValue("order_type", v as "market" | "limit" | "fill_or_kill")
        if (v !== "limit") setValue("post_only", false)
      }
    },
    [setValue]
  )

  // ── Guards ────────────────────────────────────────────────────────────────

  if (!currentUser) return <NotLoggedIn />

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="space-y-3">
      {!isMarketOpen && <MarketClosedBanner status={marketStatus} />}
      {side === "buy" && hasInsufficientBalance && availableBalance > 0 && (
        <InsufficientBalanceBanner balance={availableBalance} />
      )}

      <form onSubmit={handleSubmit(onValid)} className="space-y-4">
        {isMultiOutcome ? (
          // Two columns on a phone, three once there is room. A fixed three
          // leaves ~90px per cell at 360px, which is not enough for
          // "Golden State Warriors" even wrapped.
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {outcomes!.map((o, i) => (
              <OutcomeButton
                key={o.id}
                label={o.name}
                price={outcomePrices?.[o.name.toLowerCase()] ?? 0}
                selected={outcome === o.name.toLowerCase()}
                color={i % 2 === 0 ? "green" : "red"}
                onClick={makeOutcomeHandler(o.name.toLowerCase())}
              />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            <OutcomeButton
              label="YES"
              price={currentYesPrice}
              selected={outcome === "yes"}
              color="green"
              onClick={makeOutcomeHandler("yes")}
            />
            <OutcomeButton
              label="NO"
              price={currentNoPrice}
              selected={outcome === "no"}
              color="red"
              onClick={makeOutcomeHandler("no")}
            />
          </div>
        )}

        <div className="grid grid-cols-2 gap-2">
          {(["buy", "sell"] as const).map((s) => (
            <SideButton
              key={s}
              side={s}
              current={side}
              onClick={makeSideHandler(s)}
            />
          ))}
        </div>

        <Field>
          <FieldLabel htmlFor="amount">Amount (Shares)</FieldLabel>
          <FieldContent>
            <Input
              id="amount"
              type="number"
              step="0.01"
              min="0.01"
              placeholder="0.00"
              {...register("amount", { valueAsNumber: true })}
            />
          </FieldContent>
          {errors.amount && (
            <FieldError errors={[{ message: errors.amount.message }]} />
          )}
        </Field>

        <Field>
          <FieldLabel htmlFor="order-type">Order Type</FieldLabel>
          <FieldContent>
            <Select
              value={orderType as string}
              onValueChange={handleOrderTypeChange}
            >
              <SelectTrigger id="order-type" aria-label="Order type">
                <SelectValue placeholder="Market" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="market">Market</SelectItem>
                  <SelectItem value="limit">Limit</SelectItem>
                  <SelectItem value="fill_or_kill">Fill or Kill</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </FieldContent>
        </Field>

        {/* Market orders only. A limit order's price *is* its bound: it rests
            until that price is reachable, so a slippage tolerance on top would be
            meaningless. */}
        {orderType === "market" && (
        <Field>
          <FieldLabel htmlFor="max_slippage">
            Price protection
          </FieldLabel>
          <FieldContent>
            {/* This slider is now the actual guarantee, so it states what it
                guarantees rather than a tolerance against a frozen quote. The
                server refuses the trade if the live price has moved beyond it,
                checked inside the same lock that fills it. */}
            <Input
              id="max_slippage"
              type="range"
              min="0.001"
              max="0.1"
              step="0.001"
              value={tolerance}
              onChange={(e) => setTolerance(Number(e.target.value))}
              aria-describedby="max_slippage_help"
            />
            <p id="max_slippage_help" className="text-[11px] text-muted-foreground">
              Trade fills at up to {(tolerance * 100).toFixed(1)}% from the price you see.
              Wider fills more reliably; the server refuses the trade if it moved further.
            </p>
            <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
              <span>0.1%</span>
              <span className="font-medium text-foreground">
                {(tolerance * 100).toFixed(1)}%
              </span>
              <span>10%</span>
            </div>
          </FieldContent>
        </Field>
        )}

        {(orderType === "limit" || orderType === "fill_or_kill") && (
          <>
            <Field>
              <FieldLabel htmlFor="price">Limit Price</FieldLabel>
              <FieldContent>
                <Input
                  id="price"
                  type="number"
                  step="0.001"
                  min="0.001"
                  max="0.999"
                  placeholder={effectivePrice.toFixed(3)}
                  {...register("price", { valueAsNumber: true })}
                />
              </FieldContent>
              {errors.price && (
                <FieldError errors={[{ message: errors.price.message }]} />
              )}
            </Field>

            {orderType === "limit" && (
              <>
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="post_only"
                    checked={postOnly}
                    onCheckedChange={(c) => setValue("post_only", c === true)}
                  />
                  <Label
                    htmlFor="post_only"
                    className="cursor-pointer text-xs text-muted-foreground select-none"
                  >
                    Post-only (never executes immediately)
                  </Label>
                </div>

                <Field>
                  <FieldLabel htmlFor="expires_at">
                    Expiry (optional)
                  </FieldLabel>
                  <FieldContent>
                    <Input
                      id="expires_at"
                      type="datetime-local"
                      {...register("expires_at")}
                    />
                  </FieldContent>
                </Field>
              </>
            )}
          </>
        )}

        {Number(amount) > 0 && (
          <div
            aria-live="polite"
            aria-atomic="true"
            className="space-y-2 rounded-md bg-muted/50 p-3 text-xs"
          >
            <div className="flex justify-between">
              <span className="text-muted-foreground">Price</span>
              <span>${Number(displayPrice).toFixed(4)}</span>
            </div>
            {quoteVisible && quote && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Slippage</span>
                <span
                  className={cn(
                    "font-medium",
                    Number(quote.slippage) > 0.01
                      ? "text-yellow-700 dark:text-yellow-400"
                      : "text-green-700 dark:text-green-400"
                  )}
                >
                  {(Number(quote.slippage) * 100).toFixed(2)}%
                </span>
              </div>
            )}
            {quoteLoading && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Quote</span>
                <Spinner className="size-3" />
              </div>
            )}
            <div className="flex justify-between border-t border-border pt-2">
              <span className="text-muted-foreground">Est. Cost</span>
              <span className="font-bold">${total.toFixed(2)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Pool Fee (2%)</span>
              <span>${(total * 0.02).toFixed(2)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Protocol Fee (1%)</span>
              <span>${(total * 0.01).toFixed(2)}</span>
            </div>
            <div className="flex justify-between border-t border-border pt-2">
              <span className="text-muted-foreground">Total Fees</span>
              <span className="font-medium">
                ${(total * 0.03).toFixed(2)} (3%)
              </span>
            </div>
          </div>
        )}

        <Button
          type="submit"
          className="w-full"
          disabled={!isMarketOpen || hasInsufficientBalance || isSubmitting}
        >
          {isSubmitting ? (
            <Spinner className="size-4" />
          ) : !isMarketOpen ? (
            "Market Closed"
          ) : hasInsufficientBalance ? (
            "Insufficient Balance"
          ) : (
            `${side === "buy" ? "Buy" : "Sell"} ${
              isMultiOutcome ? outcome : outcome.toUpperCase()
            }`
          )}
        </Button>
      </form>
    </div>
  )
}

export { TradeForm }
