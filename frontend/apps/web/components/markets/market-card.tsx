"use client"

import { memo, useMemo } from "react"
import Link from "next/link"
import type { MarketResponse } from "@/hooks/api/types/market"

function formatVolume(v: string | number) {
  const n = Number(v)
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`
  return `$${n.toFixed(2)}`
}

interface MarketCardProps {
  market: MarketResponse
}

const ProbabilityBar = memo(function ProbabilityBar({ prob, color, label }: { prob: number; color: string; label?: string }) {
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(prob * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ? `${label}: ${Math.round(prob * 100)}%` : `${Math.round(prob * 100)}%`}
      className="h-5 w-full rounded-xs bg-muted overflow-hidden relative"
    >
      <div
        className="h-full rounded-xs transition-all duration-300"
        style={{ width: `${Math.round(prob * 100)}%`, backgroundColor: color }}
      />
      <span className="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-foreground mix-blend-difference">
        {Math.round(prob * 100)}%
      </span>
    </div>
  )
})

const MULTI_COLORS = [
  "#22c55e", "#ef4444", "#3b82f6", "#f59e0b", "#a855f7",
  "#06b6d4", "#ec4899", "#14b8a6", "#f97316", "#8b5cf6",
]

const OutcomeGrid = memo(function OutcomeGrid({
  outcomes,
  marketSlug,
  max = 4,
  isBinary,
}: {
  outcomes: { id: string; name: string; price: string; outcome_index: number }[]
  marketSlug: string
  max?: number
  isBinary?: boolean
}) {
  const visible = outcomes.slice(0, max)
  const overflow = outcomes.length - max

  return (
    <div className="grid grid-cols-2 gap-1.5">
      {visible.map((o, i) => {
        const color: string = isBinary
          ? (o.name === "Yes" || o.outcome_index === 0 ? "#22c55e" : "#ef4444")
          : MULTI_COLORS[i % MULTI_COLORS.length]!
        return (
          <Link
            key={o.id ?? o.outcome_index}
            href={`/markets/${marketSlug}${isBinary ? `?outcomeIndex=${o.outcome_index}` : ""}`}
            className="group rounded-md border border-border/60 bg-card/50 p-2 hover:border-primary/40 hover:bg-muted/30 transition-all"
          >
            <div className="truncate text-[11px] font-medium text-foreground mb-1 group-hover:underline">
              {o.name}
            </div>
            <ProbabilityBar prob={Number(o.price)} color={color} label={o.name} />
          </Link>
        )
      })}
      {overflow > 0 && (
        <Link
          href={`/markets/${marketSlug}`}
          aria-label={`${overflow} more outcomes`}
          className="flex items-center justify-center rounded-md border border-dashed border-border text-[11px] text-muted-foreground hover:text-foreground hover:border-primary/40 transition-all"
        >
          +{overflow} more
        </Link>
      )}
    </div>
  )
})

const MarketCard = memo(function MarketCard({ market }: MarketCardProps) {
  const isMulti = market.outcomes && market.outcomes.length > 2

  const displayOutcomes = useMemo(() => {
    if (isMulti) {
      return market.outcomes!.map((o) => ({ id: o.id, name: o.name, price: String(1 / market.outcomes!.length), outcome_index: o.outcome_index }))
    }
    return [
      { id: "yes", name: "Yes", price: market.yes_price, outcome_index: 0 },
      { id: "no", name: "No", price: market.no_price, outcome_index: 1 },
    ]
  }, [isMulti, market.outcomes, market.yes_price, market.no_price])

  return (
    <article className="rounded-xl border border-border bg-card overflow-hidden hover:border-primary/30 hover:shadow-md hover:-translate-y-px transition-all duration-200 flex flex-col">
      {/* Header */}
      <div className="flex items-start gap-2 px-4 pt-3 pb-2">
        {market.status === "resolved" ? (
          <span className="shrink-0 rounded-full bg-yellow-500/10 px-2 py-0.5 text-[8px] font-medium text-yellow-600 uppercase tracking-wide">
            RESOLVED
          </span>
        ) : market.category ? (
          <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[8px] font-medium text-primary uppercase tracking-wide">
            {market.category}
          </span>
        ) : null}
        <Link href={`/markets/${market.slug}`} className="flex-1 min-w-0" aria-label={`View ${market.question}`}>
          <h3 className="text-sm font-semibold text-foreground leading-snug line-clamp-2 hover:underline decoration-2">
            {market.question}
          </h3>
        </Link>
      </div>

      <div className="border-t border-border/50 mx-4" />

      {/* Outcomes */}
      <div className="px-4 py-2 flex-1">
        <OutcomeGrid outcomes={displayOutcomes} marketSlug={market.slug} max={isMulti ? 4 : 2} isBinary={!isMulti} />
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between px-4 py-2 border-t border-border/50 mt-auto">
        <span className="text-[11px] text-muted-foreground">
          <span className="uppercase font-semibold">${formatVolume(market.total_volume)}</span> Vol
        </span>
        <span className="text-[11px] text-muted-foreground">
          {new Date(market.closes_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
        </span>
      </div>
    </article>
  )
})

export { MarketCard }
export type { MarketCardProps }
