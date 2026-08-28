"use client"

import { useCallback, useState } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
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
  const [lpTokens, setLpTokens] = useState("")

  const addForm = useForm({
    resolver: zodResolver(z.object({ amount: z.number().min(0.01, "Min amount is 0.01") })),
    defaultValues: { amount: 0 },
  })

  const isMarketActive = marketStatus === "active"
  const availableBalance = Number(wallet?.available_balance ?? 0)
  const parsedAmount = addForm.watch("amount") ?? 0
  const hasInsufficientBalance = parsedAmount > availableBalance

  const { mutateAsync: add, isPending: isAdding } = useMutation({
    mutationFn: (amt: number) => addLiquidity(marketId, { amount: amt }),
    onSuccess: () => {
      sileo.success({ title: "Liquidity added" })
      addForm.reset()
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

  const handleAdd = useCallback((data: { amount: number }) => {
    if (!data.amount || data.amount <= 0) return
    add(data.amount)
  }, [add])

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
            step="0.01"
            min="0.01"
            placeholder="USDC amount"
            className="h-8 text-xs"
            {...addForm.register("amount", { valueAsNumber: true })}
          />
          <Button
            size="sm"
            className="h-8 text-xs"
            onClick={addForm.handleSubmit(handleAdd)}
            disabled={isAdding || parsedAmount <= 0 || hasInsufficientBalance}
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
