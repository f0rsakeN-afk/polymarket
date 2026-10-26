"use client"

/**
 * A consistent page header: title, description, and actions.
 *
 * ## Why this exists
 *
 * Five pages grew their own `<div>` + `<h1>` + `<p>` + `<Button>` arrangement,
 * and every one of them put the actions in a slightly different place — some
 * above the title, some beside it, one below. An operator moving between two
 * pages should not have to re-find the button.
 *
 * So: title and description on the left, actions on the right, wrapping to a
 * column below `sm`. The wrapping is the responsive half — on a phone the
 * actions go full-width under the title rather than squeezing the heading into
 * two lines beside a button.
 *
 * Accessibility: one `<h1>` per page, and the description is *linked* to it with
 * `aria-describedby` so a screen reader announces "Treasury, Protocol fees
 * accumulated…" as one heading rather than two disconnected strings.
 */
import type { ReactNode } from "react"

import { cn } from "@workspace/ui/lib/utils"

export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: string
  description?: string
  actions?: ReactNode
  className?: string
}) {
  const descriptionId = description ? `${title.replace(/\s+/g, "-").toLowerCase()}-description` : undefined

  return (
    <div
      className={cn(
        // `flex-wrap` + `sm:items-start` is what makes this responsive without a
        // second layout: actions drop below the heading on narrow screens and
        // sit beside it from `sm` up.
        "flex flex-col gap-3 pb-5 sm:flex-row sm:items-start sm:justify-between sm:gap-4",
        className
      )}
    >
      <div className="min-w-0 space-y-1">
        <h1
          className="truncate text-xl font-bold tracking-tight"
          aria-describedby={descriptionId}
        >
          {title}
        </h1>
        {description ? (
          <p id={descriptionId} className="text-sm text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>

      {actions ? (
        // `role="group"` with a label: a row of three buttons with no group name
        // is announced as three unrelated buttons.
        <div role="group" aria-label={`${title} actions`} className="flex shrink-0 flex-wrap items-center gap-2">
          {actions}
        </div>
      ) : null}
    </div>
  )
}