"use client"

import { useState, useCallback } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useWallet, useDeposit, useWithdraw } from "@/hooks/api/use-wallet"
import { useCurrentUser } from "@/hooks/use-auth"
import { useUserSocket } from "@/hooks/use-user-socket"
import { queryKeys } from "@/lib/api/queryKeys"
import { applyPrivateFeedResync } from "@/lib/ws-resync"
import { isUnauthorized } from "@/lib/api/client"
import { WalletBalance } from "@/components/wallet/wallet-balance"
import { Button } from "@workspace/ui/components/button"
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { depositSchema, withdrawSchema } from "@/schemas/wallet"
import type { DepositInput, WithdrawInput } from "@/schemas/wallet"

function AmountForm({
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
          <p className="text-xs text-destructive">
            {String(errors.amount.message)}
          </p>
        )}
      </div>
      <Button type="submit" disabled={loading}>
        {submitLabel}
      </Button>
    </form>
  )
}

/**
 * Frames after which the balance on screen is stale.
 *
 * There is no `wallet:update` message, and that is deliberate - a wallet is
 * derived from the ledger, so publishing a second source of truth for it would
 * mean reconciling two numbers that are supposed to be one. Instead the events
 * that actually move money invalidate the wallet directly:
 *
 *   • a fill          - funds lock converts to position
 *   • an expiry       - a lock is released and becomes available again
 *   • an order update - a lock is placed, resized, or filled
 *   • a position      - quantities change what is locked
 *
 * Getting this list wrong is silent in both directions: omit a frame and the
 * balance sits there lying, include a spurious one and the page refetches for
 * nothing. Both were previously wrong in the worst way - none of them were
 * handled at all, because this page had no socket subscription whatsoever, so a
 * trade landing in another tab left the balance showing the pre-trade number
 * with no way to tell it was stale.
 */
const WALLET_AFFECTING_FRAMES = new Set([
  "position:update",
  "order:fill",
  "order:expired",
  "order:update",
  "wallet:update",
])

export function WalletPageClient() {
  const { data: wallet, isLoading, error, isError } = useWallet()
  const { data: user } = useCurrentUser()
  const queryClient = useQueryClient()
  const deposit = useDeposit()
  const withdraw = useWithdraw()
  const [depositOpen, setDepositOpen] = useState(false)
  const [withdrawOpen, setWithdrawOpen] = useState(false)

  const handleWsMessage = useCallback(
    (payload: unknown) => {
      // The reconnect marker means the private feed has unmeasurable gaps, so
      // everything it is responsible for has to be re-read - including here.
      if (applyPrivateFeedResync(queryClient, payload)) return
      const type = (payload as { type?: string } | null)?.type
      if (type && WALLET_AFFECTING_FRAMES.has(type)) {
        // By prefix, not `queryKeys.wallet()` + filters - see the note there.
        queryClient.invalidateQueries({ queryKey: queryKeys.wallet() })
        queryClient.invalidateQueries({ queryKey: queryKeys.transactions() })
      }
    },
    [queryClient]
  )

  useUserSocket({
    userId: user?.id ?? "",
    onMessage: handleWsMessage,
    enabled: !!user?.id,
  })

  const handleDeposit = useCallback(
    (data: DepositInput) => {
      // Toasts (backend message) are emitted by useDeposit.
      deposit.mutate(data, {
        onSuccess: () => setDepositOpen(false),
      })
    },
    [deposit]
  )

  const handleWithdraw = useCallback(
    (data: WithdrawInput) => {
      // Toasts (backend message) are emitted by useWithdraw.
      withdraw.mutate(data, {
        onSuccess: () => setWithdrawOpen(false),
      })
    },
    [withdraw]
  )

  const openDeposit = useCallback(() => setDepositOpen(true), [])
  const openWithdraw = useCallback(() => setWithdrawOpen(true), [])

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Wallet</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">Manage deposits and withdrawals</p>
      </div>

      <WalletBalance
        wallet={wallet ?? null}
        loading={isLoading}
        // Only claim the user is unauthenticated when the server actually said so.
        // The gate disables this query for logged-out visitors, so a 401 is the
        // sole legitimate cause here; anything else is a failure, and calling it
        // an auth problem sends people to re-login for no reason.
        reason={isError && !isUnauthorized(error) ? "error" : "unauthenticated"}
      />

      <div className="flex gap-3">
        <Button onClick={openDeposit}>Deposit</Button>
        <Button variant="outline" onClick={openWithdraw}>
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
