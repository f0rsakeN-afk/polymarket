"use client"

import { memo, useMemo } from "react"
import Link from "next/link"
import type { MarketResponse } from "@/hooks/api/types/market"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { cn } from "@workspace/ui/lib/utils"

function formatVolume(v: string | number) {
  const n = Number(v)
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`
  return `$${n.toFixed(2)}`
}

interface MarketCardProps {
  market: MarketResponse
}

// ─── Binary layout: name + % + YES/NO pills in one row ────────────────────────

function TradePill({
  href,
  label,
  variant,
}: {
  href: string
  label: string
  variant: "yes" | "no"
}) {
  const isYes = variant === "yes"
  // oklch matches our design system green/red — using CSS variables for consistency
  const bg = isYes ? "oklch(0.72 0.19 145 / 0.12)" : "oklch(0.63 0.24 27 / 0.10)"
  const textColor = isYes ? "oklch(0.63 0.15 145)" : "oklch(0.63 0.24 27)"

  return (
    <Link
      href={href}
      className="h-7 w-11 !rounded-xs flex items-center justify-center text-xs font-semibold transition-colors duration-150 hover:opacity-80"
      style={{ backgroundColor: bg, color: textColor }}
    >
      {label}
    </Link>
  )
}

const BinaryOutcomeRow = memo(function BinaryOutcomeRow({
  outcome,
  marketSlug,
  isLast,
}: {
  outcome: { id: string; name: string; price: string; outcome_index: number }
  marketSlug: string
  isLast: boolean
}) {
  const pct = Math.round(Number(outcome.price) * 100)
  const isYes = outcome.name === "Yes" || outcome.name === "yes" || outcome.outcome_index === 0
  const color = isYes ? "#22c55e" : "#ef4444"

  return (
    <div className={cn("flex items-center gap-3 py-2", !isLast && "border-b border-border/50")}>
      {/* Name + % */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-foreground truncate">{outcome.name}</p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <span className="text-base font-semibold tabular-nums" style={{ color }}>
          {pct}%
        </span>
        <TradePill
          href={`/markets/${marketSlug}?outcomeIndex=${outcome.outcome_index}&side=buy`}
          label="Yes"
          variant="yes"
        />
        <TradePill
          href={`/markets/${marketSlug}?outcomeIndex=${outcome.outcome_index}&side=no`}
          label="No"
          variant="no"
        />
      </div>
    </div>
  )
})

// ─── Multi-outcome layout: compact 2-column grid ───────────────────────────────

const MULTI_COLORS = [
  "#22c55e", "#ef4444", "#3b82f6", "#f59e0b", "#a855f7",
  "#06b6d4", "#ec4899", "#14b8a6", "#f97316", "#8b5cf6",
]

function MultiOutcomeCell({
  outcome,
  color,
  marketSlug,
}: {
  outcome: { id: string; name: string; price: string; outcome_index: number }
  color: string
  marketSlug: string
}) {
  const pct = Math.round(Number(outcome.price) * 100)

  return (
    <Link
      href={`/markets/${marketSlug}?outcomeIndex=${outcome.outcome_index}`}
      className="group flex flex-col gap-1 p-2 rounded-md border border-border/60 bg-card/50 hover:bg-accent hover:border-primary/40 transition-all"
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-foreground truncate max-w-20 group-hover:underline">
          {outcome.name}
        </span>
        <span className="text-xs font-semibold tabular-nums shrink-0" style={{ color }}>
          {pct}%
        </span>
      </div>
      {/* Mini bar */}
      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
    </Link>
  )
}

const MultiOutcomeGrid = memo(function MultiOutcomeGrid({
  outcomes,
  marketSlug,
}: {
  outcomes: { id: string; name: string; price: string; outcome_index: number }[]
  marketSlug: string
}) {
  const visible = outcomes.slice(0, 6)
  const overflow = outcomes.length - visible.length

  return (
    <div className="grid grid-cols-2 gap-1.5">
      {visible.map((o, i) => (
        <MultiOutcomeCell
          key={o.id ?? o.outcome_index}
          outcome={o}
          color={MULTI_COLORS[i % MULTI_COLORS.length]!}
          marketSlug={marketSlug}
        />
      ))}
      {overflow > 0 && (
        <Link
          href={`/markets/${marketSlug}`}
          className="flex items-center justify-center rounded-md border border-dashed border-border text-xs text-muted-foreground hover:text-foreground hover:border-primary/40 transition-all col-span-2"
        >
          +{overflow} more
        </Link>
      )}
    </div>
  )
})

// ─── Market Card ───────────────────────────────────────────────────────────────

const MarketCard = memo(function MarketCard({ market }: MarketCardProps) {
  const isMulti = market.outcomes && market.outcomes.length > 2

  const displayOutcomes = useMemo(() => {
    if (isMulti) {
      // List API doesn't provide per-outcome prices — show equal probability
      return market.outcomes!.map((o) => ({
        id: o.id,
        name: o.name,
        price: String(1 / market.outcomes!.length),
        outcome_index: o.outcome_index,
      }))
    }
    return [
      { id: "yes", name: "Yes", price: market.yes_price, outcome_index: 0 },
      { id: "no", name: "No", price: market.no_price, outcome_index: 1 },
    ]
  }, [isMulti, market.outcomes, market.yes_price, market.no_price])

  return (
    <article className="rounded-xl border border-border bg-card overflow-hidden hover:border-primary/30 hover:shadow-md hover:-translate-y-px transition-all duration-200 flex flex-col mb-4">
      {/* Header */}
      <div className="flex items-start gap-2 px-4 pt-3 pb-2">
        {market.status === "resolved" ? (
          <span className="shrink-0 rounded-full bg-yellow-500/10 px-2 py-0.5 text-[0.5rem] font-medium text-yellow-600 uppercase tracking-wider">
            RESOLVED
          </span>
        ) : market.category ? (
          <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[0.5rem] font-medium text-primary uppercase tracking-wider">
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
        {isMulti ? (
          <MultiOutcomeGrid outcomes={displayOutcomes} marketSlug={market.slug} />
        ) : (
          displayOutcomes.map((o, i) => (
            <BinaryOutcomeRow
              key={o.id ?? o.outcome_index}
              outcome={o}
              marketSlug={market.slug}
              isLast={i === displayOutcomes.length - 1}
            />
          ))
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between px-4 py-2 border-t border-border/50 mt-auto">
        <span className="text-xs text-muted-foreground uppercase font-semibold">
          ${formatVolume(market.total_volume)} Vol
        </span>
        <span className="text-xs text-muted-foreground">
          {new Date(market.closes_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
        </span>
      </div>
    </article>
  )
})

// ─── Skeleton ────────────────────────────────────────────────────────────────

export function MarketCardSkeleton() {
  return (
    <article className="rounded-xl border border-border bg-card overflow-hidden mb-4">
      {/* Header */}
      <div className="flex items-start gap-2 px-4 pt-3 pb-2">
        <Skeleton className="h-5 w-14 rounded-full shrink-0" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      </div>
      <div className="border-t border-border/50 mx-4" />
      {/* Outcome rows */}
      <div className="px-4 py-2 space-y-0">
        {[1, 2].map((i) => (
          <div key={i} className="flex items-center gap-3 py-2 border-b border-border/50 last:border-0">
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="h-4 w-10 rounded" />
            <Skeleton className="h-7 w-11 !rounded-xs shrink-0" />
            <Skeleton className="h-7 w-11 !rounded-xs shrink-0" />
          </div>
        ))}
      </div>
      {/* Footer */}
      <div className="flex items-center justify-between px-4 py-2 border-t border-border/50">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-3 w-16" />
      </div>
    </article>
  )
}

export { MarketCard }
export type { MarketCardProps }
