"use client"

import { useCallback, useState } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Spinner } from "@workspace/ui/components/spinner"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@workspace/ui/components/dialog"
import { cn } from "@workspace/ui/lib/utils"
import { useCreateAlert } from "@/hooks/use-alerts"
import { sileo } from "sileo"

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
  const [open, setOpen] = useState(false)
  const { mutateAsync: createAlert, isPending } = useCreateAlert()

  const { register, handleSubmit, setValue, watch, formState: { errors }, reset } = useForm<AlertInput>({
    resolver: zodResolver(alertSchema),
    defaultValues: { outcome: "yes", condition: "above", trigger_price: currentYesPrice },
  })

  const outcome = watch("outcome")
  const condition = watch("condition")

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

  const quickFill = (price: number) => setValue("trigger_price", price)

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger>
        <Button variant="outline" size="sm" className="w-full mt-3">
          Create Price Alert
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[380px]">
        <DialogHeader>
          <DialogTitle className="text-sm">Create Price Alert</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {/* Outcome */}
          <div>
            <label className="text-xs text-muted-foreground mb-1.5 block">Outcome</label>
            <div className="grid grid-cols-2 gap-2">
              {(["yes", "no"] as const).map((o) => (
                <button
                  key={o}
                  type="button"
                  onClick={() => setValue("outcome", o)}
                  className={cn(
                    "py-2 rounded-lg border text-xs font-semibold uppercase transition-colors",
                    outcome === o
                      ? o === "yes"
                        ? "border-green-500 bg-green-500/10 text-green-500"
                        : "border-red-500 bg-red-500/10 text-red-500"
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
            <label className="text-xs text-muted-foreground mb-1.5 block">Alert when price goes</label>
            <div className="grid grid-cols-2 gap-2">
              {(["above", "below"] as const).map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setValue("condition", c)}
                  className={cn(
                    "py-2 rounded-lg border text-xs font-semibold capitalize transition-colors",
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
            <label className="text-xs text-muted-foreground mb-1.5 block">Trigger price</label>
            <Input
              type="number"
              step="0.01"
              min="0.01"
              max="0.99"
              className="font-mono"
              {...register("trigger_price", { valueAsNumber: true })}
            />
            {errors.trigger_price && (
              <p className="text-[10px] text-red-500 mt-1">{errors.trigger_price.message}</p>
            )}
          </div>

          {/* Quick fill */}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => quickFill(currentYesPrice)}
              className="flex-1 py-1.5 rounded border border-border text-[10px] font-medium text-muted-foreground hover:bg-muted transition-colors"
            >
              YES ${currentYesPrice.toFixed(2)}
            </button>
            <button
              type="button"
              onClick={() => quickFill(currentNoPrice)}
              className="flex-1 py-1.5 rounded border border-border text-[10px] font-medium text-muted-foreground hover:bg-muted transition-colors"
            >
              NO ${currentNoPrice.toFixed(2)}
            </button>
          </div>

          <Button type="submit" className="w-full" disabled={isPending}>
            {isPending ? <Spinner className="size-4" /> : "Create Alert"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export { AlertDialog }
