"use client"

import { useState, useEffect, useCallback, useRef, useMemo } from "react"
import { Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator } from "@workspace/ui/components/command"
import { Kbd } from "@workspace/ui/components/kbd"
import { Badge } from "@workspace/ui/components/badge"
import { cn } from "@workspace/ui/lib/utils"
import { SearchIcon, ClockIcon, XIcon } from "lucide-react"

export interface CommandItem {
  id: string
  label: string
  description?: string
  category: string
  icon?: React.ReactNode
  keywords?: string[]
  action: () => void
}

export interface CommandPaletteProps {
  items: CommandItem[]
  recentSearches?: string[]
  onRecentSearchChange?: (searches: string[]) => void
  placeholder?: string
  emptyMessage?: string
  maxRecent?: number
}

const KBD_SHORTCUTS = [
  { key: "↑", label: "navigate up" },
  { key: "↓", label: "navigate down" },
  { key: "↵", label: "select" },
  { key: "esc", label: "close" },
]

function CommandPaletteItem({ item, isSelected, onSelect }: { item: CommandItem; isSelected: boolean; onSelect: () => void }) {
  return (
    <CommandItem
      value={item.id}
      onSelect={onSelect}
      className={cn(
        "flex items-center gap-3 py-2.5 px-3 cursor-pointer",
        isSelected && "bg-muted"
      )}
    >
      {item.icon && (
        <span className="flex size-5 items-center justify-center rounded-sm bg-muted p-1">{item.icon}</span>
      )}
      <div className="flex flex-1 flex-col gap-0.5">
        <span className="text-sm font-medium">{item.label}</span>
        {item.description && (
          <span className="text-xs text-muted-foreground">{item.description}</span>
        )}
      </div>
      <Badge variant="outline" className="text-[10px] shrink-0">
        {item.category}
      </Badge>
    </CommandItem>
  )
}

export function CommandPalette({
  items,
  recentSearches = [],
  onRecentSearchChange,
  placeholder = "Search...",
  emptyMessage = "No results found.",
  maxRecent = 5,
}: CommandPaletteProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [recent, setRecent] = useState<string[]>(recentSearches)
  const inputRef = useRef<HTMLInputElement>(null)

  const openPalette = useCallback(() => setOpen(true), [])
  const closePalette = useCallback(() => { setOpen(false); setSearch("") }, [])
  const handleOpenChange = useCallback((o: boolean) => { setOpen(o); if (!o) setSearch("") }, [])

  // Group items by category
  const groupedItems = useMemo(() => {
    const groups: Record<string, CommandItem[]> = {}
    items.forEach((item) => {
      if (!groups[item.category]) groups[item.category] = []
      groups[item.category]!.push(item)
    })
    return groups
  }, [items])

  // Filter items based on search
  const filteredItems = useMemo(() => {
    if (!search.trim()) return items
    const q = search.toLowerCase()
    return items.filter(
      (item) =>
        item.label.toLowerCase().includes(q) ||
        item.description?.toLowerCase().includes(q) ||
        item.keywords?.some((k) => k.toLowerCase().includes(q))
    )
  }, [items, search])

  const filteredGrouped = useMemo(() => {
    if (!search.trim()) return groupedItems
    const groups: Record<string, CommandItem[]> = {}
    filteredItems.forEach((item) => {
      if (!groups[item.category]) groups[item.category] = []
      groups[item.category]!.push(item)
    })
    return groups
  }, [filteredItems, groupedItems, search])

  const flatFiltered = search.trim() ? filteredItems : []

  // Reset selection when search changes
  useEffect(() => {
    setSelectedIndex(0)
  }, [search])

  // Keyboard shortcut to open
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault()
        setOpen((o) => !o)
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [])

  const handleSelect = useCallback(
    (item: CommandItem) => {
      // Add to recent
      const label = item.label
      const newRecent = [label, ...recent.filter((r) => r !== label)].slice(0, maxRecent)
      setRecent(newRecent)
      onRecentSearchChange?.(newRecent)

      setOpen(false)
      setSearch("")
      item.action()
    },
    [recent, maxRecent, onRecentSearchChange]
  )

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const count = flatFiltered.length

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault()
          setSelectedIndex((i) => (i + 1) % count)
          break
        case "ArrowUp":
          e.preventDefault()
          setSelectedIndex((i) => (i - 1 + count) % count)
          break
        case "Enter":
          e.preventDefault()
          if (flatFiltered[selectedIndex]) {
            handleSelect(flatFiltered[selectedIndex])
          }
          break
        case "Escape":
          e.preventDefault()
          setOpen(false)
          setSearch("")
          break
      }
    },
    [flatFiltered, selectedIndex, handleSelect]
  )

  const handleRecentClick = useCallback(
    (label: string) => {
      setSearch(label)
      inputRef.current?.focus()
    },
    []
  )

  return (
    <>
      {/* Trigger button */}
      <button
        onClick={openPalette}
        className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted/50 transition-colors"
      >
        <SearchIcon className="size-4" />
        <span className="hidden sm:inline">Search...</span>
        <Kbd className="ml-2 hidden sm:inline-flex size-5 text-[10px]">⌘K</Kbd>
      </button>

      {/* Dialog */}
      <CommandDialog open={open} onOpenChange={handleOpenChange}>
        <div className="relative">
          <CommandInput
            ref={inputRef as React.RefObject<HTMLInputElement>}
            value={search}
            onValueChange={setSearch}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            className="border-0! bg-transparent! pb-2!"
          />
          <button
            onClick={closePalette}
            className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded hover:bg-muted"
            aria-label="Close"
          >
            <XIcon className="size-4" />
          </button>
        </div>

        <div className="border-t border-border/50" />

        {/* Keyboard shortcuts hint */}
        <div className="flex items-center gap-4 px-3 py-2 border-b border-border/50">
          {KBD_SHORTCUTS.map((s) => (
            <div key={s.key} className="flex items-center gap-1 text-[10px] text-muted-foreground">
              <Kbd className="size-4 text-[9px]">{s.key}</Kbd>
              <span>{s.label}</span>
            </div>
          ))}
        </div>

        <CommandList className="max-h-[320px]">
          {!search.trim() && recent.length > 0 && (
            <>
              <CommandGroup heading="Recent">
                {recent.map((label) => (
                  <CommandItem
                    key={label}
                    value={label}
                    onSelect={() => handleRecentClick(label)}
                    className="flex items-center gap-2 py-2 cursor-pointer"
                  >
                    <ClockIcon className="size-4 text-muted-foreground" />
                    <span>{label}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
              <CommandSeparator />
            </>
          )}

          {search.trim() && filteredItems.length === 0 && (
            <CommandEmpty>{emptyMessage}</CommandEmpty>
          )}

          {Object.entries(filteredGrouped).map(([category, categoryItems]) => (
            <CommandGroup key={category} heading={category}>
              {categoryItems.map((item, idx) => {
                const flatIdx = flatFiltered.indexOf(item)
                const isSelected = !search.trim() ? false : flatIdx === selectedIndex
                return (
                  <CommandPaletteItem
                    key={item.id}
                    item={item}
                    isSelected={isSelected}
                    onSelect={() => handleSelect(item)}
                  />
                )
              })}
            </CommandGroup>
          ))}

          {!search.trim() && Object.keys(groupedItems).length === 0 && (
            <CommandEmpty>{emptyMessage}</CommandEmpty>
          )}
        </CommandList>
      </CommandDialog>
    </>
  )
}
