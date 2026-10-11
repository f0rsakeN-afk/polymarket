"use client"

import { memo, useMemo } from "react"
import Link from "next/link"
import type { MarketResponse } from "@/hooks/api/types/market"
import { outcomeColor } from "@/lib/outcome-colors"
import { applyLivePrices } from "@/lib/live-price"
import { tickColor, usePriceTick } from "@/lib/use-price-tick"
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
  /**
   * Latest prices from the shared socket, when the card sits inside a grid that
   * subscribes. Omit on surfaces with no live feed and the card renders from
   * `market` exactly as before.
   */
  live?: {
    yes_price?: number
    no_price?: number
    outcome_prices?: Record<string, number>
  }
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

  return (
    <Link
      href={href}
      className="flex h-9 min-h-9 w-12 min-w-12 items-center justify-center rounded-md text-xs font-semibold transition-colors duration-150 hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      style={
        isYes
          ? { backgroundColor: "var(--chart-1)", color: "var(--primary-foreground)" }
          : { backgroundColor: "var(--destructive)", color: "var(--destructive-foreground)" }
      }
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
  const isYes =
    outcome.name === "Yes" ||
    outcome.name === "yes" ||
    outcome.outcome_index === 0

  return (
    <div
      className={cn(
        "flex items-center gap-3 py-2",
        !isLast && "border-b border-border/50"
      )}
    >
      {/* Name + % */}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-foreground">
          {outcome.name}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <span
          className={cn(
            "text-base font-semibold tabular-nums",
            isYes ? "text-green-700" : "text-red-700"
          )}
        >
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

  // Direction of this outcome's last real move. Hook order is unconditional -
  // an early return above it would change the hook count between renders.
  const numeric = Number(outcome.price)
  const tick = usePriceTick(Number.isFinite(numeric) ? numeric : null)

  return (
    <Link
      href={`/markets/${marketSlug}?outcomeIndex=${outcome.outcome_index}`}
      className="group flex flex-col gap-1 rounded-md border border-border/60 bg-card/50 p-2 transition-colors hover:border-primary/40 hover:bg-accent"
    >
      <div className="flex items-center justify-between">
        <span className="max-w-20 truncate text-xs font-medium text-foreground group-hover:underline">
          {outcome.name}
        </span>
        {/*
          The number flashes on a real move.

          `key={tick.at}` remounts the span so the CSS animation restarts, which
          is how the highlight plays once and reverts with no JS timer to keep in
          sync. Colour alone is not enough - it is also bolded, because colour is
          the channel users with colour-vision deficiency lose, and it is the
          first thing to drop when a grid is dense.

          `motion-reduce` removes it entirely for users who have asked the OS for
          less motion: a grid re-animating several times a second is exactly the
          repeated peripheral animation that setting exists for.
        */}
        <span
          key={tick.at}
          className={cn(
            "shrink-0 text-xs font-semibold tabular-nums text-foreground",
            tick.direction !== 0 && "animate-[tick-flash_900ms_ease-out] motion-reduce:animate-none",
            tickColor(tick.direction),
          )}
        >
          {pct}%
        </span>
      </div>
      {/* Mini bar. `transition-all` replaced with `transition-[width]` so a price
          tick animates the one thing that changed, rather than every colour and
          shadow on the element at the same time. */}
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full transition-[width] duration-300 motion-reduce:transition-none"
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
  // A card is a teaser, not a table, and it shows the same shape whatever the
  // market type - so a grid of them reads as one surface rather than a mix of
  // sizes.
  //
  // Binary rows and multi-outcome cells are already the same component - name,
  // percentage, bar - so a binary market and a parimutuel market with up to four
  // outcomes are identical: two rows either way. Only *more* than four diverged,
  // because the cap was six and the badge took a full extra row (`col-span-2`),
  // making those cards visibly taller than the rest of their row.
  //
  // Fixing the grid at 2x2 and letting the badge occupy the slot a fourth
  // outcome would have used means every card is exactly two outcome rows tall -
  // two outcomes or fifty - which is what lets the grid be laid out at a known
  // height with no measuring, no ragged rows, and no clipped content.
  const MAX_SLOTS = 4
  // Derived from what is actually hidden, not from the slot count. The badge
  // takes one of the four slots, so the number of outcomes on screen is
  // `MAX_SLOTS - 1` whenever there is an overflow - computing it from
  // `MAX_SLOTS` instead undercounts by exactly one and tells the user there are
  // fewer options left than there really are.
  const visible =
    outcomes.length > MAX_SLOTS ? outcomes.slice(0, MAX_SLOTS - 1) : outcomes.slice(0, MAX_SLOTS)
  const overflow = outcomes.length - visible.length

  return (
    <div className="grid grid-cols-2 gap-1.5">
      {visible.map((o, i) => (
        <MultiOutcomeCell
          key={o.id ?? o.outcome_index}
          outcome={o}
          color={outcomeColor(i)}
          marketSlug={marketSlug}
        />
      ))}
      {overflow > 0 && (
        <Link
          href={`/markets/${marketSlug}`}
          className="flex items-center justify-center rounded-md border border-dashed border-border text-xs font-medium text-muted-foreground transition-all hover:border-primary/40 hover:text-foreground"
        >
          +{overflow} more
        </Link>
      )}
    </div>
  )
})

// ─── Market Card ───────────────────────────────────────────────────────────────

const MarketCard = memo(function MarketCard({ market, live }: MarketCardProps) {
  // Live prices overlay the REST snapshot when a socket frame has arrived, so a
  // card in a grid moves on the same frame the market page does. Without it both
  // grids - the home page and /markets - froze at whatever the list query
  // returned, sitting right beside a live trending carousel.
  //
  // Overlaid here rather than written to the query cache because the card renders
  // from props and the same market appears in several differently-filtered lists.
  // `applyLivePrices` owns the multi-outcome rules.
  const priced = useMemo(() => applyLivePrices(market, live), [market, live])

  // Name-based, matching the backend: a market is parimutuel when it has no
  // YES/NO pair. Counting outcomes would classify a two-way NAMED market
  // ("Trump vs Biden") as binary and render it as Yes/No, which is not what it is.
  const hasNamedPair = useMemo(() => {
    const names = (priced.outcomes ?? []).map((o) => o.name.toLowerCase())
    return names.includes("yes") && names.includes("no")
  }, [priced.outcomes])

  const isMulti = (priced.outcomes?.length ?? 0) > 0 && !hasNamedPair

  // Movement is tracked on the headline price - the YES price for a binary
  // market, and the leading outcome for a parimutuel one, because every market
  // has one and it is the number the grid is scanned for. Tracking each outcome
  // separately would light up a card for a change the user is not looking at.
  const headline = isMulti
    ? Number(priced.outcomes?.[0]?.price ?? Number.NaN)
    : Number(priced.yes_price ?? Number.NaN)
  const tick = usePriceTick(Number.isFinite(headline) ? headline : null)

  // A price from the socket is a fact about *now*; one from the REST snapshot is
  // a fact about when the page loaded. Without saying which, a card that never
  // updates looks exactly like a card that is merely quiet.
  const isLive = live !== undefined

  const displayOutcomes = useMemo(() => {
    if (isMulti) {
      // Real per-outcome prices from the API. The old fallback of `1 / n` for
      // every outcome made all N read identical no matter what the market
      // actually looked like.
      const even = String(1 / (priced.outcomes?.length ?? 1))
      return priced.outcomes!.map((o) => ({
        id: o.id,
        name: o.name,
        price:
          o.price === null || o.price === undefined
            ? even
            : String(o.price),
        outcome_index: o.outcome_index,
      }))
    }
    // Binary: the market-level pair. The API also prices each outcome
    // individually, but on a YES/NO market that is the same two numbers, and
    // `yes_price`/`no_price` is the pair the card has always displayed.
    return [
      { id: "yes", name: "Yes", price: priced.yes_price, outcome_index: 0 },
      { id: "no", name: "No", price: priced.no_price, outcome_index: 1 },
    ]
  }, [isMulti, priced.outcomes, priced.yes_price, priced.no_price])

  return (
    <article
      className={cn(
        "flex h-full min-h-0 flex-col overflow-hidden rounded-xl border bg-card transition-all duration-200 hover:shadow-md",
        // The "just moved" treatment is deliberately quiet: a border tint, not a
        // fill. A grid where whole cards flash is unreadable, and the thing worth
        // noticing is *which* card moved, so the emphasis has to stay on the
        // number and let the card edge just say "something happened here".
        tick.active
          ? "border-primary/40 ring-1 ring-primary/20"
          : "border-border hover:border-primary/30",
      )}
      data-active={tick.active || undefined}
      data-live={isLive || undefined}
    >
      {/* Header */}
      <div className="flex items-start gap-2 px-4 pt-4 pb-3">
        {market.status === "resolved" && (
          <span className="shrink-0 rounded-full bg-yellow-500/10 px-2 py-0.5 text-[10px] font-semibold tracking-wider text-yellow-700 uppercase">
            Resolved
          </span>
        )}
        <Link
          href={`/markets/${market.slug}`}
          className="min-w-0 flex-1"
          aria-label={`View ${market.question}`}
        >
          <h3 className="line-clamp-2 text-sm leading-snug font-semibold text-foreground decoration-2 hover:underline">
            {market.question}
          </h3>
        </Link>
      </div>

      <div className="mx-4 border-t border-border/50" />

      {/* Outcomes */}
      {/* `min-h-0` stops a tall market pushing the footer out of the cell;
          `overflow-hidden` clips anything that still exceeds it here rather than
          letting it escape the card's rounded corner. */}
      <div className="min-h-0 flex-1 overflow-hidden px-4 py-3">
        {isMulti ? (
          <MultiOutcomeGrid
            outcomes={displayOutcomes}
            marketSlug={market.slug}
          />
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
      <div className="mt-auto flex items-center justify-between gap-2 border-t border-border/50 px-4 py-2.5">
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {isLive && (
            <span
              className="relative flex size-1.5 shrink-0"
              title="Live — streaming prices"
            >
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-500 opacity-60 motion-reduce:hidden" />
              <span className="relative inline-flex size-1.5 rounded-full bg-emerald-500" />
            </span>
          )}
          <span className="font-semibold uppercase">
            {formatVolume(market.total_volume)} Vol
          </span>
        </span>
        <span className="text-xs text-muted-foreground">
          {new Date(market.closes_at).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
          })}
        </span>
      </div>
    </article>
  )
})

// ─── Skeleton ────────────────────────────────────────────────────────────────

export function MarketCardSkeleton() {
  return (
    <article className="overflow-hidden rounded-xl border border-border bg-card">
      {/* Header */}
      <div className="flex items-start gap-2 px-4 pt-4 pb-3">
        <Skeleton className="h-5 w-14 shrink-0 rounded-full" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      </div>
      <div className="mx-4 border-t border-border/50" />
      {/* Outcome rows */}
      <div className="space-y-0 px-4 py-3">
        {[1, 2].map((i) => (
          <div
            key={i}
            className="flex items-center gap-3 border-b border-border/50 py-2 last:border-0"
          >
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="h-4 w-10 rounded" />
            <Skeleton className="h-9 w-12 shrink-0 rounded-md" />
            <Skeleton className="h-9 w-12 shrink-0 rounded-md" />
          </div>
        ))}
      </div>
      {/* Footer */}
      <div className="flex items-center justify-between border-t border-border/50 px-4 py-2.5">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-3 w-16" />
      </div>
    </article>
  )
}

export { MarketCard }
export type { MarketCardProps }
