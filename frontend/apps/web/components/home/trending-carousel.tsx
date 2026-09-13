"use client"

import TrendingCarouselItem from "./trending-carousel-item"
import { useCarouselScroll } from "@/hooks/use-carousel-scroll"
import type { MarketResponse } from "@/hooks/api/types/market"
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react"

interface TrendingCarouselProps {
  markets: MarketResponse[]
}

function TrendingCarousel({ markets }: TrendingCarouselProps) {
  const { containerRef, canScrollLeft, canScrollRight, scrollLeft, scrollRight } = useCarouselScroll()

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
          onClick={scrollLeft}
          aria-label="Scroll left"
          className="absolute top-1/2 left-0 size-8 -translate-x-2 -translate-y-1/2 items-center justify-center rounded-full border border-border bg-background shadow-sm transition-opacity focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:flex md:opacity-0 md:group-hover/carousel:opacity-100 flex"
        >
          <ChevronLeftIcon className="size-4" aria-hidden="true" />
        </button>
      )}
      {canScrollRight && (
        <button
          onClick={scrollRight}
          aria-label="Scroll right"
          className="absolute top-1/2 right-0 size-8 translate-x-2 -translate-y-1/2 items-center justify-center rounded-full border border-border bg-background shadow-sm transition-opacity focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:flex md:opacity-0 md:group-hover/carousel:opacity-100 flex"
        >
          <ChevronRightIcon className="size-4" aria-hidden="true" />
        </button>
      )}
    </section>
  )
}

export default TrendingCarousel
