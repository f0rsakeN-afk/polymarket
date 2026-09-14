"use client"

import { useCallback, useState } from "react"
import { useForm, useWatch } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Spinner } from "@workspace/ui/components/spinner"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@workspace/ui/components/dialog"
import { cn } from "@workspace/ui/lib/utils"
import { useCreateAlert } from "@/hooks/api/use-alerts"
import { useCurrentUser } from "@/hooks/use-auth"
import { sileo } from "sileo"
import Link from "next/link"

const QUICK_FILL_OPTIONS = ["yes", "no"] as const
const QUICK_FILL_CONDITIONS = ["above", "below"] as const

const alertSchema = z.object({
  outcome: z.enum(["yes", "no"]),
  condition: z.enum(["above", "below"]),
  trigger_price: z.number().min(0.01, "Min 0.01").max(0.99, "Max 0.99"),
})

type AlertInput = z.infer<typeof alertSchema>

function AlertDialog({ marketId, currentYesPrice, currentNoPrice }: {
  marketId: string
  currentYesPrice: number
  currentNoPrice: number
}) {
  const { data: currentUser } = useCurrentUser()
  const [open, setOpen] = useState(false)
  const { mutateAsync: createAlert, isPending } = useCreateAlert()

  const { register, handleSubmit, setValue, control, formState: { errors }, reset } = useForm<AlertInput>({
    resolver: zodResolver(alertSchema),
    defaultValues: { outcome: "yes", condition: "above", trigger_price: currentYesPrice },
  })

  const outcome = useWatch({ control, name: "outcome" })
  const condition = useWatch({ control, name: "condition" })

  const onSubmit = useCallback(async (data: AlertInput) => {
    try {
      await createAlert({ market_id: marketId, ...data })
      sileo.success({ title: "Alert created" })
      reset()
      setOpen(false)
    } catch (e) {
      sileo.error({ title: "Failed to create alert", description: e instanceof Error ? e.message : "Unknown error" })
    }
  }, [createAlert, marketId, reset])

  const quickFill = useCallback((price: number) => {
    setValue("trigger_price", price)
  }, [setValue])

  const handleOutcomeClick = useCallback((o: typeof QUICK_FILL_OPTIONS[number]) => {
    setValue("outcome", o)
  }, [setValue])

  const handleConditionClick = useCallback((c: typeof QUICK_FILL_CONDITIONS[number]) => {
    setValue("condition", c)
  }, [setValue])

  const makeOutcomeHandler = useCallback((o: typeof QUICK_FILL_OPTIONS[number]) => () => handleOutcomeClick(o), [handleOutcomeClick])
  const makeConditionHandler = useCallback((c: typeof QUICK_FILL_CONDITIONS[number]) => () => handleConditionClick(c), [handleConditionClick])
  const makeQuickFillHandler = useCallback((price: number) => () => quickFill(price), [quickFill])

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger className="w-full mt-3 inline-flex items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium ring-offset-background transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50">
        {currentUser ? "Create Price Alert" : "Sign in for Price Alerts"}
      </DialogTrigger>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="text-sm font-semibold">Create Price Alert</DialogTitle>
          <DialogDescription className="sr-only">
            Set a price alert for this market. Choose an outcome, a condition, and a trigger price.
          </DialogDescription>
        </DialogHeader>

        {!currentUser ? (
          <div className="py-4 text-center space-y-3">
            <p className="text-sm text-muted-foreground">Sign in to create price alerts</p>
            <Link
              href="/login"
              className="block w-full rounded-md border border-primary bg-primary px-4 py-2 text-sm font-medium text-center text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Sign In
            </Link>
          </div>
        ) : (

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {/* Outcome */}
          <div>
            <span id="alert-outcome-label" className="text-xs text-muted-foreground mb-1.5 block">Outcome</span>
            <div role="group" aria-labelledby="alert-outcome-label" className="grid grid-cols-2 gap-2">
              {QUICK_FILL_OPTIONS.map((o) => (
                <button
                  key={o}
                  type="button"
                  onClick={makeOutcomeHandler(o)}
                  aria-pressed={outcome === o}
                  className={cn(
                    "min-h-9 rounded-xl border py-2 text-xs font-semibold uppercase transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    outcome === o
                      ? o === "yes"
                        ? "border-green-600/50 bg-green-600/10 text-green-700 dark:text-green-400"
                        : "border-red-600/50 bg-red-600/10 text-red-700 dark:text-red-400"
                      : "border-border bg-muted text-muted-foreground"
                  )}
                >
                  {o}
                </button>
              ))}
            </div>
          </div>

          {/* Condition */}
          <div>
            <span id="alert-condition-label" className="text-xs text-muted-foreground mb-1.5 block">Alert when price goes</span>
            <div role="group" aria-labelledby="alert-condition-label" className="grid grid-cols-2 gap-2">
              {QUICK_FILL_CONDITIONS.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={makeConditionHandler(c)}
                  aria-pressed={condition === c}
                  className={cn(
                    "min-h-9 rounded-xl border py-2 text-xs font-semibold capitalize transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    condition === c
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border bg-muted text-muted-foreground"
                  )}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>

          {/* Price */}
          <div>
            <label htmlFor="alert-trigger-price" className="text-xs text-muted-foreground mb-1.5 block">Trigger price</label>
            <Input
              id="alert-trigger-price"
              type="number"
              step="0.01"
              min="0.01"
              max="0.99"
              required
              aria-required="true"
              className="font-mono"
              {...register("trigger_price", { valueAsNumber: true })}
            />
            {errors.trigger_price && (
              <p role="alert" className="mt-1 text-xs text-destructive">{errors.trigger_price.message}</p>
            )}
          </div>

          {/* Quick fill */}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={makeQuickFillHandler(currentYesPrice)}
              className="min-h-9 flex-1 rounded-md border border-border text-xs font-medium text-muted-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              YES ${currentYesPrice.toFixed(2)}
            </button>
            <button
              type="button"
              onClick={makeQuickFillHandler(currentNoPrice)}
              className="min-h-9 flex-1 rounded-md border border-border text-xs font-medium text-muted-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              NO ${currentNoPrice.toFixed(2)}
            </button>
          </div>

          <Button type="submit" className="w-full" disabled={isPending}>
            {isPending ? <Spinner className="size-4" /> : "Create Alert"}
          </Button>
        </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

export { AlertDialog }
