"use client"

import { useState, useEffect, useCallback, useRef, useMemo } from "react"
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@workspace/ui/components/command"
import { Kbd } from "@workspace/ui/components/kbd"
import { Badge } from "@workspace/ui/components/badge"
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

function CommandPaletteItem({ item, onSelect }: { item: CommandItem; onSelect: () => void }) {
  // cmdk scores the `value` prop together with `keywords`, so hand it the full
  // searchable text. Selection highlighting needs no manual state: the
  // CommandItem primitive styles itself from cmdk's data-selected attribute.
  const keywords = [item.description, ...(item.keywords ?? [])].filter(
    (k): k is string => Boolean(k)
  )

  return (
    <CommandItem
      value={item.label}
      keywords={keywords}
      onSelect={onSelect}
      className="flex items-center gap-3 py-2.5 px-3 cursor-pointer"
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
  const [recent, setRecent] = useState<string[]>(recentSearches)
  const inputRef = useRef<HTMLInputElement>(null)

  const openPalette = useCallback(() => setOpen(true), [])
  const closePalette = useCallback(() => { setOpen(false); setSearch("") }, [])
  const handleOpenChange = useCallback((o: boolean) => { setOpen(o); if (!o) setSearch("") }, [])

  // Group items by category. Filtering is left entirely to cmdk, which scores
  // each item's value+keywords and hides non-matches itself.
  const groupedItems = useMemo(() => {
    const groups: Record<string, CommandItem[]> = {}
    items.forEach((item) => {
      if (!groups[item.category]) groups[item.category] = []
      groups[item.category]!.push(item)
    })
    return groups
  }, [items])

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

  const handleSearchChange = useCallback((value: string) => {
    setSearch(value)
  }, [])

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
              onValueChange={handleSearchChange}
              placeholder={placeholder}
              className="border-0! bg-transparent! pb-2!"
            />
            <button
              onClick={closePalette}
              className="absolute right-3 top-1/2 -translate-y-0.5 p-1 rounded hover:bg-muted"
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
                <Kbd className="size-4 text-[10px]">{s.key}</Kbd>
                <span>{s.label}</span>
              </div>
            ))}
          </div>

          <CommandList className="max-h-[320px]">
            {/* cmdk renders CommandEmpty only when its own filtered count is 0,
                so it needs no conditional of its own. */}
            <CommandEmpty>{emptyMessage}</CommandEmpty>

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

            {Object.entries(groupedItems).map(([category, categoryItems]) => (
              <CommandGroup key={category} heading={category}>
                {categoryItems.map((item) => (
                  <CommandPaletteItem
                    key={item.id}
                    item={item}
                    onSelect={() => handleSelect(item)}
                  />
                ))}
              </CommandGroup>
            ))}
          </CommandList>
      </CommandDialog>
    </>
  )
}
