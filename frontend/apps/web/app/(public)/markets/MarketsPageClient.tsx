"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { MarketList } from "@/components/markets/market-list"
import { useMarkets } from "@/hooks/api/use-markets"
import { cn } from "@workspace/ui/lib/utils"
import { Input } from "@workspace/ui/components/input"
import { SearchIcon } from "lucide-react"

const CATEGORIES = ["All", "Crypto", "Politics", "Finance", "Science", "Sports", "Other"]

export function MarketsPageClient() {
  const [category, setCategory] = useState<string>("All")
  const [search, setSearch] = useState("")
  const [query, setQuery] = useState("")
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    const timeoutId = setTimeout(() => {
      setQuery(search)
    }, 300)
    debounceRef.current = timeoutId
    return () => clearTimeout(timeoutId)
  }, [search])

  const activeCategory = category === "All" ? undefined : category
  const { data: marketsData, isLoading: marketsLoading, fetchNextPage: fetchMarketsNextPage, hasNextPage: marketsHasMore } = useMarkets({
    q: query || undefined,
    category: activeCategory,
  })

  const handleLoadMoreMarkets = useCallback(() => {
    fetchMarketsNextPage()
  }, [fetchMarketsNextPage])

  const handleCategoryClick = useCallback((cat: string) => () => setCategory(cat), [])
  const handleSearchChange = useCallback((e: { target: { value: string } }) => setSearch(e.target.value), [])

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Markets</h1>
        <p className="mt-1 text-muted-foreground text-sm">
          Browse and trade on prediction markets
        </p>
      </div>

      {/* Search */}
      <div className="relative">
        <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground pointer-events-none" />
        <Input
          type="text"
          value={search}
          onChange={handleSearchChange}
          placeholder="Search markets..."
          aria-label="Search markets"
          className="w-full h-9 pl-9 pr-4"
        />
      </div>

      {/* Category tabs */}
      <div className="flex items-center gap-1 border-b border-border overflow-x-auto scrollbar-hide">
        {CATEGORIES.map((cat) => (
          <button
            key={cat}
            onClick={handleCategoryClick(cat)}
            className={cn(
              "px-4 py-2 text-xs font-medium whitespace-nowrap border-b-2 -mb-px transition-colors",
              category === cat
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {cat}
          </button>
        ))}
      </div>

      <MarketList
        markets={marketsData?.markets ?? []}
        loading={marketsLoading}
        hasMore={marketsHasMore ?? false}
        onLoadMore={handleLoadMoreMarkets}
      />
    </div>
  )
}
