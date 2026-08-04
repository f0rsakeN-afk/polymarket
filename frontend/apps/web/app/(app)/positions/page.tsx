"use client"

import { useCallback } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Card } from "@workspace/ui/components/card"
import { usePositions } from "@/hooks/api/use-positions"
import { useUserSocket } from "@/hooks/use-user-socket"
import { useCurrentUser } from "@/hooks/use-auth"
import { PositionsList } from "@/components/orders/positions-list"

export const metadata = {
  robots: { index: false, follow: false },
}

export default function PositionsPage() {
  const qc = useQueryClient()
  const { data: user } = useCurrentUser()
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } = usePositions()
  const positions = data?.positions ?? []
  const hasMore = data?.hasMore ?? false

  const handleWsMessage = useCallback(
    (msg: unknown) => {
      const message = msg as { type?: string; notification?: { type?: string } }
      if (message.type === "position:update" || message.notification?.type === "order_filled") {
        qc.invalidateQueries({ queryKey: ["positions"] })
      }
    },
    [qc]
  )

  useUserSocket({
    userId: user?.id ?? "",
    onMessage: handleWsMessage,
    enabled: Boolean(user?.id),
  })

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-4">
      <h1 className="text-2xl font-semibold">Positions</h1>
      <Card className="p-4">
        <PositionsList
          positions={positions}
          loading={isLoading || isFetchingNextPage}
          hasMore={hasMore}
          onLoadMore={fetchNextPage}
        />
      </Card>
    </div>
  )
}
