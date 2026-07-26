"use client"

import { useCallback, useEffect, useMemo, useRef, useState, memo } from "react"
import { useForm } from "react-hook-form"
import { valibotResolver } from "@hookform/resolvers/valibot"
import { InferInput } from "valibot"
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
import { PlaceOrderSchema, type PlaceOrderInput } from "@/lib/schemas/trading"
import { getQuote } from "@/lib/api/orders"
import type { Outcome, QuoteResponse } from "@/lib/types/api"

type FormInput = InferInput<typeof PlaceOrderSchema>

interface TradeFormProps {
  marketId: string
  currentYesPrice: number
  currentNoPrice: number
  outcomes?: Outcome[]
  onSubmit: (order: PlaceOrderInput) => Promise<void>
  disabled?: boolean
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



function TradeForm({ marketId, currentYesPrice, currentNoPrice, outcomes, onSubmit, disabled }: TradeFormProps) {
  const isMultiOutcome = outcomes && outcomes.length > 2
  const [outcome, setOutcome] = useState<string>(isMultiOutcome ? (outcomes?.[0]?.name?.toLowerCase() ?? "yes") : "yes")
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
    resolver: valibotResolver(PlaceOrderSchema),
    defaultValues: {
      market_id: marketId,
      outcome: "yes",
      side: "buy",
      order_type: "market",
      amount: undefined,
      price: undefined,
      post_only: false,
      client_order_id: clientOrderId,
    },
  })

  const amount = watch("amount")
  const price = watch("price")
  const orderType = watch("order_type")

  const effectivePrice = isMultiOutcome
    ? (outcome === "yes" ? currentYesPrice : outcome === "no" ? currentNoPrice : 0)
    : outcome === "yes"
    ? currentYesPrice
    : currentNoPrice
  const displayPrice = orderType === "limit" ? (price ?? (quote?.price ?? effectivePrice)) : (quote?.price ?? effectivePrice)
  const total = amount && displayPrice ? amount * displayPrice : 0

  // ── Quote fetching ──

  useEffect(() => {
    if (quoteDebounceRef.current) clearTimeout(quoteDebounceRef.current)
    if (!amount || amount <= 0 || orderType !== "market") {
      setQuote(null)
      return
    }
    quoteDebounceRef.current = setTimeout(async () => {
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
    return () => {
      if (quoteDebounceRef.current) clearTimeout(quoteDebounceRef.current)
    }
  }, [amount, outcome, side, marketId, orderType])

  const handleOutcomeClick = useCallback(
    (name: string) => {
      setOutcome(name)
      setValue("outcome", name)
    },
    [setValue]
  )

  const handleSideClick = useCallback(
    (s: "buy" | "sell") => {
      setSide(s)
      setValue("side", s)
    },
    [setValue]
  )

  const onValid = useCallback(
    async (data: PlaceOrderInput) => {
      const payload: PlaceOrderInput = {
        ...data,
        client_order_id: clientOrderId,
        max_slippage: 0.005,
        quote_id: quote?.quote_id,
      }
      setQuote(null)
      await onSubmit(payload)
    },
    [onSubmit, clientOrderId, quote]
  )

  return (
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
              onClick={() => handleOutcomeClick(o.name.toLowerCase())}
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
            onClick={() => handleOutcomeClick("yes")}
          />
          <OutcomeButton
            label="NO"
            price={currentNoPrice}
            selected={outcome === "no"}
            color="red"
            onClick={() => handleOutcomeClick("no")}
          />
        </div>
      )}

      <div className="grid grid-cols-2 gap-2">
        {(["buy", "sell"] as const).map((s) => (
          <SideButton key={s} side={s} current={side} onClick={() => handleSideClick(s)} />
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
            onValueChange={(v) => {
              if (v) setValue("order_type", v as "market" | "limit" | "fill_or_kill")
              if (v !== "limit") setValue("post_only", false)
            }}
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
                <Label htmlFor="post_only" className="text-[11px] text-muted-foreground cursor-pointer select-none">
                  Post-only (never executes immediately)
                </Label>
              </div>

              <Field>
                <FieldLabel htmlFor="expires_at">Expiry (optional)</FieldLabel>
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

      {amount > 0 && (
        <div className="rounded-md bg-muted/50 p-3 text-xs space-y-2">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Price</span>
            <span>${displayPrice.toFixed(4)}</span>
          </div>
          {quote && (
            <div className="flex justify-between">
              <span className="text-muted-foreground">Slippage</span>
              <span className={cn(
                "font-medium",
                quote.slippage > 0.01 ? "text-yellow-500" : "text-green-500"
              )}>
                {(quote.slippage * 100).toFixed(2)}%
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
        </div>
      )}

      <Button type="submit" className="w-full" disabled={disabled || isSubmitting}>
        {isSubmitting ? <Spinner className="size-4" /> : `${side === "buy" ? "Buy" : "Sell"} ${isMultiOutcome ? outcome : outcome.toUpperCase()}`}
      </Button>
    </form>
  )
}

export { TradeForm }
