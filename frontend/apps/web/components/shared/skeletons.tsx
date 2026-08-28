"use client"

import { memo } from "react"
import { cn } from "@workspace/ui/lib/utils"

function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded-md bg-muted/60", className)}
    />
  )
}

const SkeletonMarketCard = memo(function SkeletonMarketCard() {
  return (
    <div className="flex flex-col rounded-xl border border-border bg-card overflow-hidden">
      <div className="p-4 pb-2 space-y-2 flex-1">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
        <div className="grid grid-cols-2 gap-1.5 pt-1">
          <div className="rounded-md border border-border/60 bg-card/50 p-2 space-y-1.5">
            <Skeleton className="h-2.5 w-12" />
            <Skeleton className="h-2 w-full" />
          </div>
          <div className="rounded-md border border-border/60 bg-card/50 p-2 space-y-1.5">
            <Skeleton className="h-2.5 w-12" />
            <Skeleton className="h-2 w-full" />
          </div>
        </div>
      </div>
      <div className="border-t border-border px-4 py-2.5">
        <div className="flex items-center justify-between">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-3 w-16" />
        </div>
      </div>
    </div>
  )
})

const SkeletonMarketGrid = memo(function SkeletonMarketGrid({ count = 6 }: { count?: number }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonMarketCard key={i} />
      ))}
    </div>
  )
})

const SkeletonTradeFeed = memo(function SkeletonTradeFeed({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-0">
      <div className="grid grid-cols-7 gap-2 px-1 py-2 border-b border-border">
        {Array.from({ length: 7 }).map((_, i) => (
          <Skeleton key={i} className="h-2.5" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="grid grid-cols-7 gap-2 px-1 py-2.5 border-b border-border/50">
          {Array.from({ length: 7 }).map((_, j) => (
            <Skeleton key={j} className={cn("h-3", j === 0 ? "w-16" : j === 1 ? "w-10" : j === 2 ? "w-14" : j === 6 ? "w-12" : "w-full")} />
          ))}
        </div>
      ))}
    </div>
  )
})

const SkeletonOrderRow = memo(function SkeletonOrderRow() {
  return (
    <div className="flex items-center justify-between py-3 border-b border-border last:border-0">
      <div className="space-y-1.5 flex-1">
        <Skeleton className="h-3 w-48" />
        <div className="flex items-center gap-2">
          <Skeleton className="h-2.5 w-8" />
          <Skeleton className="h-2.5 w-6" />
          <Skeleton className="h-2.5 w-20" />
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0 ml-4">
        <Skeleton className="h-3 w-12" />
        <Skeleton className="h-4 w-14 rounded" />
      </div>
    </div>
  )
})

const SkeletonPortfolioSummary = memo(function SkeletonPortfolioSummary() {
  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-4">
      <div className="flex items-center justify-between">
        <Skeleton className="h-4 w-16" />
        <Skeleton className="h-3 w-12" />
      </div>
      <div className="flex items-end justify-between">
        <div className="space-y-1">
          <Skeleton className="h-2.5 w-20" />
          <Skeleton className="h-7 w-32" />
        </div>
        <div className="text-right space-y-1">
          <Skeleton className="h-2.5 w-24" />
          <Skeleton className="h-5 w-20" />
        </div>
      </div>
      <div className="border-t border-border/50 my-3" />
      <div className="grid grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="space-y-1">
            <Skeleton className="h-2.5 w-14" />
            <Skeleton className="h-4 w-20" />
          </div>
        ))}
      </div>
    </div>
  )
})

const SkeletonTrendingCarousel = memo(function SkeletonTrendingCarousel() {
  return (
    <div className="flex gap-4 overflow-hidden">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="min-w-[240px] rounded-xl border border-border bg-card p-4 space-y-2 shrink-0">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-3/4" />
          <div className="flex items-center justify-between pt-1">
            <Skeleton className="h-4 w-12" />
            <Skeleton className="h-2.5 w-16" />
          </div>
        </div>
      ))}
    </div>
  )
})

const SkeletonPositionsList = memo(function SkeletonPositionsList({ rows = 4 }: { rows?: number }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <Skeleton className="h-4 w-16 mb-3" />
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonOrderRow key={i} />
      ))}
    </div>
  )
})

const SkeletonMarketDetail = memo(function SkeletonMarketDetail() {
  return (
    <div className="grid gap-6 lg:grid-cols-4">
      <div className="space-y-6 lg:col-span-3">
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Skeleton className="h-4 w-24 rounded-full" />
            <Skeleton className="h-3 w-20" />
          </div>
          <Skeleton className="h-7 w-3/4" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Skeleton className="h-5 w-20" />
              <Skeleton className="h-5 w-20" />
            </div>
            <Skeleton className="h-3 w-20" />
          </div>
          <Skeleton className="h-[220px] w-full" />
        </div>
        <div className="grid grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-lg border border-border bg-card p-3 space-y-1.5 text-center">
              <Skeleton className="h-2.5 w-12 mx-auto" />
              <Skeleton className="h-4 w-16 mx-auto" />
            </div>
          ))}
        </div>
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="flex border-b border-border bg-muted/50">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-9 flex-1 m-0 rounded-none" />
            ))}
          </div>
          <div className="p-4">
            <Skeleton className="h-[200px] w-full" />
          </div>
        </div>
      </div>
      <div className="space-y-4">
        <div className="rounded-xl border border-border bg-card p-5 space-y-3">
          <Skeleton className="h-4 w-24" />
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full rounded-md" />
          ))}
          <Skeleton className="h-9 w-full rounded-md" />
        </div>
        <div className="rounded-xl border border-border bg-card p-5 space-y-3">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-9 w-full rounded-md" />
        </div>
        <div className="rounded-xl border border-border bg-card p-5 space-y-2">
          <Skeleton className="h-4 w-20" />
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center justify-between">
              <Skeleton className="h-2.5 w-16" />
              <Skeleton className="h-2.5 w-20" />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
})

const SkeletonTable = memo(function SkeletonTable({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <div className="flex items-center gap-4">
          {Array.from({ length: cols }).map((_, i) => (
            <Skeleton key={i} className="h-3 flex-1" />
          ))}
        </div>
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="px-4 py-3 border-b border-border/50 last:border-0">
          <div className="flex items-center gap-4">
            {Array.from({ length: cols }).map((_, j) => (
              <Skeleton key={j} className={cn("h-3", j === 0 ? "flex-[2]" : "flex-1")} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
})

const SkeletonOrderBook = memo(function SkeletonOrderBook({ rows = 8 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between px-1">
        <Skeleton className="h-2.5 w-12" />
        <Skeleton className="h-2 w-16" />
      </div>
      {/* Column headers */}
      <div className="flex items-center justify-between px-1">
        <Skeleton className="h-2 w-6" />
        <Skeleton className="h-2 w-10" />
        <Skeleton className="h-2 w-6" />
      </div>
      {/* Rows */}
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center justify-between px-1.5">
          <Skeleton className="h-3 w-12" />
          <Skeleton className="h-3 w-12" />
          <Skeleton className="h-3 w-12" />
        </div>
      ))}
      {/* Spread divider */}
      <div className="flex items-center justify-center py-1 rounded bg-muted/30">
        <Skeleton className="h-2 w-20" />
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={`bid-${i}`} className="flex items-center justify-between px-1.5">
          <Skeleton className="h-3 w-12" />
          <Skeleton className="h-3 w-12" />
          <Skeleton className="h-3 w-12" />
        </div>
      ))}
    </div>
  )
})

const SkeletonOrderBookPanel = memo(function SkeletonOrderBookPanel() {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="mb-4 flex items-center justify-between">
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-3 w-12" />
      </div>
      <SkeletonOrderBook />
    </div>
  )
})

export {
  Skeleton,
  SkeletonMarketCard,
  SkeletonMarketGrid,
  SkeletonTradeFeed,
  SkeletonOrderRow,
  SkeletonPortfolioSummary,
  SkeletonTrendingCarousel,
  SkeletonPositionsList,
  SkeletonMarketDetail,
  SkeletonTable,
  SkeletonOrderBook,
  SkeletonOrderBookPanel,
}
