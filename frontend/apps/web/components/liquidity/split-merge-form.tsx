"use client"

import { useCallback, useMemo, useState } from "react"
import { useMarkets } from "@/hooks/api/use-markets"
import { useCurrentUser } from "@/hooks/use-auth"
import { useSplit, useMerge } from "@/hooks/api/use-split-merge"
import { useWallet } from "@/hooks/api/use-wallet"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Spinner } from "@workspace/ui/components/spinner"
import { Tabs, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@workspace/ui/components/select"
import Link from "next/link"

export function SplitMergeForm() {
  const { data: currentUser } = useCurrentUser()
  const { data: wallet } = useWallet()
  const { data: marketsData } = useMarkets()
  const [mode, setMode] = useState<"split" | "merge">("split")
  const [marketId, setMarketId] = useState("")
  const [amount, setAmount] = useState("")

  const { mutateAsync: split, isPending: isSplitting } = useSplit()
  const { mutateAsync: merge, isPending: isMerging } = useMerge()

  const isPending = isSplitting || isMerging
  const availableBalance = Number(wallet?.available_balance ?? 0)
  const parsedAmount = parseFloat(amount) || 0

  const selectedMarket = useMemo(() =>
    marketsData?.markets.find((m) => m.id === marketId),
    [marketsData?.markets, marketId]
  )

  const handleSplit = useCallback(async () => {
    if (!marketId || parsedAmount <= 0) return
    await split({ marketId, amount: parsedAmount })
    setAmount("")
  }, [marketId, parsedAmount, split])

  const handleMerge = useCallback(async () => {
    if (!marketId || parsedAmount <= 0) return
    await merge({ marketId, amount: parsedAmount })
    setAmount("")
  }, [marketId, parsedAmount, merge])

  const handleSubmit = useCallback(() => {
    if (mode === "split") handleSplit()
    else handleMerge()
  }, [mode, handleSplit, handleMerge])

  const handleTabChange = useCallback((v: string) => {
    setMode(v as "split" | "merge")
    setAmount("")
  }, [])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSubmit()
  }, [handleSubmit])

  if (!currentUser) {
    return (
      <div className="py-4 text-center space-y-2">
        <p className="text-xs text-muted-foreground">Sign in to use split/merge</p>
        <Link
          href="/login"
          className="block w-full rounded-md border border-border px-4 py-2 text-xs font-medium text-center text-muted-foreground hover:bg-muted transition-colors"
        >
          Sign In
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <Tabs value={mode} onValueChange={handleTabChange} className="w-full">
        <TabsList className="w-full grid grid-cols-2">
          <TabsTrigger value="split" className="text-xs">Split (USDC → Shares)</TabsTrigger>
          <TabsTrigger value="merge" className="text-xs">Merge (Shares → USDC)</TabsTrigger>
        </TabsList>
      </Tabs>

      <div>
        <label className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1.5 block">
          Market
        </label>
        <Select value={marketId} onValueChange={(v) => { if (v) setMarketId(v) }}>
          <SelectTrigger>
            <SelectValue placeholder="Select market" />
          </SelectTrigger>
          <SelectContent>
            {marketsData?.markets.map((m) => (
              <SelectItem key={m.id} value={m.id}>{m.question.slice(0, 60)}{m.question.length > 60 ? "…" : ""}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {selectedMarket && (
          <p className="text-[10px] text-muted-foreground mt-1">
            YES ${Number(selectedMarket.yes_price).toFixed(2)} · NO ${Number(selectedMarket.no_price).toFixed(2)}
          </p>
        )}
      </div>

      <div>
        <label className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1.5 block">
          {mode === "split" ? "USDC Amount" : "Shares Amount"}
        </label>
        <Input
          type="number"
          min="0"
          step="0.01"
          placeholder={mode === "split" ? "USDC to convert" : "Shares to convert"}
          className="h-9 text-xs"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        {mode === "split" && parsedAmount > availableBalance && (
          <p className="text-[10px] text-red-500 mt-1">Insufficient balance — max ${availableBalance.toFixed(2)}</p>
        )}
        {mode === "split" && selectedMarket && parsedAmount > 0 && (
          <p className="text-[10px] text-muted-foreground mt-1">
            You receive ~{parsedAmount.toFixed(2)} YES + ~{parsedAmount.toFixed(2)} NO shares (2% fee deducted)
          </p>
        )}
        {mode === "merge" && selectedMarket && parsedAmount > 0 && (
          <p className="text-[10px] text-muted-foreground mt-1">
            You receive ~${parsedAmount.toFixed(2)} USDC (2% fee deducted)
          </p>
        )}
      </div>

      <Button
        className="w-full h-9 text-xs"
        onClick={handleSubmit}
        disabled={isPending || !marketId || parsedAmount <= 0 || (mode === "split" && parsedAmount > availableBalance)}
      >
        {isPending ? <Spinner className="size-3" /> : mode === "split" ? "Split USDC" : "Merge Shares"}
      </Button>
    </div>
  )
}
