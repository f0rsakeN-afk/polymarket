"use client"

import { useCallback, memo } from "react"
import { useRouter } from "next/navigation"
import { cn } from "@workspace/ui/lib/utils"
import { useMarketCategories } from "@/hooks/api/use-markets"

interface CategoryTabsProps {
  tag: string
}

function CategoryTabs({ tag }: CategoryTabsProps) {
  const router = useRouter()
  const { data: categories = [] } = useMarketCategories()

  const handleClick = useCallback(
    (cat: string) => {
      window.scrollTo({ top: 0, behavior: "instant" })
      router.push(cat === "All" ? "/" : `/?tag=${cat.toLowerCase()}`)
    },
    [router]
  )

  return (
    <div className="flex items-center gap-1 overflow-x-auto scrollbar-hide">
      {["All", ...categories].map((cat) => {
        const isSelected = tag.toLowerCase() === cat.toLowerCase()
        return (
          <button
            key={cat}
            onClick={() => handleClick(cat)}
            className={cn(
              "px-4 py-2 text-xs font-medium whitespace-nowrap border-b-2 transition-colors",
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
