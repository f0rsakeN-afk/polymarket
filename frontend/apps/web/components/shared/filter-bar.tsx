"use client"

import { useState, useCallback, useMemo } from "react"
import { PlusIcon, XIcon, ChevronDownIcon } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Badge } from "@workspace/ui/components/badge"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@workspace/ui/components/dropdown-menu"
import { cn } from "@workspace/ui/lib/utils"

export interface FilterOption {
  key: string
  label: string
}

export interface ActiveFilter {
  key: string
  label: string
  value: string
}

export interface FilterBarProps {
  filters: FilterOption[]
  activeFilters: ActiveFilter[]
  onFilterAdd: (key: string, value: string) => void
  onFilterRemove: (key: string, value: string) => void
  onClearAll: () => void
  placeholder?: string
  className?: string
}

function FilterPill({ filter, onRemove }: { filter: ActiveFilter; onRemove: () => void }) {
  return (
    <Badge variant="outline" className="gap-1.5 pl-2 pr-1.5 py-1 text-xs font-normal">
      <span className="text-muted-foreground">{filter.label}:</span>
      <span className="font-medium">{filter.value}</span>
      <button
        onClick={onRemove}
        className="ml-0.5 rounded-sm p-0.5 hover:bg-muted-foreground/20 transition-colors"
        aria-label={`Remove ${filter.label} filter`}
      >
        <XIcon className="size-2.5" />
      </button>
    </Badge>
  )
}

export function FilterBar({
  filters,
  activeFilters,
  onFilterAdd,
  onFilterRemove,
  onClearAll,
  placeholder = "Add filter",
  className,
}: FilterBarProps) {
  const [openDropdown, setOpenDropdown] = useState<string | null>(null)

  const handleAddFilter = useCallback(
    (key: string) => {
      // For simplicity, prompt is handled by the caller via a sub-component
      // Here we just signal intent - the parent can show a value picker
      onFilterAdd(key, "")
      setOpenDropdown(null)
    },
    [onFilterAdd]
  )

  // Stable per-key callbacks — one function per filter, never recreated
  const filterCallbacks = useMemo(() => {
    const map = new Map<string, () => void>()
    for (const f of filters) {
      map.set(f.key, () => handleAddFilter(f.key))
    }
    return map
  }, [filters, handleAddFilter])

  // Get available filters (those not fully applied)
  const availableFilters = filters.filter((f) => {
    // A filter is available if it's not in activeFilters with a value
    // For multi-value filters, we always show them if there are fewer than N values
    const activeKeys = new Set(activeFilters.map((af) => af.key))
    return !activeKeys.has(f.key)
  })

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2 min-h-[36px]",
        className
      )}
    >
      {/* Active filters */}
      {activeFilters.map((filter) => (
        <FilterPill
          key={`${filter.key}-${filter.value}`}
          filter={filter}
          onRemove={() => onFilterRemove(filter.key, filter.value)}
        />
      ))}

      {/* Add filter dropdown */}
      {availableFilters.length > 0 && (
        <DropdownMenu
          open={openDropdown === "add"}
          onOpenChange={(o) => setOpenDropdown(o ? "add" : null)}
        >
          <DropdownMenuTrigger>
            <Button variant="outline" size="sm" className="h-6 gap-1 text-xs">
              <PlusIcon className="size-3" />
              {placeholder}
              <ChevronDownIcon className="size-3 ml-0.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="min-w-[160px]">
            {availableFilters.map((f) => (
              <DropdownMenuItem
                key={f.key}
                onClick={filterCallbacks.get(f.key)}
                className="cursor-pointer"
              >
                {f.label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}

      {/* Clear all */}
      {activeFilters.length > 0 && (
        <Button
          variant="ghost"
          size="sm"
          onClick={onClearAll}
          className="h-6 px-2 text-xs text-muted-foreground hover:text-destructive"
        >
          Clear all
        </Button>
      )}
    </div>
  )
}

// Hook for managing filter state
export function useFilterBar<T extends string = string>(initial?: T[]) {
  const [activeFilters, setActiveFilters] = useState<ActiveFilter[]>([])

  const addFilter = useCallback((key: string, value: string) => {
    setActiveFilters((prev) => {
      if (prev.some((f) => f.key === key && f.value === value)) return prev
      return [...prev, { key, label: key, value }]
    })
  }, [])

  const removeFilter = useCallback((key: string, value: string) => {
    setActiveFilters((prev) => prev.filter((f) => !(f.key === key && f.value === value)))
  }, [])

  const clearAll = useCallback(() => {
    setActiveFilters([])
  }, [])

  return { activeFilters, addFilter, removeFilter, clearAll }
}
