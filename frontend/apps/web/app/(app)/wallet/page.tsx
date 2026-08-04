"use client"

import { useState } from "react"
import { useWallet, useDeposit, useWithdraw } from "@/hooks/api/use-wallet"
import { WalletBalance } from "@/components/wallet/wallet-balance"
import { Button } from "@workspace/ui/components/button"
import { Dialog, DialogContent, DialogTitle } from "@workspace/ui/components/dialog"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { depositSchema, withdrawSchema } from "@/lib/schemas/trading"
import type { DepositInput, WithdrawInput } from "@/lib/schemas/trading"
import { sileo } from "sileo"

export const metadata = { robots: { index: false, follow: false } }

function AmountForm({
  title,
  schema,
  submitLabel,
  onSubmit,
  loading,
}: {
  title: string
  schema: typeof depositSchema | typeof withdrawSchema
  submitLabel: string
  onSubmit: (data: DepositInput | WithdrawInput) => void
  loading: boolean
}) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<DepositInput | WithdrawInput>({
    resolver: zodResolver(schema),
  })

  return (
    <form
      onSubmit={handleSubmit((data) => {
        onSubmit(data)
        reset()
      })}
      className="grid gap-4"
    >
      <div className="grid gap-2">
        <Label htmlFor="amount">Amount (USD)</Label>
        <Input
          id="amount"
          type="number"
          step="0.01"
          min="1"
          placeholder="0.00"
          {...register("amount", { valueAsNumber: true })}
        />
        {errors.amount && (
          <p className="text-xs text-destructive">{String(errors.amount.message)}</p>
        )}
      </div>
      <Button type="submit" disabled={loading}>
        {submitLabel}
      </Button>
    </form>
  )
}

export default function WalletPage() {
  const { data: wallet, isLoading } = useWallet()
  const deposit = useDeposit()
  const withdraw = useWithdraw()
  const [depositOpen, setDepositOpen] = useState(false)
  const [withdrawOpen, setWithdrawOpen] = useState(false)

  const handleDeposit = (data: DepositInput) => {
    deposit.mutate(data, {
      onSuccess: () => {
        sileo.success({ title: "Deposit initiated" })
        setDepositOpen(false)
      },
      onError: () => sileo.error({ title: "Deposit failed" }),
    })
  }

  const handleWithdraw = (data: WithdrawInput) => {
    withdraw.mutate(data, {
      onSuccess: () => {
        sileo.success({ title: "Withdrawal initiated" })
        setWithdrawOpen(false)
      },
      onError: () => sileo.error({ title: "Withdrawal failed" }),
    })
  }

  return (
    <div className="p-8 max-w-md space-y-6">
      <h1 className="text-2xl font-semibold">Wallet</h1>

      <WalletBalance wallet={wallet ?? null} loading={isLoading} />

      <div className="flex gap-3">
        <Button onClick={() => setDepositOpen(true)}>Deposit</Button>
        <Button variant="outline" onClick={() => setWithdrawOpen(true)}>
          Withdraw
        </Button>
      </div>

      <Dialog open={depositOpen} onOpenChange={setDepositOpen}>
        <DialogContent>
          <DialogTitle>Deposit</DialogTitle>
          <AmountForm
            title="Deposit"
            schema={depositSchema}
            submitLabel="Deposit"
            onSubmit={handleDeposit}
            loading={deposit.isPending}
          />
        </DialogContent>
      </Dialog>

      <Dialog open={withdrawOpen} onOpenChange={setWithdrawOpen}>
        <DialogContent>
          <DialogTitle>Withdraw</DialogTitle>
          <AmountForm
            title="Withdraw"
            schema={withdrawSchema}
            submitLabel="Withdraw"
            onSubmit={handleWithdraw}
            loading={withdraw.isPending}
          />
        </DialogContent>
      </Dialog>
    </div>
  )
}
