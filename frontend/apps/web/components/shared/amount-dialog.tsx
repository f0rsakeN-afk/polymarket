"use client"

import { useCallback, useState } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { sileo } from "sileo"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Spinner } from "@workspace/ui/components/spinner"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@workspace/ui/components/alert-dialog"
import { Field, FieldContent, FieldError } from "@workspace/ui/components/field"
import { z } from "zod"

const amountSchema = z.object({
  amount: z.number().min(0.01, "Minimum amount is $0.01"),
})

type AmountInput = z.infer<typeof amountSchema>

interface AmountDialogProps {
  title: string
  description: string
  trigger: React.ReactNode
  onConfirm: (amount: number) => Promise<void>
}

export function AmountDialog({ title, description, trigger, onConfirm }: AmountDialogProps) {
  const [open, setOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const { register, handleSubmit, reset, formState: { errors } } = useForm<AmountInput>({
    resolver: zodResolver(amountSchema),
  })

  const handleOpenChange = useCallback((next: boolean) => {
    setOpen(next)
    if (!next) reset()
  }, [reset])

  const handleConfirm = useCallback(async (data: AmountInput) => {
    setSubmitting(true)
    try {
      await onConfirm(data.amount)
      sileo.success({ title: `${title} successful` })
      reset()
      setOpen(false)
    } catch (e) {
      sileo.error({
        title: `${title} failed`,
        description: e instanceof Error ? e.message : "Unknown error",
      })
    } finally {
      setSubmitting(false)
    }
  }, [onConfirm, title, reset])

  return (
    <AlertDialog open={open} onOpenChange={handleOpenChange}>
      <AlertDialogTrigger render={trigger as React.ReactElement} />
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <form onSubmit={handleSubmit(handleConfirm)} className="space-y-4 mt-4">
          <Field>
            <FieldContent>
              <Input
                type="number"
                step="0.01"
                min="0.01"
                placeholder="0.00"
                className="h-9"
                {...register("amount", { valueAsNumber: true })}
              />
            </FieldContent>
            {errors.amount && (
              <FieldError errors={[{ message: errors.amount.message ?? "Invalid amount" }]} />
            )}
          </Field>
          <AlertDialogFooter>
            <AlertDialogCancel type="button" onClick={() => reset()}>Cancel</AlertDialogCancel>
            <AlertDialogAction render={<Button type="submit" disabled={submitting}>
              {submitting ? <Spinner className="size-4" /> : "Confirm"}
            </Button>} />
          </AlertDialogFooter>
        </form>
      </AlertDialogContent>
    </AlertDialog>
  )
}
