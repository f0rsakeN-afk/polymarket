"use client"

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { sileo } from "sileo"
import { Check, X } from "lucide-react"

import { adminApi, type AdminMarketRow } from "@workspace/api-client/admin"
import { apiErrorMessage } from "@workspace/api-client/client"
import { queryKeys } from "@/lib/queryKeys"
import { PageHeader } from "@/components/page-header"
import { Pagination } from "@/components/pagination"
import { RejectMarketDialog } from "@/components/reject-market-dialog"
import { Button } from "@workspace/ui/components/button"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Badge } from "@workspace/ui/components/badge"
import { Spinner } from "@workspace/ui/components/spinner"

/**
 * The moderation queue.
 *
 * Only `pending_review` by default, because that is the actionable set — a
 * moderator opening this page wants the markets waiting on them, not the whole
 * catalogue. The other statuses are one click away for the "why did that one get
 * rejected?" question, which is why they are a filter rather than absent.
 */
const FILTERS = [
  { value: "pending_review", label: "Awaiting review" },
  { value: "rejected", label: "Rejected" },
  { value: "active", label: "Active" },
  { value: "resolved", label: "Resolved" },
]

export function AdminMarketsClient() {
  const qc = useQueryClient()
  const [status, setStatus] = useState("pending_review")
  const [page, setPage] = useState(1)
  // Changing a filter while on a later page lands you on an empty page of the
  // new filter, which reads as "there is nothing here" rather than "start again".
  const resetToFirstPage = () => setPage(1)

  const { data: result, isLoading } = useQuery({
    queryKey: queryKeys.adminMarkets(status, page),
    queryFn: () => adminApi.markets(status, page, 50),
    retry: false,
  })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["admin", "markets"] })
  }

  const approve = useMutation({
    mutationFn: (id: string) => adminApi.approveMarket(id),
    onSuccess: () => {
      refresh()
      sileo.success({ title: "Market approved" })
    },
    onError: (err) =>
      sileo.error({ title: apiErrorMessage(err, "Could not approve market") }),
  })

  const [rejecting, setRejecting] = useState<AdminMarketRow | null>(null)

  const rows = result?.data ?? []
  // Envelope, not just the rows: `total` and `has_more` are what tell an operator
  // the queue continues past what they can see.
  const total = result?.total ?? 0
  const hasMore = result?.has_more ?? false
  const pending = status === "pending_review"

  return (
    <div className="space-y-4">
      <PageHeader
        title="Moderation"
        description={
          pending
            ? "Markets waiting on a decision before they become tradable."
            : "Browse by status."
        }
        actions={
          <div className="flex gap-1" role="group" aria-label="Filter by status">
            {FILTERS.map((f) => (
              <Button
                key={f.value}
                variant={status === f.value ? "default" : "outline"}
                size="sm"
                onClick={() => { resetToFirstPage(); setStatus(f.value); }}
                aria-pressed={status === f.value}
              >
                {f.label}
              </Button>
            ))}
          </div>
        }
      />

      <Card className="overflow-hidden pt-0">
        {isLoading ? (
          <CardContent role="status" className="flex h-48 items-center justify-center">
            <Spinner className="size-5" />
            <span className="sr-only">Loading markets…</span>
          </CardContent>
        ) : rows.length === 0 ? (
          <CardContent
            role="status"
            className="flex h-48 flex-col items-center justify-center gap-2 text-sm text-muted-foreground"
          >
            <p className="font-medium text-foreground">Nothing here</p>
            <p className="text-xs">
              {pending
                ? "No markets are waiting for review."
                : `No markets with status “${status}”.`}
            </p>
          </CardContent>
        ) : (
          <ul className="divide-y">
            {rows.map((market) => (
              <li
                key={market.id}
                className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium">{market.question}</p>
                  <p className="text-xs text-muted-foreground">
                    /{market.slug} ·{" "}
                    {new Date(market.created_at).toLocaleDateString()}
                  </p>
                  {/* The reason, on the row that needs it.
                      "Why was this declined?" is the first question asked about
                      every rejected submission in this list, and answering it
                      without opening each one is the difference between triage
                      and a click-through. Shown whatever the filter, because the
                      queue is browsed by status and the rejected filter is where
                      these all live. */}
                  {market.rejection_reason ? (
                    <p className="mt-1 max-w-prose text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">
                        Declined:&nbsp;
                      </span>
                      {market.rejection_reason}
                    </p>
                  ) : null}
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="secondary" className="capitalize">
                    {market.status.replace("_", " ")}
                  </Badge>
                  {pending && (
                    <>
                      <Button
                        size="sm"
                        disabled={approve.isPending}
                        onClick={() => approve.mutate(market.id)}
                      >
                        <Check className="size-3.5" />
                        Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setRejecting(market)}
                        className="text-destructive hover:bg-destructive/10"
                      >
                        <X className="size-3.5" />
                        Reject
                      </Button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <RejectMarketDialog
        key={rejecting?.id ?? "no-reject-target"}
        market={
          rejecting
            ? { id: rejecting.id, slug: rejecting.slug, question: rejecting.question }
            : null
        }
        onOpenChange={(open) => !open && setRejecting(null)}
      />

      <Pagination
        page={page}
        pageSize={50}
        total={total}
        hasMore={hasMore}
        itemLabel="markets"
        isLoading={isLoading}
        onPageChange={setPage}
      />
    </div>
  )
}