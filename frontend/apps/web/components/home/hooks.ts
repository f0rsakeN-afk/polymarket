"use client"

import { useCallback, useEffect, useRef, useState } from "react"

export function useCarouselScroll() {
  const containerRef = useRef<HTMLDivElement>(null)
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(true)

  const checkScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    setCanScrollLeft(el.scrollLeft > 0)
    setCanScrollRight(el.scrollLeft < el.scrollWidth - el.clientWidth - 8)
  }, [])

  useEffect(() => {
    checkScroll()
    const el = containerRef.current
    if (el) el.addEventListener("scroll", checkScroll, { passive: true })
    return () => { if (el) el.removeEventListener("scroll", checkScroll) }
  }, [checkScroll])

  const scrollLeft = useCallback(() => {
    containerRef.current?.scrollBy({ left: -340, behavior: "smooth" })
  }, [])

  const scrollRight = useCallback(() => {
    containerRef.current?.scrollBy({ left: 340, behavior: "smooth" })
  }, [])

  return { containerRef, canScrollLeft, canScrollRight, scrollLeft, scrollRight }
}
