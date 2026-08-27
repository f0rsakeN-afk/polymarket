"use client"

import { useCallback, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Spinner } from "@workspace/ui/components/spinner"
import { sileo } from "sileo"
import Link from "next/link"
import { addLiquidity, removeLiquidity } from "@/lib/api/liquidity"
import { useCurrentUser } from "@/hooks/use-auth"
import { useWallet } from "@/hooks/api/use-wallet"
import { queryKeys } from "@/lib/api/queryKeys"

export function AddLiquidityForm({ marketId, marketStatus }: { marketId: string; marketStatus: string }) {
  const { data: currentUser } = useCurrentUser()
  const { data: wallet } = useWallet()
  const qc = useQueryClient()
  const [amount, setAmount] = useState("")
  const [lpTokens, setLpTokens] = useState("")

  const isMarketActive = marketStatus === "active"
  const availableBalance = Number(wallet?.available_balance ?? 0)
  const parsedAmount = parseFloat(amount) || 0
  const hasInsufficientBalance = parsedAmount > availableBalance

  const { mutateAsync: add, isPending: isAdding } = useMutation({
    mutationFn: () => addLiquidity(marketId, { amount: parseFloat(amount) }),
    onSuccess: () => {
      sileo.success({ title: "Liquidity added" })
      setAmount("")
      qc.invalidateQueries({ queryKey: ["market", marketId] })
      qc.invalidateQueries({ queryKey: queryKeys.lpAnalytics() })
      qc.invalidateQueries({ queryKey: queryKeys.lpPosition(marketId) })
      qc.invalidateQueries({ queryKey: queryKeys.wallet() })
    },
    onError: (e) => sileo.error({ title: "Failed to add liquidity", description: e instanceof Error ? e.message : "Unknown error" }),
  })

  const { mutateAsync: remove, isPending: isRemoving } = useMutation({
    mutationFn: () => removeLiquidity(marketId, { lp_tokens: parseFloat(lpTokens) }),
    onSuccess: () => {
      sileo.success({ title: "Liquidity removed" })
      setLpTokens("")
      qc.invalidateQueries({ queryKey: ["market", marketId] })
      qc.invalidateQueries({ queryKey: queryKeys.lpAnalytics() })
      qc.invalidateQueries({ queryKey: queryKeys.lpPosition(marketId) })
      qc.invalidateQueries({ queryKey: queryKeys.wallet() })
    },
    onError: (e) => sileo.error({ title: "Failed to remove liquidity", description: e instanceof Error ? e.message : "Unknown error" }),
  })

  const handleAdd = useCallback(() => {
    if (!amount || parseFloat(amount) <= 0) return
    add()
  }, [amount, add])

  const handleRemove = useCallback(() => {
    if (!lpTokens || parseFloat(lpTokens) <= 0) return
    remove()
  }, [lpTokens, remove])

  if (!currentUser) {
    return (
      <div className="py-4 text-center space-y-2">
        <p className="text-xs text-muted-foreground">Sign in to provide liquidity</p>
        <Link
          href="/login"
          className="block w-full rounded-md border border-border px-4 py-2 text-xs font-medium text-center text-muted-foreground hover:bg-muted transition-colors"
        >
          Sign In
        </Link>
      </div>
    )
  }

  if (!isMarketActive) {
    return (
      <div className="py-4 text-center">
        <p className="text-xs text-muted-foreground">Liquidity disabled — market is {marketStatus}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {hasInsufficientBalance && (
        <p className="text-xs text-red-500">
          Insufficient balance — max ${availableBalance.toFixed(2)} available
        </p>
      )}
      <div>
        <label className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1.5 block">
          Add Liquidity
        </label>
        <div className="flex gap-2">
          <Input
            type="number"
            min="0"
            step="0.01"
            placeholder="USDC amount"
            className="h-8 text-xs"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
          <Button
            size="sm"
            className="h-8 text-xs"
            onClick={handleAdd}
            disabled={isAdding || !amount || parsedAmount <= 0 || hasInsufficientBalance}
          >
            {isAdding ? <Spinner className="size-3" /> : "Add"}
          </Button>
        </div>
      </div>
      <div>
        <label className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1.5 block">
          Remove Liquidity
        </label>
        <div className="flex gap-2">
          <Input
            type="number"
            min="0"
            step="0.01"
            placeholder="LP tokens"
            className="h-8 text-xs"
            value={lpTokens}
            onChange={(e) => setLpTokens(e.target.value)}
          />
          <Button
            size="sm"
            className="h-8 text-xs"
            onClick={handleRemove}
            disabled={isRemoving || !lpTokens || parseFloat(lpTokens) <= 0}
          >
            {isRemoving ? <Spinner className="size-3" /> : "Remove"}
          </Button>
        </div>
      </div>
    </div>
  )
}
