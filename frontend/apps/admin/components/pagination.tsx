"use client"

/**
 * Page controls.
 *
 * ## Why this exists rather than three copies of the same block
 *
 * The users list had working pagination and the disputes, markets and audit views
 * did not — each pinned to `page: 1`, so an operator saw the first page of a
 * queue and no indication that anything else existed. For the moderation queue
 * that is the serious one: an unresolved dispute on page 3 is invisible, and the
 * page reads as "this is everything".
 *
 * Written once because three hand-maintained copies of a prev/next block drift,
 * and the drift is invisible until someone notices a queue that stops early.
 *
 * ## What it deliberately does not render
 *
 * The controls only appear when there is somewhere to go. A permanently disabled
 * "Previous" on a single-page result is a control that teaches people it does
 * nothing — and it is on screen on every visit to the most common admin page.
 */

import { ChevronLeft, ChevronRight } from "lucide-react"

import { Button } from "@workspace/ui/components/button"

export interface PaginationProps {
  page: number
  pageSize: number
  /** Total rows, so the last page and the count can both be shown. */
  total?: number
  /** The server's own answer, so the UI never disagrees with what it was given. */
  hasMore?: boolean
  onPageChange: (page: number) => void
  /** What one row is called, for the "1–25 of 130 disputes" line. */
  itemLabel?: string
  isLoading?: boolean
}

export function Pagination({
  page,
  pageSize,
  total,
  hasMore,
  onPageChange,
  itemLabel,
  isLoading = false,
}: PaginationProps) {
  const knownTotal = typeof total === "number" && Number.isFinite(total)
  const totalPages = knownTotal ? Math.max(1, Math.ceil(total / pageSize)) : null
  const lastPage = totalPages ?? (hasMore ? page + 1 : page)

  const canGoBack = page > 1 && !isLoading
  const canGoForward = (hasMore ?? false) && !isLoading

  if (!canGoBack && !canGoForward) return null

  const first = (page - 1) * pageSize + 1
  const last = knownTotal
    ? Math.min(page * pageSize, total as number)
    : page * pageSize

  return (
    <nav
      aria-label="Pagination"
      className="flex flex-wrap items-center justify-between gap-3 pt-1"
    >
      <p className="text-xs text-muted-foreground" aria-live="polite">
        {knownTotal ? (
          <>
            Showing{" "}
            <span className="font-medium tabular-nums text-foreground">
              {first.toLocaleString()}–{last.toLocaleString()}
            </span>{" "}
            of{" "}
            <span className="font-medium tabular-nums text-foreground">
              {total.toLocaleString()}
            </span>
            {itemLabel ? ` ${itemLabel}` : ""}
          </>
        ) : (
          <>
            Page <span className="tabular-nums text-foreground">{page}</span>
          </>
        )}
      </p>

      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={!canGoBack}
        >
          <ChevronLeft className="size-3.5" aria-hidden />
          Previous
        </Button>

        {/* The page number is announced as a label rather than left implicit in
            the two buttons, so a screen reader user knows where they are without
            having to count. */}
        <span className="px-1 text-xs text-muted-foreground" aria-live="polite">
          {totalPages ? (
            <>
              Page {page} of {totalPages}
            </>
          ) : hasMore ? (
            <>Page {page}</>
          ) : null}
        </span>

        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(Math.min(lastPage, page + 1))}
          disabled={!canGoForward}
        >
          Next
          <ChevronRight className="size-3.5" aria-hidden />
        </Button>
      </div>
    </nav>
  )
}