"use client"

/**
 * A dispute, in full, before anyone rules on it.
 *
 * ## Why this is a dialog and not just a link to the market
 *
 * Adjudicating a dispute resolves the market and queues settlement — it decides
 * who gets paid. It is the most consequential privileged action in the product,
 * and the list row carries only the question and the proposer's name.
 *
 * Two things are needed to rule fairly, and neither was on the screen:
 *
 * - **the resolution criteria**. A ruling is judged against a stated criterion.
 *   Without reading it, an operator is deciding by vibes and the losing party has
 *   a legitimate complaint. The list had a comment claiming this was shown; it
 *   was not, because the detail endpoint was never called.
 * - **the evidence the proposer supplied**. It exists on the row, but a truncated
 *   snippet next to a "Resolve" button is not the same as reading it.
 *
 * So the detail endpoint is actually called, and everything needed to make the
 * decision is in front of the operator before the ruling button is reachable.
 */

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { ExternalLink, Gavel, Scale } from "lucide-react"

import { adminApi, type AdminDisputeRow } from "@workspace/api-client/admin"
import { apiErrorMessage } from "@workspace/api-client/client"
import { Button, buttonVariants } from "@workspace/ui/components/button"
import { Badge } from "@workspace/ui/components/badge"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { Spinner } from "@workspace/ui/components/spinner"
import { cn } from "@workspace/ui/lib/utils"

interface Props {
  dispute: AdminDisputeRow | null
  onOpenChange: (open: boolean) => void
  /** Opens the ruling flow for this dispute. */
  onRule: (dispute: AdminDisputeRow) => void
}

export function DisputeDetailDialog({ dispute, onOpenChange, onRule }: Props) {
  // Keyed on the id so switching between disputes cannot show the previous
  // one's evidence against the new one's question.
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["admin", "dispute", dispute?.id],
    queryFn: () => adminApi.dispute(dispute!.id),
    enabled: Boolean(dispute),
    retry: false,
  })

  const detail = data?.data
  const evidenceUrl = detail?.evidence_url

  return (
    <Dialog open={Boolean(dispute)} onOpenChange={(open) => !open && onOpenChange(false)}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-start gap-2">
            <Scale className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-0">{detail?.market_question ?? dispute?.market_question}</span>
          </DialogTitle>
          {detail ? (
            <DialogDescription className="sr-only">
              Dispute opened by {detail.proposer_username ?? "a user"}
            </DialogDescription>
          ) : null}
        </DialogHeader>

        {isLoading ? (
          <div className="flex h-40 items-center justify-center" role="status">
            <Spinner className="size-5" />
            <span className="sr-only">Loading the dispute</span>
          </div>
        ) : isError ? (
          // A moderator cannot rule on something they cannot read, so this is a
          // dead end rather than a silent blank panel.
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm">
            <p className="font-medium text-destructive">Could not load this dispute</p>
            <p className="mt-1 text-muted-foreground">
              {apiErrorMessage(error, "Try again.")}
            </p>
          </div>
        ) : !detail ? null : (
          <div className="space-y-5">
            {/* ── What is actually in dispute ───────────────────────────── */}
            <section className="space-y-1.5">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                The disputed resolution
              </h3>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{detail.market_status}</Badge>
                <span className="text-sm">
                  Proposed outcome:{" "}
                  <span className="font-medium">
                    {detail.proposed_outcome_name ?? "not stated"}
                  </span>
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                Raised by {detail.proposer_username ?? "an unknown user"} ·{" "}
                {new Date(detail.created_at).toLocaleString()}
              </p>
            </section>

            {/* ── The criterion the ruling is judged against ─────────────── */}
            <section className="space-y-1.5">
              <h3
                className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
              >
                Resolution criteria
              </h3>
              {detail.resolution_criteria ? (
                <p className="rounded-md border bg-muted/40 p-3 text-sm">
                  {detail.resolution_criteria}
                </p>
              ) : (
                // Stated, not hidden. A market with no criteria is why this
                // dispute exists, and an operator who does not know that will
                // rule on the proposer's evidence alone and think they are being
                // careful.
                <p className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
                  <span className="font-medium">This market states no resolution criteria.</span>{" "}
                  There is nothing to judge the proposed outcome against, which is
                  usually why the dispute was raised. Ruling on the evidence alone
                  is a judgement call and will not survive an appeal.
                </p>
              )}
              {detail.resolution_source ? (
                <p className="text-xs text-muted-foreground">
                  Source: {detail.resolution_source}
                </p>
              ) : null}
            </section>

            {/* ── The proposer's evidence ────────────────────────────────── */}
            <section className="space-y-1.5">
              <h3
                className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
              >
                Evidence supplied
              </h3>
              {detail.evidence || evidenceUrl ? (
                <div className="space-y-2 rounded-md border p-3">
                  {/* Whitespace preserved: evidence is quoted text, and a
                      reflowed quote stops being quotable. */}
                  {detail.evidence ? (
                    <p className="whitespace-pre-wrap text-sm">{detail.evidence}</p>
                  ) : null}
                  {evidenceUrl ? (
                    <a
                      href={evidenceUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={cn(
                        buttonVariants({ variant: "link", size: "sm" }),
                        "h-auto p-0 text-sm"
                      )}
                    >
                      Open the linked source
                      <ExternalLink className="size-3" aria-hidden />
                      <span className="sr-only"> (opens in a new tab)</span>
                    </a>
                  ) : null}
                </div>
              ) : (
                <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
                  No evidence was supplied. That is itself a fact worth weighing
                  before ruling.
                </p>
              )}
            </section>
          </div>
        )}

        <DialogFooter className="gap-2 sm:justify-between">
          {detail ? (
            <Link
              href={`/markets?market=${detail.market_id}`}
              className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            >
              Open the market
            </Link>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
              Close
            </Button>
            {/* Disabled until the detail has loaded. Ruling is irreversible and
                pays real money, so the button must not be reachable from a row
                the operator has not actually read yet. */}
            <Button
              size="sm"
              disabled={!detail || isLoading}
              onClick={() => {
                if (dispute) onRule(dispute)
                onOpenChange(false)
              }}
            >
              <Gavel className="size-3.5" aria-hidden />
              Rule on this dispute
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}