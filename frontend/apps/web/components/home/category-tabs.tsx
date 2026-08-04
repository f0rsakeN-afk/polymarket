"use client"

import { useCallback, memo } from "react"
import { cn } from "@workspace/ui/lib/utils"
import { useMarketCategories } from "@/hooks/use-markets"

interface CategoryTabsProps {
  tag: string
  onTagChange: (t: string) => void
}

function CategoryTabs({ tag, onTagChange }: CategoryTabsProps) {
  const { data: categories = [] } = useMarketCategories()
  const handleClick = useCallback((cat: string) => {
    onTagChange(cat)
  }, [onTagChange])

  return (
    <div role="tablist" aria-label="Market categories" className="flex items-center gap-1 border-b border-border overflow-x-auto">
      {["All", ...categories].map((cat) => {
        const isSelected = tag.toLowerCase() === cat.toLowerCase()
        return (
          <button
            key={cat}
            role="tab"
            aria-selected={isSelected}
            onClick={() => handleClick(cat)}
            className={cn(
              "px-4 py-2 text-xs font-medium whitespace-nowrap border-b-2 -mb-px transition-colors",
              isSelected
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {cat}
          </button>
        )
      })}
    </div>
  )
}

export default memo(CategoryTabs)
