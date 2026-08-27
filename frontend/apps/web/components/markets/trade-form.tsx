"use client"

import { useCallback, useEffect, useMemo, useRef, useState, memo } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Spinner } from "@workspace/ui/components/spinner"
import { Checkbox } from "@workspace/ui/components/checkbox"
import { Label } from "@workspace/ui/components/label"
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from "@workspace/ui/components/select"
import {
  Field,
  FieldContent,
  FieldError,
  FieldLabel,
} from "@workspace/ui/components/field"

import { cn } from "@workspace/ui/lib/utils"
import { placeOrderSchema, type PlaceOrderInput, z } from "@/lib/schemas/trading"
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
  outcomes?: Outcome[]
  marketStatus: string
  onSubmit: (order: PlaceOrderInput) => Promise<void>
}

// Only resolved markets block trading. Active, closed, and dispute_window all allow trading.
const BLOCKED_STATUS = "resolved"

function NotLoggedIn() {
  return (
    <div className="py-6 text-center space-y-2">
      <p className="text-sm text-muted-foreground">Sign in to start trading</p>
      <Link
        href="/login"
        className="block w-full rounded-md border border-primary bg-primary px-4 py-2 text-sm font-medium text-center text-primary-foreground hover:bg-primary/90 transition-colors"
      >
        Sign In
      </Link>
      <p className="text-xs text-muted-foreground">
        New here?{" "}
        <Link href="/signup" className="underline underline-offset-2 hover:text-foreground">
          Create account
        </Link>
      </p>
    </div>
  )
}

function MarketClosedBanner({ status }: { status: string }) {
  return (
    <div className="rounded-md border border-yellow-500/20 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-600 dark:text-yellow-400">
      Market is <span className="font-medium">{status}</span> — trading is disabled
    </div>
  )
}

function InsufficientBalanceBanner({ balance }: { balance: number }) {
  return (
    <div className="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-600 dark:text-red-400">
      Insufficient balance — you have{" "}
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
      className={cn(
        "rounded-lg border p-2.5 text-center transition-colors",
        selected
          ? color === "green"
            ? "border-green-500/50 bg-green-500/10 text-green-500"
            : "border-red-500/50 bg-red-500/10 text-red-500"
          : "border-border bg-card text-muted-foreground hover:bg-muted"
      )}
    >
      <div className="text-sm font-bold">{label}</div>
      <div className="text-xs">${price.toFixed(2)}</div>
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
      className={cn(
        "rounded-md border py-1.5 text-xs font-semibold uppercase transition-colors",
        side === current
          ? side === "buy"
            ? "border-green-500/50 bg-green-500/10 text-green-500"
            : "border-red-500/50 bg-red-500/10 text-red-500"
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
  outcomes,
  marketStatus,
  onSubmit,
}: TradeFormProps) {
  const { data: currentUser } = useCurrentUser()
  const { data: wallet } = useWallet()

  const isMultiOutcome = outcomes && outcomes.length > 2
  const [outcome, setOutcome] = useState<string>(
    isMultiOutcome ? (outcomes?.[0]?.name?.toLowerCase() ?? "yes") : "yes"
  )
  const [side, setSide] = useState<"buy" | "sell">("buy")
  const [quote, setQuote] = useState<QuoteResponse | null>(null)
  const [quoteLoading, setQuoteLoading] = useState(false)
  const quoteDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clientOrderId = useMemo(() => crypto.randomUUID(), [])

  const {
    register,
    handleSubmit,
    watch,
    setValue,
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

  const amount = watch("amount")
  const price = watch("price")
  const orderType = watch("order_type")

  const effectivePrice = isMultiOutcome
    ? outcome === "yes"
      ? currentYesPrice
      : outcome === "no"
      ? currentNoPrice
      : 0  // multi-outcome named prices require per-outcome price map from parent
    : outcome === "yes"
    ? currentYesPrice
    : currentNoPrice

  const displayPrice =
    orderType === "limit"
      ? price ?? quote?.price ?? effectivePrice
      : quote?.price ?? effectivePrice

  const total = amount && displayPrice ? Number(amount) * Number(displayPrice) : 0

  const isMarketOpen = marketStatus !== BLOCKED_STATUS
  const availableBalance = Number(wallet?.available_balance ?? 0)
  const hasInsufficientBalance = side === "buy" && total > availableBalance

  // ── Quote fetching ──────────────────────────────────────────────────────────

  useEffect(() => {
    if (quoteDebounceRef.current) clearTimeout(quoteDebounceRef.current)
    if (!amount || Number(amount) <= 0 || orderType !== "market") {
      setQuote(null)
      return
    }
    const timeoutId = setTimeout(async () => {
      setQuoteLoading(true)
      try {
        const res = await getQuote({ market_id: marketId, outcome, side, amount })
        setQuote(res.data)
      } catch {
        setQuote(null)
      } finally {
        setQuoteLoading(false)
      }
    }, 300)
    quoteDebounceRef.current = timeoutId
    return () => clearTimeout(timeoutId)
  }, [amount, outcome, side, marketId, orderType])

  // ── Handlers ────────────────────────────────────────────────────────────

  const handleOutcomeClick = useCallback(
    (name: string) => {
      setOutcome(name)
      setValue("outcome", name)
    },
    [setValue]
  )

  // Stable curried handlers — avoid creating new fn per render in lists
  const makeOutcomeHandler = useCallback((name: string) => () => handleOutcomeClick(name), [handleOutcomeClick])

  const handleSideClick = useCallback(
    (s: "buy" | "sell") => {
      setSide(s)
      setValue("side", s)
    },
    [setValue]
  )

  const makeSideHandler = useCallback((s: "buy" | "sell") => () => handleSideClick(s), [handleSideClick])

  const onValid = useCallback(
    async (data: PlaceOrderInput) => {
      const payload: PlaceOrderInput = {
        ...data,
        client_order_id: clientOrderId,
        quote_id: quote?.quote_id,
      }
      setQuote(null)
      await onSubmit(payload)
    },
    [onSubmit, clientOrderId, quote]
  )

  const handleOrderTypeChange = useCallback((v: string) => {
    if (v) setValue("order_type", v as "market" | "limit" | "fill_or_kill")
    if (v !== "limit") setValue("post_only", false)
  }, [setValue])

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
          <div className="grid grid-cols-3 gap-2">
            {outcomes!.map((o, i) => (
              <OutcomeButton
                key={o.id}
                label={o.name}
                price={i === 0 ? currentYesPrice : i === 1 ? currentNoPrice : 0}
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
          {((["buy", "sell"]) as const).map((s) => (
            <SideButton key={s} side={s} current={side} onClick={makeSideHandler(s)} />
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
          {errors.amount && <FieldError errors={[{ message: errors.amount.message }]} />}
        </Field>

        <Field>
          <FieldLabel>Order Type</FieldLabel>
          <FieldContent>
            <Select
              value={orderType as string}
              onValueChange={handleOrderTypeChange}
            >
              <SelectTrigger>
                <SelectValue placeholder="Market" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="market">Market</SelectItem>
                <SelectItem value="limit">Limit</SelectItem>
                <SelectItem value="fill_or_kill">Fill or Kill</SelectItem>
              </SelectContent>
            </Select>
          </FieldContent>
        </Field>

        <Field>
          <FieldLabel htmlFor="max_slippage">
            Slippage Tolerance — {(Number(watch("max_slippage") ?? 0.005) * 100).toFixed(1)}%
          </FieldLabel>
          <FieldContent>
            <Input
              id="max_slippage"
              type="range"
              min="0.001"
              max="0.1"
              step="0.001"
              {...register("max_slippage", { valueAsNumber: true })}
            />
            <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
              <span>0.1%</span>
              <span className="font-medium text-foreground">
                {(Number(watch("max_slippage") ?? 0.005) * 100).toFixed(1)}%
              </span>
              <span>10%</span>
            </div>
          </FieldContent>
          {errors.max_slippage && (
            <FieldError errors={[{ message: errors.max_slippage.message }]} />
          )}
        </Field>

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
              {errors.price && <FieldError errors={[{ message: errors.price.message }]} />}
            </Field>

            {orderType === "limit" && (
              <>
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="post_only"
                    checked={watch("post_only")}
                    onCheckedChange={(c) => setValue("post_only", c === true)}
                  />
                  <Label
                    htmlFor="post_only"
                    className="text-[11px] text-muted-foreground cursor-pointer select-none"
                  >
                    Post-only (never executes immediately)
                  </Label>
                </div>

                <Field>
                  <FieldLabel htmlFor="expires_at">Expiry (optional)</FieldLabel>
                  <FieldContent>
                    <Input id="expires_at" type="datetime-local" {...register("expires_at")} />
                  </FieldContent>
                </Field>
              </>
            )}
          </>
        )}

        {Number(amount) > 0 && (
          <div className="rounded-md bg-muted/50 p-3 text-xs space-y-2">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Price</span>
              <span>${Number(displayPrice).toFixed(4)}</span>
            </div>
            {quote && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Slippage</span>
                <span
                  className={cn(
                    "font-medium",
                    Number(quote.slippage) > 0.01 ? "text-yellow-500" : "text-green-500"
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
              <span className="font-medium">${(total * 0.03).toFixed(2)} (3%)</span>
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
