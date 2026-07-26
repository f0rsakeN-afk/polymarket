"use client"

import { useCallback } from "react"
import TrendingCarouselItem from "./trending-carousel-item"
import { useCarouselScroll } from "./hooks"
import type { MarketResponse } from "@/lib/types/api"
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react"

interface TrendingCarouselProps {
  markets: MarketResponse[]
}

function TrendingCarousel({ markets }: TrendingCarouselProps) {
  const { containerRef, canScrollLeft, canScrollRight, scrollLeft, scrollRight } = useCarouselScroll()

  const handleScrollLeft = useCallback(() => scrollLeft(), [scrollLeft])
  const handleScrollRight = useCallback(() => scrollRight(), [scrollRight])

  if (markets.length === 0) return null

  return (
    <div className="relative group/carousel">
      <div
        ref={containerRef}
        className="flex gap-4 overflow-x-auto pb-2 scrollbar-hide scroll-smooth"
        style={{ scrollbarWidth: "none", msOverflowStyle: "none" }}
      >
        {markets.map((m) => (
          <TrendingCarouselItem key={m.id} market={m} />
        ))}
      </div>
      {canScrollLeft && (
        <button
          onClick={handleScrollLeft}
          className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-2 size-8 rounded-full bg-background border border-border shadow-sm flex items-center justify-center opacity-0 group-hover/carousel:opacity-100 transition-opacity"
        >
          <ChevronLeftIcon className="size-4" />
        </button>
      )}
      {canScrollRight && (
        <button
          onClick={handleScrollRight}
          className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-2 size-8 rounded-full bg-background border border-border shadow-sm flex items-center justify-center opacity-0 group-hover/carousel:opacity-100 transition-opacity"
        >
          <ChevronRightIcon className="size-4" />
        </button>
      )}
    </div>
  )
}

export default TrendingCarousel
