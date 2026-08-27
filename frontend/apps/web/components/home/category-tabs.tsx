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

  const handleTabClick = useCallback(
    (cat: string) => () => handleClick(cat),
    [handleClick]
  )

  return (
    <div className="flex items-center gap-1 overflow-x-auto scrollbar-hide">
      {["All", ...categories].map((cat) => {
        const isSelected = tag.toLowerCase() === cat.toLowerCase()
        return (
          <button
            key={cat}
            onClick={handleTabClick(cat)}
            className={cn(
              "relative px-4 py-2 text-xs font-medium whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground",
              isSelected
                ? "text-foreground after:absolute after:inset-x-[-6px] after:bottom-0 after:h-[3px] after:bg-primary after:opacity-100 after:rounded-full after:transition-opacity"
                : "after:absolute after:inset-x-[-6px] after:bottom-0 after:h-[3px] after:bg-primary after:opacity-0 after:rounded-full after:transition-opacity hover:after:opacity-40"
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
