"use client"

import { useCallback } from "react"
import TrendingCarouselItem from "./trending-carousel-item"
import { useCarouselScroll } from "@/hooks/use-carousel-scroll"
import type { MarketResponse } from "@/hooks/api/types/market"
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
    <section aria-label="Trending markets" className="relative group/carousel">
      <div
        ref={containerRef}
        role="list"
        aria-label="Trending markets carousel"
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
          aria-label="Scroll left"
          className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-2 size-8 rounded-full bg-background border border-border shadow-sm flex items-center justify-center opacity-0 group-hover/carousel:opacity-100 transition-opacity"
        >
          <ChevronLeftIcon className="size-4" aria-hidden="true" />
        </button>
      )}
      {canScrollRight && (
        <button
          onClick={handleScrollRight}
          aria-label="Scroll right"
          className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-2 size-8 rounded-full bg-background border border-border shadow-sm flex items-center justify-center opacity-0 group-hover/carousel:opacity-100 transition-opacity"
        >
          <ChevronRightIcon className="size-4" aria-hidden="true" />
        </button>
      )}
    </section>
  )
}

export default TrendingCarousel
