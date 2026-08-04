"use client"

import { useInfiniteQuery } from "@tanstack/react-query"
import { listPositions } from "@/lib/api/positions"
import type { Position } from "@/hooks/api/types/order"

export function usePositions() {
  return useInfiniteQuery({
    queryKey: ["positions"] as const,
    queryFn: ({ pageParam }) => listPositions({ page: pageParam, page_size: 20 }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _, lastPageParam) =>
      lastPage.has_more ? lastPageParam + 1 : undefined,
    select: (data) => ({
      positions: data.pages.flatMap((p) => p.data) as Position[],
      hasMore: data.pages[data.pages.length - 1]?.has_more ?? false,
    }),
  })
}
