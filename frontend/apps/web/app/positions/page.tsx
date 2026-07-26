"use client"

import { PositionsList } from "@/components/orders/positions-list"
import { usePositions } from "@/hooks/use-positions"

export default function PositionsPage() {
  const { data, isLoading, fetchNextPage, hasNextPage } = usePositions()

  return (
    <div className="container mx-auto max-w-4xl px-4 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Positions</h1>
        <p className="mt-1 text-muted-foreground">Your active positions and P&amp;L</p>
      </div>
      <PositionsList
        positions={data?.positions ?? []}
        loading={isLoading}
        hasMore={hasNextPage ?? false}
        onLoadMore={fetchNextPage}
      />
    </div>
  )
}
