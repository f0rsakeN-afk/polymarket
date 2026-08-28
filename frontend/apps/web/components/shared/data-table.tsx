"use client"

import { useState, useMemo, useCallback, useEffect } from "react"
import { ChevronUp, ChevronDown, ChevronsUpDown, ChevronLeft, ChevronRight, RotateCcw } from "lucide-react"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@workspace/ui/components/table"
import { Checkbox } from "@workspace/ui/components/checkbox"
import { Button } from "@workspace/ui/components/button"
import { Card, CardContent } from "@workspace/ui/components/card"
import { cn } from "@workspace/ui/lib/utils"
import type React from "react"

export interface Column<T> {
  key: keyof T | string
  header: string
  render?: (row: T) => React.ReactNode
  sortable?: boolean
  className?: string
  visible?: boolean
}

export interface DataTableProps<T> {
  data: T[]
  columns: Column<T>[]
  loading?: boolean
  error?: Error | null
  onRetry?: () => void
  selectable?: boolean
  selectedIds?: Set<string>
  onSelectionChange?: (ids: Set<string>) => void
  pagination?: {
    page: number
    pageSize: number
    total: number
    onPageChange: (page: number) => void
  }
  emptyMessage?: string
  rowKey: (row: T) => string
  skeletonRows?: number
}

type SortDir = "asc" | "desc" | null

function useSort<T>(data: T[], columns: Column<T>[], rowKey: (row: T) => string) {
  const [sortCol, setSortCol] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>(null)

  const sorted = useMemo(() => {
    if (!sortCol || !sortDir) return data
    const col = columns.find((c) => c.key === sortCol)
    if (!col) return data
    return [...data].sort((a, b) => {
      const av = (a as Record<string, unknown>)[sortCol as string]
      const bv = (b as Record<string, unknown>)[sortCol as string]
      if (av == null && bv == null) return 0
      if (av == null) return sortDir === "asc" ? 1 : -1
      if (bv == null) return sortDir === "asc" ? -1 : 1
      const cmp = av < bv ? -1 : av > bv ? 1 : 0
      return sortDir === "asc" ? cmp : -cmp
    })
  }, [data, sortCol, sortDir, columns])

  const handleSort = useCallback((key: string) => {
    setSortCol((prev) => {
      if (prev !== key) {
        setSortDir("asc")
        return key
      }
      setSortDir((d) => {
        if (d === "asc") return "desc"
        if (d === "desc") {
          setSortCol(null)
          return null
        }
        return "asc"
      })
      return prev
    })
  }, [])

  const SortIcon = useCallback(
    ({ colKey }: { colKey: string }) => {
      if (sortCol !== colKey) return <ChevronsUpDown className="size-3 opacity-40" />
      if (sortDir === "asc") return <ChevronUp className="size-3" />
      return <ChevronDown className="size-3" />
    },
    [sortCol, sortDir]
  )

  return { sorted, handleSort, SortIcon }
}

function SkeletonRows({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, i) => (
        <TableRow key={i}>
          {Array.from({ length: cols }).map((_, j) => (
            <TableCell key={j}>
              <div className="h-3 w-full animate-pulse rounded bg-muted/60" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  )
}

function DataTableSkeleton<T>({ columns, selectable, skeletonRows = 5 }: { columns: Column<T>[]; selectable?: boolean; skeletonRows?: number }) {
  const cols = columns.filter((c) => c.visible !== false).length + (selectable ? 1 : 0)
  return (
    <Card className="overflow-hidden pt-0">
      <div className="overflow-auto" style={{ maxHeight: "600px", minHeight: "200px" }}>
        <Table noWrapper className="w-full min-w-[640px]">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              {selectable && <TableHead className="w-10" />}
              {columns
                .filter((c) => c.visible !== false)
                .map((col) => (
                  <TableHead key={col.key as string} className={cn("select-none", col.className)}>
                    <div className="h-3 w-16 animate-pulse rounded bg-muted/60" />
                  </TableHead>
                ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            <SkeletonRows rows={skeletonRows} cols={cols} />
          </TableBody>
        </Table>
      </div>
    </Card>
  )
}

export function DataTable<T>({
  data,
  columns,
  loading,
  error,
  onRetry,
  selectable,
  selectedIds = new Set(),
  onSelectionChange,
  pagination,
  emptyMessage = "No data found",
  rowKey,
  skeletonRows = 5,
}: DataTableProps<T>) {
  const [localSelected, setLocalSelected] = useState<Set<string>>(selectedIds)
  const [expanded, setExpanded] = useState(false)

  const visibleColumns = columns.filter((c) => c.visible !== false)
  const { sorted, handleSort, SortIcon } = useSort(data, columns, rowKey)

  // Sync local selection with prop
  useEffect(() => {
    setLocalSelected(selectedIds)
  }, [selectedIds])

  const handleSelectAll = useCallback(
    (checked: boolean) => {
      const newSet = checked ? new Set(sorted.map((row) => rowKey(row))) : new Set<string>()
      setLocalSelected(newSet)
      onSelectionChange?.(newSet)
    },
    [sorted, rowKey, onSelectionChange]
  )

  const handleSelectRow = useCallback(
    (id: string, checked: boolean) => {
      const newSet = new Set(localSelected)
      if (checked) newSet.add(id)
      else newSet.delete(id)
      setLocalSelected(newSet)
      onSelectionChange?.(newSet)
    },
    [localSelected, onSelectionChange]
  )

  const totalPages = pagination ? Math.ceil(pagination.total / pagination.pageSize) : 1
  const currentPage = pagination?.page ?? 1

  const handlePrevPage = useCallback(
    () => pagination?.onPageChange(currentPage - 1),
    [pagination, currentPage]
  )
  const handleNextPage = useCallback(
    () => pagination?.onPageChange(currentPage + 1),
    [pagination, currentPage]
  )

  const allSelected = sorted.length > 0 && sorted.every((row) => localSelected.has(rowKey(row)))
  const someSelected = sorted.some((row) => localSelected.has(rowKey(row)))

  if (error) {
    return (
      <Card>
        <CardContent className="flex h-48 flex-col items-center justify-center gap-3">
          <p className="text-sm text-destructive">Failed to load data</p>
          {onRetry && (
            <Button size="sm" variant="outline" onClick={onRetry}>
              <RotateCcw className="size-3 mr-1" />
              Retry
            </Button>
          )}
        </CardContent>
      </Card>
    )
  }

  if (loading && data.length === 0) {
    return <DataTableSkeleton columns={columns} selectable={selectable} skeletonRows={skeletonRows} />
  }

  if (data.length === 0) {
    return (
      <Card>
        <CardContent className="flex h-48 items-center justify-center text-sm text-muted-foreground">
          {emptyMessage}
        </CardContent>
      </Card>
    )
  }

  return (
    <>
      <Card className="overflow-hidden pt-0">
        <div className="overflow-auto" style={{ maxHeight: "600px", minHeight: "200px" }}>
          <Table noWrapper className="w-full min-w-[640px]">
            <TableHeader className="sticky top-0 z-20 bg-muted">
              <TableRow className="hover:bg-transparent">
                {selectable && (
                  <TableHead className="w-10">
                    <Checkbox
                      checked={allSelected}
                      onCheckedChange={handleSelectAll}
                      aria-label="Select all"
                    />
                  </TableHead>
                )}
                {visibleColumns.map((col) => (
                  <TableHead
                    key={col.key as string}
                    className={cn(
                      col.sortable ? "cursor-pointer select-none hover:bg-muted/80" : "",
                      col.className
                    )}
                    onClick={col.sortable ? () => handleSort(col.key as string) : undefined}
                  >
                    <div className="flex items-center gap-1">
                      {col.header}
                      {col.sortable && <SortIcon colKey={col.key as string} />}
                    </div>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((row) => {
                const id = rowKey(row)
                const isSelected = localSelected.has(id)
                return (
                  <TableRow
                    key={id}
                    className={cn(isSelected && "bg-muted/50")}
                    data-state={isSelected ? "selected" : undefined}
                  >
                    {selectable && (
                      <TableCell className="w-10">
                        <Checkbox
                          checked={isSelected}
                          onCheckedChange={(checked) => handleSelectRow(id, Boolean(checked))}
                          aria-label={`Select row ${id}`}
                        />
                      </TableCell>
                    )}
                    {visibleColumns.map((col) => (
                      <TableCell key={col.key as string} className={col.className}>
                        {col.render ? col.render(row) : String((row as Record<string, unknown>)[col.key as string] ?? "—")}
                      </TableCell>
                    ))}
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      </Card>

      {pagination && totalPages > 1 && (
        <div className="flex items-center justify-between px-2 py-3">
          <div className="text-xs text-muted-foreground">
            Page {currentPage} of {totalPages} ({pagination.total} total)
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              disabled={currentPage <= 1}
              onClick={handlePrevPage}
              aria-label="Previous page"
            >
              <ChevronLeft className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              disabled={currentPage >= totalPages}
              onClick={handleNextPage}
              aria-label="Next page"
            >
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      )}
    </>
  )
}
