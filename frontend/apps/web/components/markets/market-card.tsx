"use client"

import { memo } from "react"
import Link from "next/link"
import { cn } from "@workspace/ui/lib/utils"
import type { MarketResponse } from "@/lib/types/api"

function formatVolume(v: number) {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`
  return `$${v.toFixed(2)}`
}

interface MarketCardProps {
  market: MarketResponse
  outcomes?: ReadonlyArray<{ id: string; name: string; price: number; outcome_index: number }>
  onBet?: (outcomeIndex: number) => void
  compact?: boolean
}

interface OutcomeRowProps {
  outcome: { id: string; name: string; price: number; outcome_index: number }
  marketSlug: string
}

const OutcomeRow = memo(function OutcomeRow({ outcome, marketSlug }: OutcomeRowProps) {
  const prob = Math.round(outcome.price * 100)

  return (
    <div className="flex items-center gap-3 py-1.5 min-w-0">
      {/* Outcome name */}
      <Link
        href={`/markets/${marketSlug}`}
        className="flex-1 min-w-0 truncate text-sm font-medium text-foreground hover:underline decoration-2"
      >
        {outcome.name}
      </Link>

      {/* YES / NO buttons */}
      <div className="flex items-center gap-1 shrink-0">
        {/* Price */}
        <span className="text-sm font-semibold text-foreground w-10 text-right mr-1">
          {prob}%
        </span>

        {/* YES */}
        <Link
          href={`/markets/${marketSlug}?outcomeIndex=${outcome.outcome_index}`}
          className="group inline-flex items-center justify-center relative h-[27px] w-10 rounded-xs bg-green-500/15 text-green-600 hover:bg-green-500 hover:!text-white transition-all duration-150 active:scale-95"
        >
          <span className="absolute top-1/2 -translate-y-1/2 left-1/2 -translate-x-1/2 text-[13px] font-semibold truncate max-w-[36px] group-hover:opacity-0 transition-opacity">
            Yes
          </span>
          <span className="absolute top-1/2 -translate-y-1/2 left-1/2 -translate-x-1/2 text-[13px] font-semibold opacity-0 group-hover:opacity-100 transition-opacity">
            {prob}%
          </span>
        </Link>

        {/* NO */}
        <Link
          href={`/markets/${marketSlug}?outcomeIndex=${outcome.outcome_index === 0 ? 1 : 0}`}
          className="group inline-flex items-center justify-center relative h-[27px] w-10 rounded-xs bg-red-500/15 text-red-500 hover:bg-red-500 hover:!text-white transition-all duration-150 active:scale-95"
        >
          <span className="absolute top-1/2 -translate-y-1/2 left-1/2 -translate-x-1/2 text-[13px] font-semibold truncate max-w-[36px] group-hover:opacity-0 transition-opacity">
            No
          </span>
          <span className="absolute top-1/2 -translate-y-1/2 left-1/2 -translate-x-1/2 text-[13px] font-semibold opacity-0 group-hover:opacity-100 transition-opacity">
            {100 - prob}%
          </span>
        </Link>
      </div>
    </div>
  )
})

function MarketCard({ market, outcomes }: MarketCardProps) {
  const displayOutcomes = outcomes ?? [
    { id: "yes", name: "Yes", price: market.yes_price, outcome_index: 0 },
    { id: "no", name: "No", price: market.no_price, outcome_index: 1 },
  ]

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden hover:border-primary/30 hover:shadow-md hover:-translate-y-px transition-all duration-200">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 pt-3 pb-2">
        {market.status === "resolved" ? (
          <span className="shrink-0 rounded-full bg-yellow-500/10 px-2 py-0.5 text-[8px] font-medium text-yellow-600 uppercase tracking-wide">
            RESOLVED
          </span>
        ) : market.category ? (
          <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[8px] font-medium text-primary uppercase tracking-wide">
            {market.category}
          </span>
        ) : null}
        <Link
          href={`/markets/${market.slug}`}
          className="flex-1 min-w-0"
        >
          <h3 className="text-sm font-semibold text-foreground leading-snug line-clamp-2 hover:underline decoration-2">
            {market.question}
          </h3>
        </Link>
      </div>

      {/* Divider */}
      <div className="border-t border-border/50 mx-4" />

      {/* Outcome rows */}
      <div className="px-4 py-1">
        {displayOutcomes.map((outcome) => (
          <OutcomeRow
            key={outcome.id ?? outcome.outcome_index}
            outcome={outcome}
            marketSlug={market.slug}
          />
        ))}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between px-4 py-2 border-t border-border/50">
        <span className="text-[11px] text-muted-foreground">
          <span className="uppercase font-semibold">${formatVolume(market.total_volume)}</span> Vol
        </span>
        <span className="text-[11px] text-muted-foreground">
          {new Date(market.closes_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
        </span>
      </div>
    </div>
  )
}

export { MarketCard }
export type { MarketCardProps }
