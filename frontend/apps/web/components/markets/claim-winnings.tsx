"use client"

import { memo, useCallback, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { sileo } from "sileo"
import { useCurrentUser } from "@/hooks/use-auth"
import { claimWinnings } from "@/lib/api/markets"

const ClaimWinnings = memo(function ClaimWinnings({ slug }: { slug: string }) {
  const { data: currentUser } = useCurrentUser()
  const qc = useQueryClient()
  const [claiming, setClaiming] = useState(false)
  const [claimed, setClaimed] = useState(false)

  const handleClaim = useCallback(async () => {
    setClaiming(true)
    try {
      await claimWinnings(slug)
      setClaimed(true)
      qc.invalidateQueries({ queryKey: ["wallet"] })
      qc.invalidateQueries({ queryKey: ["transactions"] })
      qc.invalidateQueries({ queryKey: ["positions"] })
      sileo.success({ title: "Winnings claimed!" })
    } catch (e) {
      sileo.error({ title: "Claim failed", description: e instanceof Error ? e.message : "Unknown error" })
    } finally {
      setClaiming(false)
    }
  }, [slug, qc])

  if (!currentUser) return null

  return (
    <div className="mt-3 pt-3 border-t border-amber-500/20">
      <button
        onClick={handleClaim}
        disabled={claiming || claimed}
        aria-label={claimed ? "Winnings already claimed" : claiming ? "Claiming winnings" : "Claim your winnings"}
        className="w-full rounded-md bg-amber-500 px-3 py-2 text-xs font-semibold text-amber-950 hover:bg-amber-400 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {claimed ? "Claimed!" : claiming ? "Claiming..." : "Claim Winnings"}
      </button>
    </div>
  )
})

export { ClaimWinnings }
