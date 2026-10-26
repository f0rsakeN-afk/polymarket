"use client"

/**
 * Where the money went.
 *
 * ## Why this exists
 *
 * The treasury page showed a balance, some pending fees, and a button to sweep
 * them. `GET /treasury/logs` existed and was never called, so the one question
 * anyone actually asks about a treasury balance — *where did this come from* —
 * had no answer anywhere in the admin app.
 *
 * That matters more here than it would elsewhere. The audit trail records the
 * `distribution` actions, but not the `fee_collected` ones: fees accrue
 * continuously from trades, so a balance that has grown with nothing showing
 * where it came from is indistinguishable from one that was invented.
 *
 * ## Signed amounts
 *
 * `fee_collected` is money in and `distribution` is money out, so they are
 * rendered with a sign rather than both as bare positive numbers. A column of
 * positive amounts, half of which are withdrawals, is a column that lies.
 */

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ArrowDownLeft, ArrowUpRight, Receipt } from "lucide-react"

import { adminApi } from "@workspace/api-client/admin"
import { queryKeys } from "@/lib/queryKeys"
import { Pagination } from "@/components/pagination"
import { Badge } from "@workspace/ui/components/badge"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Spinner } from "@workspace/ui/components/spinner"

const PAGE_SIZE = 20

const EVENT_LABEL: Record<string, string> = {
  fee_collected: "Fees collected",
  distribution: "Distributed",
}

export function TreasuryHistory() {
  const [page, setPage] = useState(1)

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.treasuryLogs(page),
    queryFn: () => adminApi.treasuryLogs({ page, pageSize: PAGE_SIZE }),
    retry: false,
  })

  const rows = data?.data ?? []
  const total = data?.total ?? 0
  const hasMore = data?.has_more ?? false

  return (
    <Card className="overflow-hidden pt-0">
      <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-4">
        <div>
          <h2 className="text-base font-semibold">Movement history</h2>
          <p className="text-xs text-muted-foreground">
            Every fee collected and every withdrawal, newest first.
          </p>
        </div>
        {total > 0 ? (
          <Badge variant="secondary">{total.toLocaleString()} entries</Badge>
        ) : null}
      </div>

      {isLoading ? (
        <CardContent role="status" className="flex h-32 items-center justify-center">
          <Spinner className="size-5" />
          <span className="sr-only">Loading treasury history</span>
        </CardContent>
      ) : rows.length === 0 ? (
        <CardContent className="py-12 text-center">
          <Receipt className="mx-auto mb-2 size-7 text-muted-foreground" aria-hidden />
          <p className="text-sm font-medium text-foreground">No movements recorded</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Fees appear here as trades happen, and distributions when they are swept.
          </p>
        </CardContent>
      ) : (
        <ul className="divide-y border-t">
          {rows.map((entry) => {
            const incoming = entry.event === "fee_collected";
            return (
              <li key={entry.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                <span
                  className={
                    incoming
                      ? "grid size-7 shrink-0 place-items-center rounded-full bg-emerald-500/10 text-emerald-600"
                      : "grid size-7 shrink-0 place-items-center rounded-full bg-amber-500/10 text-amber-600"
                  }
                  aria-hidden
                >
                  {incoming ? <ArrowDownLeft className="size-3.5" /> : <ArrowUpRight className="size-3.5" />}
                </span>

                <div className="min-w-0 flex-1">
                  {/* Direction in words as well as in the icon: the icon alone is
                      not an accessible signal. */}
                  <p className="text-sm font-medium">
                    {EVENT_LABEL[entry.event] ?? entry.event}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {new Date(entry.created_at).toLocaleString()}
                    {entry.reference_type ? (
                      <>
                        {" · "}
                        {entry.reference_type}
                        {entry.reference_id ? ` ${entry.reference_id}` : ""}
                      </>
                    ) : null}
                  </p>
                </div>

                {/* Signed. A column of positive numbers, half of which is money
                    leaving, is a column that lies about direction. */}
                <p
                  className={
                    incoming
                      ? "shrink-0 text-sm font-medium tabular-nums text-emerald-600"
                      : "shrink-0 text-sm font-medium tabular-nums text-amber-600"
                  }
                >
                  {incoming ? "+" : "−"}
                  {Number(entry.amount).toLocaleString(undefined, {
                    maximumFractionDigits: 8,
                  })}
                </p>
              </li>
            );
          })}
        </ul>
      )}

      <div className="border-t px-5 py-3">
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          total={total}
          hasMore={hasMore}
          itemLabel="movements"
          isLoading={isLoading}
          onPageChange={setPage}
        />
      </div>
    </Card>
  );
}