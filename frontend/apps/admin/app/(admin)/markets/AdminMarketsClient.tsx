"use client"

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { sileo } from "sileo"
import { Check, X } from "lucide-react"

import { adminApi } from "@workspace/api-client/admin"
import { apiErrorMessage } from "@workspace/api-client/client"
import { queryKeys } from "@/lib/queryKeys"
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

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.adminMarkets(status, 1),
    queryFn: () => adminApi.markets(status, 1, 50).then((r) => r.data),
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

  const reject = useMutation({
    mutationFn: (id: string) => adminApi.rejectMarket(id),
    onSuccess: () => {
      refresh()
      sileo.success({ title: "Market rejected" })
    },
    onError: (err) =>
      sileo.error({ title: apiErrorMessage(err, "Could not reject market") }),
  })

  const rows = data ?? []
  const pending = status === "pending_review"

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Moderation</h1>
          <p className="text-sm text-muted-foreground">
            {pending
              ? "Markets waiting on a decision before they become tradable."
              : "Browse by status."}
          </p>
        </div>
        <div className="flex gap-1" role="group" aria-label="Filter by status">
          {FILTERS.map((f) => (
            <Button
              key={f.value}
              variant={status === f.value ? "default" : "outline"}
              size="sm"
              onClick={() => setStatus(f.value)}
              aria-pressed={status === f.value}
            >
              {f.label}
            </Button>
          ))}
        </div>
      </div>

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
                        disabled={reject.isPending}
                        onClick={() => reject.mutate(market.id)}
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
    </div>
  )
}