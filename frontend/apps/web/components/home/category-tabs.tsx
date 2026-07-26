"use client"

import { useCallback, memo } from "react"
import { cn } from "@workspace/ui/lib/utils"

const CATEGORIES = ["All", "Crypto", "Politics", "Finance", "Science", "Sports", "Other"]

interface CategoryTabsProps {
  tag: string
  onTagChange: (t: string) => void
}

function CategoryTabs({ tag, onTagChange }: CategoryTabsProps) {
  const handleClick = useCallback((cat: string) => {
    onTagChange(cat)
  }, [onTagChange])

  return (
    <div className="flex items-center gap-1 border-b border-border overflow-x-auto">
      {CATEGORIES.map((cat) => (
        <button
          key={cat}
          onClick={() => handleClick(cat)}
          className={cn(
            "px-4 py-2 text-xs font-medium whitespace-nowrap border-b-2 -mb-px transition-colors",
            tag.toLowerCase() === cat.toLowerCase()
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground"
          )}
        >
          {cat}
        </button>
      ))}
    </div>
  )
}

export default memo(CategoryTabs)
