"use client"

/**
 * Approving several queued markets at once.
 *
 * ## Why only approve is batched
 *
 * A rejection carries a reason its author reads at sign-in. One reason applied
 * to forty submissions is not forty decisions, it is one decision copied forty
 * times - and it is the author who has to act on it. So rejection stays
 * one-at-a-time with its own reason, and only approval is batched.
 *
 * That is not a symmetry argument. Approval publishes a market that has already
 * been read and judged acceptable; the judgement happened during triage and the
 * click is the bookkeeping. Rejection's judgement *is* the reason, so it cannot
 * be pre-made for someone else.
 *
 * ## Selection is page-scoped, deliberately
 *
 * "Select all" means the fifty rows on this page, never "every matching market
 * on every page". A control that quietly widens past what the operator can see
 * is how a moderation queue approves three hundred markets that nobody looked
 * at. There is no cross-page selection to reach for.
 *
 * ## Partial failure is reported, never summarised as success
 *
 * Every approval is its own request with its own outcome. Nineteen successes
 * and one refusal is a fact about the queue, and reporting "20 approved" because
 * nineteen went through is how a refused market goes unnoticed until somebody
 * opens it and finds it untradable.
 */

import { useState } from "react"
import { Check, X } from "lucide-react"

import type { AdminMarketRow } from "@workspace/api-client/admin"
import { Button } from "@workspace/ui/components/button"
import { Checkbox } from "@workspace/ui/components/checkbox"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@workspace/ui/components/alert-dialog"

/** How many questions the confirmation names before it summarises the rest. */
const NAMED = 5

export function BulkApproveBar({
  selected,
  totalOnPage,
  isRunning,
  onToggleAll,
  onClear,
  onConfirm,
}: {
  /** The selected markets, in page order. */
  selected: AdminMarketRow[]
  /** How many rows are on the page - for "all of these" to be truthful. */
  totalOnPage: number
  isRunning: boolean
  onToggleAll: (checked: boolean) => void
  onClear: () => void
  onConfirm: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  const count = selected.length
  const allSelected = count > 0 && count === totalOnPage
  // Base UI keeps `checked` and `indeterminate` apart: a boolean is not a
  // tri-state. `checked` answers "are they all on", `indeterminate` answers
  // "are some on", and setting both is how a control ends up claiming a
  // certainty it does not have.
  const someSelected = count > 0 && !allSelected

  return (
    <>
      {count > 0 ? (
        <div
          role="region"
          aria-label="Bulk actions"
          className="flex flex-wrap items-center gap-3 rounded-md border bg-muted/40 px-3 py-2"
        >
          <Checkbox
            checked={allSelected}
            indeterminate={someSelected}
            onCheckedChange={(checked: boolean) => onToggleAll(checked)}
            aria-label={
              allSelected
                ? `Clear all ${count} selected markets`
                : `Select all ${totalOnPage} markets on this page`
            }
          />
          <p className="text-sm">
            <span className="font-medium tabular-nums">{count}</span> of{" "}
            <span className="tabular-nums">{totalOnPage}</span> selected
          </p>
          <Button size="sm" disabled={isRunning} onClick={() => setConfirming(true)}>
            <Check className="size-3.5" />
            {isRunning ? "Approving…" : `Approve ${count}`}
          </Button>
          <Button size="sm" variant="ghost" disabled={isRunning} onClick={onClear}>
            <X className="size-3.5" />
            Clear
          </Button>
        </div>
      ) : null}

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Approve {count} market{count === 1 ? "" : "s"}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              Approved markets become tradable immediately. Only the{" "}
              {count === 1 ? "market" : "markets"} you selected on this page are
              affected — nothing else in the queue is touched.
            </AlertDialogDescription>
          </AlertDialogHeader>

          {/* The questions, so the last look before publishing is a real one.
              An operator confirming a count they never counted is not
              confirming anything. */}
          <ul className="max-h-48 space-y-1 overflow-y-auto rounded-md border p-2 text-xs">
            {selected.slice(0, NAMED).map((market) => (
              <li key={market.id} className="truncate">
                {market.question}
              </li>
            ))}
            {count > NAMED ? (
              <li className="text-muted-foreground">
                …and {count - NAMED} more on this page.
              </li>
            ) : null}
          </ul>

          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                // Closed here, before the work starts. Handing the click straight
                // to the parent's handler left the dialog open for the length of
                // the batch - so the operator watched "Approve 3" sit on screen
                // while it ran, with no way to tell it had been accepted and no
                // way out but Escape.
                setConfirming(false)
                onConfirm()
              }}
            >
              Approve {count}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
