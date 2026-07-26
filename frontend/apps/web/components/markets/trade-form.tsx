"use client"

import { useCallback, useState, memo } from "react"
import { useForm } from "react-hook-form"
import { valibotResolver } from "@hookform/resolvers/valibot"
import { InferInput } from "valibot"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Spinner } from "@workspace/ui/components/spinner"
import {
  Field,
  FieldContent,
  FieldError,
  FieldLabel,
} from "@workspace/ui/components/field"
import { cn } from "@workspace/ui/lib/utils"
import { PlaceOrderSchema, type PlaceOrderInput } from "@/lib/schemas/trading"
import type { Outcome } from "@/lib/types/api"

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

const OrderTypeButton = memo(function OrderTypeButton({
  type,
  current,
  onClick,
}: {
  type: "market" | "limit"
  current: "market" | "limit"
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md border px-3 py-1 text-xs font-medium transition-colors",
        type === current
          ? "border-primary bg-primary/10 text-primary"
          : "border-border text-muted-foreground hover:bg-muted"
      )}
    >
      {type}
    </button>
  )
})

function TradeForm({ marketId, currentYesPrice, currentNoPrice, outcomes, onSubmit, disabled }: TradeFormProps) {
  const isMultiOutcome = outcomes && outcomes.length > 2
  const [outcome, setOutcome] = useState<string>(isMultiOutcome ? (outcomes?.[0]?.name?.toLowerCase() ?? "yes") : "yes")
  const [side, setSide] = useState<"buy" | "sell">("buy")

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
  const displayPrice = orderType === "limit" ? (price ?? effectivePrice) : effectivePrice
  const total = amount && displayPrice ? amount * displayPrice : 0

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

  const handleOrderTypeClick = useCallback(
    (t: "market" | "limit") => {
      setValue("order_type", t)
    },
    [setValue]
  )

  const onValid = useCallback(
    async (data: PlaceOrderInput) => {
      await onSubmit(data)
    },
    [onSubmit]
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

      <div className="flex gap-2">
        {(["market", "limit"] as const).map((t) => (
          <OrderTypeButton key={t} type={t} current={orderType as "market" | "limit"} onClick={() => handleOrderTypeClick(t)} />
        ))}
      </div>

      {orderType === "limit" && (
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
      )}

      {amount > 0 && (
        <div className="rounded-md bg-muted/50 p-3 text-xs">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Price</span>
            <span>${displayPrice.toFixed(4)}</span>
          </div>
          <div className="mt-2 flex justify-between border-t border-border pt-2">
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
