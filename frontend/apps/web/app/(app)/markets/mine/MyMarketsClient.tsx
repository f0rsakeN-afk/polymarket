"use client"

/**
 * My markets — every submission, and what became of it.
 *
 * ## Why this page exists at all
 *
 * Submitting a market was write-only. The endpoint put it in a review queue, and
 * the only way to find out what happened was to keep the slug and try the direct
 * link, which 404s for anyone but the author and says nothing either way. There
 * was no list, no status, and no explanation.
 *
 * That is the worst possible shape for a feature whose entire value is
 * "propose something and find out whether it got accepted".
 *
 * ## What each state has to tell the user
 *
 * The states are not interchangeable, so they are not rendered as one row with a
 * varying badge:
 *
 * - **pending_review** — the only thing to say is that a human has not looked at
 *   it yet. Anything more specific would be a guess.
 * - **rejected** — the reason, in full, stated as the reason. This is the one the
 *   page exists for, so it is not truncated into a tooltip.
 * - **active** — the live link and the current prices. A published market the
 *   author cannot click through to is a small, silly dead end.
 * - **closed / resolving / resolved / dispute_window** — the outcome where there
 *   is one, because "resolved" without saying who won is not information.
 */

import { useCallback, useMemo, useState } from "react"
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import {
  ArrowUpRight,
  Ban,
  CheckCircle2,
  Clock,
  Plus,
  SearchX,
} from "lucide-react"

import { listMyMarkets } from "@/lib/api/markets"
import type { MarketResponse } from "@/hooks/api/types/market"
import { useCurrentUser } from "@/hooks/use-auth"
import { queryKeys } from "@/lib/api/queryKeys"
import { Button, buttonVariants } from "@workspace/ui/components/button"
import { Badge } from "@workspace/ui/components/badge"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Spinner } from "@workspace/ui/components/spinner"
import { cn } from "@workspace/ui/lib/utils"

/**
 * Status → how it reads, what colour, what icon.
 *
 * `pending_review` deliberately has no icon indicating progress or approval. It
 * is a queue position, not a forecast, and drawing it as either would be a
 * promise the system cannot keep.
 */
const STATUS_META: Record<
  string,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" }
> = {
  pending_review: { label: "In review", variant: "secondary" },
  rejected: { label: "Declined", variant: "destructive" },
  active: { label: "Live", variant: "default" },
  closed: { label: "Trading closed", variant: "outline" },
  resolving: { label: "Resolving", variant: "secondary" },
  resolved: { label: "Resolved", variant: "outline" },
  dispute_window: { label: "In dispute window", variant: "secondary" },
}

function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? { label: status, variant: "outline" as const }
  return (
    <Badge variant={meta.variant} className="capitalize">
      {meta.label}
    </Badge>
  )
}

/** The one-line explanation for the state, written for the person who submitted it. */
function StatusNote({ market }: { market: MarketResponse }) {
  switch (market.status) {
    case "pending_review":
      return (
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <Clock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          Waiting for a moderator. Nothing is needed from you.
        </p>
      )
    case "rejected":
      return (
        // Not truncated. A reason hidden behind a hover is a reason nobody reads,
        // and the author has nowhere else to look.
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2">
          {/* Heading says *why*, not *that* — the badge above already says the
              state, and repeating it wastes the one line that should carry the
              reason. */}
          <p className="flex items-center gap-1.5 text-xs font-medium text-destructive">
            <Ban className="size-3.5 shrink-0" aria-hidden />
            Why it was declined
            {market.rejected_at ? (
              <span className="font-normal text-muted-foreground">
                on {new Date(market.rejected_at).toLocaleDateString()}
              </span>
            ) : null}
          </p>
          {market.rejection_reason ? (
            <p className="mt-1 text-sm text-foreground">{market.rejection_reason}</p>
          ) : (
            <p className="mt-1 text-xs text-muted-foreground">
              No reason was recorded. Contact support if you need one.
            </p>
          )}
        </div>
      )
    case "active":
      return (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <CheckCircle2 className="size-3.5 shrink-0" aria-hidden />
          Live and tradable.
        </p>
      )
    case "resolved":
      return (
        <p className="text-xs text-muted-foreground">
          Resolved
          {market.winning_outcome_name
            ? ` — ${market.winning_outcome_name} won.`
            : "."}
        </p>
      )
    default:
      return null
  }
}

function MarketRow({ market, highlighted }: { market: MarketResponse; highlighted: boolean }) {
  const isLive = market.status === "active" || market.status === "dispute_window"
  // Declined and pending markets are not tradable, so offering a "View market"
  // link that lands on a page saying "not found" would be the exact dead end
  // this page is meant to remove. Authors can still open them — the API allows
  // it for them — but it is not the primary action.
  const canOpen = market.status !== "pending_review" && market.status !== "rejected"

  return (
    <li
      className={cn(
        "px-4 py-4 transition-colors",
        highlighted && "bg-primary/5 ring-1 ring-inset ring-primary/30"
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={market.status} />
            {market.category ? (
              <span className="text-xs text-muted-foreground">{market.category}</span>
            ) : null}
          </div>
          <p className="mt-1.5 text-sm font-medium">{market.question}</p>
          <p className="mt-0.5 font-mono text-xs text-muted-foreground">
            /markets/{market.slug}
          </p>
          <div className="mt-2 space-y-2">
            <StatusNote market={market} />
            {market.resolution_criteria ? (
              <details className="text-xs">
                <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                  Resolution criteria
                </summary>
                <p className="mt-1 max-w-prose text-muted-foreground">
                  {market.resolution_criteria}
                </p>
                {market.resolution_source ? (
                  <p className="mt-1 text-muted-foreground">
                    Source: {market.resolution_source}
                  </p>
                ) : null}
              </details>
            ) : null}
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2 text-right">
          {isLive ? (
            <p className="text-sm tabular-nums">
              <span className="font-medium">
                {Math.round(Number(market.yes_price ?? 0) * 100)}%
              </span>{" "}
              <span className="text-xs text-muted-foreground">Yes</span>
            </p>
          ) : null}
          <p className="text-xs text-muted-foreground">
            Submitted {new Date(market.closes_at).toLocaleDateString()}
          </p>
          {/* A styled `Link`, not `Button render={<Link/>}`: Base UI's Button
              stamps `role="button"` on an anchor, which drops it out of a screen
              reader's list of links and removes open-in-new-tab — both expected
              on something that navigates. */}
          {canOpen ? (
            <Link
              href={`/markets/${market.slug}`}
              className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            >
              View market
              <ArrowUpRight className="size-3.5" aria-hidden />
            </Link>
          ) : null}
        </div>
      </div>
    </li>
  )
}

export default function MyMarketsClient() {
  const { data: user, isLoading: userLoading } = useCurrentUser()
  const [page, setPage] = useState(1)

  /**
   * Gated on `user`, not just on "mounted".
   *
   * Auth here is cookie-based, so a signed-out visitor's request is a 401 and
   * not an error. Firing it anyway produces a spurious error toast on a page
   * that simply has nothing to show them.
   */
  const query = useQuery({
    queryKey: queryKeys.myMarkets(page),
    queryFn: () => listMyMarkets({ page, pageSize: 20 }),
    enabled: !!user,
  })

  const markets = useMemo(() => query.data?.data ?? [], [query.data])
  const total = query.data?.total ?? 0
  const hasMore = query.data?.has_more ?? false

  const retry = useCallback(() => query.refetch(), [query])

  if (userLoading || (query.isLoading && !!user)) {
    return (
      <div
        className="flex min-h-64 items-center justify-center"
        role="status"
        aria-live="polite"
      >
        <Spinner className="size-5" />
        <span className="sr-only">Loading your markets</span>
      </div>
    )
  }

  if (!user) return null

  if (query.isError) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
          <p className="text-sm text-muted-foreground">
            Your markets could not be loaded.
          </p>
          <Button variant="outline" size="sm" onClick={retry}>
            Try again
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">My markets</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {total === 0
              ? "Every market you have proposed, and where each one stands."
              : `${total} market${total === 1 ? "" : "s"} proposed • ${
                  markets.filter((m) => m.status === "active").length
                } live`}
          </p>
        </div>
        <Link
          href="/markets/new"
          className={cn(buttonVariants({ size: "sm" }))}
        >
          <Plus className="size-4" aria-hidden />
          Propose a market
        </Link>
      </div>

      {markets.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-4 py-16 text-center">
            <SearchX className="size-8 text-muted-foreground" aria-hidden />
            <div className="space-y-1">
              <p className="text-sm font-medium">You have not proposed a market yet</p>
              <p className="max-w-sm text-sm text-muted-foreground">
                Ask something with a clear answer and a date it can close. A
                moderator reviews it before it becomes tradable.
              </p>
            </div>
            <Link
              href="/markets/new"
              className={cn(buttonVariants({ size: "sm" }))}
            >
              <Plus className="size-4" aria-hidden />
              Propose your first market
            </Link>
          </CardContent>
        </Card>
      ) : (
        <>
          <Card className="overflow-hidden py-0">
            <ul className="divide-y">
              {markets.map((market) => (
                <MarketRow key={market.id} market={market} highlighted={false} />
              ))}
            </ul>
          </Card>

          {/* Paging appears only when there is somewhere to go. A permanently
              visible disabled "Previous" on a single page is a control that
              teaches people it does nothing. */}
          {hasMore || page > 1 ? (
            <div className="flex items-center justify-between">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </Button>
              <span className="text-xs text-muted-foreground" aria-live="polite">
                Page {page} of {Math.max(1, Math.ceil(total / 20))}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={!hasMore}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}