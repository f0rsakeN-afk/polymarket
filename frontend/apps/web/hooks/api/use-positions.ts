"use client"

import { useInfiniteQuery } from "@tanstack/react-query"
import { listPositions } from "@/lib/api/positions"
import { queryKeys } from "@/lib/api/queryKeys"
import type { Position } from "@/hooks/api/types/order"

export function usePositions() {
  return useInfiniteQuery({
    queryKey: queryKeys.positions(),
    queryFn: ({ pageParam }) => listPositions({ page: pageParam, page_size: 20 }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _, lastPageParam) =>
      lastPage.data.has_more ? lastPageParam + 1 : undefined,
    select: (data) => ({
      positions: data.pages.flatMap((p) => p.data.positions) as Position[],
      hasMore: data.pages[data.pages.length - 1]?.data.has_more ?? false,
    }),
    staleTime: 10_000,
  })
}
