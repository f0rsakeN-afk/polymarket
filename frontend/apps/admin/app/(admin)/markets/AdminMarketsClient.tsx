"use client"

import { useCallback, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { sileo } from "sileo"
import { Check, Search, X } from "lucide-react"

import { adminApi, type AdminMarketRow } from "@workspace/api-client/admin"
import { apiErrorMessage } from "@workspace/api-client/client"
import { queryKeys } from "@/lib/queryKeys"
import { PageHeader } from "@/components/page-header"
import { BulkApproveBar } from "@/components/bulk-approve-bar"
import { Pagination } from "@/components/pagination"
import { RejectMarketDialog } from "@/components/reject-market-dialog"
import { Button } from "@workspace/ui/components/button"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Badge } from "@workspace/ui/components/badge"
import { Checkbox } from "@workspace/ui/components/checkbox"
import { Input } from "@workspace/ui/components/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { Spinner } from "@workspace/ui/components/spinner"

/**
 * The moderation queue.
 *
 * Only `pending_review` by default, because that is the actionable set — a
 * moderator opening this page wants the markets waiting on them, not the whole
 * catalogue. The other statuses are one click away for the "why did that one get
 * rejected?" question, which is why they are a filter rather than absent.
 */
/**
 * Every state a market can be in, plus "everything".
 *
 * `""` is All, and it is the default. This screen used to default to
 * `pending_review` with no way to see anything else at once — so "is anything
 * broken" could not be answered here, and three of the seven states (`closed`,
 * `resolving`, `dispute_window`) were not listed at all. A market sitting in
 * `resolving` with a stuck resolver was invisible to the very screen meant to
 * catch it.
 */
const FILTERS = [
  { value: "", label: "All" },
  { value: "pending_review", label: "Awaiting review" },
  { value: "rejected", label: "Rejected" },
  { value: "active", label: "Active" },
  { value: "closed", label: "Trading closed" },
  { value: "resolving", label: "Resolving" },
  { value: "dispute_window", label: "In dispute window" },
  { value: "resolved", label: "Resolved" },
]

const SORTS = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "closing_soon", label: "Closing soonest" },
  { value: "volume", label: "Most traded" },
  { value: "liquidity", label: "Most liquid" },
] as const

type SortValue = (typeof SORTS)[number]["value"]

export function AdminMarketsClient() {
  const qc = useQueryClient()
  const searchParams = useSearchParams()

  /**
   * `?market=<id>` is the other half of the dispute queue's market link.
   *
   * Every dispute row links its market question to here, and until this read the
   * parameter the link was decorative: it navigated to an unfiltered first page
   * and quietly severed the connection between the dispute being read and the
   * market it is about - which is the one thing an operator following that link
   * needs to keep.
   *
   * Seeded into the same state as a typed search rather than fetched
   * separately, so the box shows where the list came from and clearing it clears
   * the filter too.
   */
  const marketParam = searchParams.get("market") ?? ""

  const [status, setStatus] = useState("")
  const [search, setSearch] = useState(marketParam)
  const [appliedSearch, setAppliedSearch] = useState(marketParam)
  const [sort, setSort] = useState<SortValue>("newest")
  const [page, setPage] = useState(1)
  // Changing a filter while on a later page lands you on an empty page of the
  // new filter, which reads as "there is nothing here" rather than "start again".
  const resetToFirstPage = () => setPage(1)

  const { data: result, isLoading } = useQuery({
    // Every input in the key, not just page and status. Two searches that differ
    // only in text share a cache entry otherwise, and the second operator to ask
    // is shown the first one's results.
    queryKey: [...queryKeys.adminMarkets(status || "all", page), appliedSearch, sort],
    queryFn: () =>
      adminApi.markets({
        status: status || undefined,
        q: appliedSearch || undefined,
        sort,
        page,
        pageSize: 50,
      }),
    // A refetch on every keystroke would hit the admin list endpoint for each
    // character; the search is submitted, not typed.
    retry: false,
  })

  const rows = result?.data ?? []
  // Envelope, not just the rows: `total` and `has_more` are what tell an operator
  // the queue continues past what they can see.
  const total = result?.total ?? 0
  const hasMore = result?.has_more ?? false
  const filtering = Boolean(status || appliedSearch)

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

  /**
   * Bulk approval.
   *
   * Sequential on purpose. Fifty parallel mutations would hit the rate limiter,
   * and the ones refused for that reason would come back indistinguishable from
   * real refusals - so the operator would be told some markets failed for
   * reasons the product invented. One at a time keeps the failure report true.
   */
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [bulkRunning, setBulkRunning] = useState(false)

  const pending = status === "pending_review"

  /**
   * Selection cannot outlive the thing it selected.
   *
   * A market approved on the previous page is still in the set when the
   * operator returns, and "Approve 3" would then mean approving three markets
   * that are no longer waiting. Dropping ids the current page no longer shows is
   * the cheapest correct rule, and it also stops a stale id being sent to the
   * API for a market that has already moved on.
   */
  const visibleIds = useMemo(() => new Set(rows.map((row) => row.id)), [rows])
  const liveSelection = useMemo(() => {
    const kept = new Set([...selected].filter((id) => visibleIds.has(id)))
    return kept.size === selected.size ? selected : kept
  }, [selected, visibleIds])

  const toggle = (id: string, checked: boolean) => {
    setSelected((previous) => {
      const next = new Set(previous)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })
  }

  const toggleAll = (checked: boolean) => {
    setSelected(checked ? new Set(rows.map((row) => row.id)) : new Set())
  }

  const clearSelection = () => setSelected(new Set())

  const bulkApprove = useCallback(async () => {
    const targets = rows.filter((row) => liveSelection.has(row.id))
    if (targets.length === 0) return

    setBulkRunning(true)
    const failed: string[] = []
    let approved = 0

    for (const market of targets) {
      try {
        await adminApi.approveMarket(market.id)
        approved += 1
      } catch {
        // The market's own question, not the id: an operator chasing a failure
        // needs to know which submission did not publish, and "3 of them" does
        // not survive being pasted into a ticket.
        failed.push(market.question)
      }
    }

    setBulkRunning(false)
    clearSelection()
    refresh()

    // One toast per outcome shape, and never a success message that covers a
    // partial failure. Nineteen of twenty is not "approved".
    if (failed.length === 0) {
      sileo.success({
        title: `${approved} market${approved === 1 ? "" : "s"} approved`,
        description: "They are tradable now.",
      })
      return
    }
    if (approved === 0) {
      sileo.error({
        title: "Nothing was approved",
        description: `${failed.length} failed. ${failed.slice(0, 2).join(" · ")}`,
      })
      return
    }
    sileo.error({
      title: `${approved} approved, ${failed.length} failed`,
      description: `Not published: ${failed.slice(0, 2).join(" · ")}`,
    })
  }, [rows, liveSelection, refresh])

  return (
    <div className="space-y-4">
      <PageHeader
        title="Markets"
        description={
          pending
            ? "Markets waiting on a decision before they become tradable."
            : filtering
              ? `${total.toLocaleString()} matching • every state, including the ones the public catalogue hides.`
              : "Every market, in every state — including the ones the public catalogue hides."
        }
        actions={
          <div className="flex gap-1" role="group" aria-label="Filter by status">
            {FILTERS.map((f) => (
              <Button
                key={f.value || "all"}
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

      {/* Search and sort live below the status chips rather than inside the
          header: the chips answer "which state", these two answer "which one",
          and separating them keeps each control to a single question. */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <form
          role="search"
          onSubmit={(event) => {
            event.preventDefault()
            resetToFirstPage()
            setAppliedSearch(search.trim())
          }}
          className="flex w-full gap-2 sm:max-w-md"
        >
          <label htmlFor="market-search" className="sr-only">
            Search markets by question, slug or submitter
          </label>
          <Input
            id="market-search"
            /* type=search rather than the default text: it gives the field the
               searchbox role, which is what tells a screen reader this box
               searches rather than being an unlabelled text field, and it
               brings the browser's own clear affordance. */
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search question, slug or submitter…"
          />
          <Button type="submit" variant="outline" size="sm">
            <Search className="size-3.5" aria-hidden />
            Search
          </Button>
          {appliedSearch ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setSearch("")
                setAppliedSearch("")
                resetToFirstPage()
              }}
            >
              Clear
            </Button>
          ) : null}
        </form>

        <div className="flex items-center gap-2">
          <label htmlFor="market-sort" className="text-xs text-muted-foreground">
            Sort
          </label>
          <Select
            value={sort}
            onValueChange={(value) => {
              resetToFirstPage()
              setSort(value as SortValue)
            }}
          >
            <SelectTrigger id="market-sort" className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORTS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Only on the pending filter, because only pending markets can be
          approved. A selection control on a list of already-approved markets is
          a control that cannot do the thing it offers. */}
      {pending ? (
        <BulkApproveBar
          selected={rows.filter((row) => liveSelection.has(row.id))}
          totalOnPage={rows.length}
          isRunning={bulkRunning}
          onToggleAll={toggleAll}
          onClear={clearSelection}
          onConfirm={bulkApprove}
        />
      ) : null}

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
              {appliedSearch
                ? `Nothing matches “${appliedSearch}”.`
                : pending
                  ? "No markets are waiting for review."
                  : status
                    ? `No markets with status “${status}”.`
                    : "There are no markets at all."}
            </p>
          </CardContent>
        ) : (
          <ul className="divide-y">
            {rows.map((market) => (
              <li
                key={market.id}
                className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
              >
                {/* The checkbox leads the row rather than sitting inside the
                    text block, so it lines up down the column and the hit target
                    is not the question text. */}
                {pending ? (
                  <Checkbox
                    checked={liveSelection.has(market.id)}
                    onCheckedChange={(checked: boolean) =>
                      toggle(market.id, checked)
                    }
                    aria-label={`Select ${market.question}`}
                  />
                ) : null}
                <div className="min-w-0">
                  <p className="text-sm font-medium">{market.question}</p>
                  <p className="text-xs text-muted-foreground">
                    /{market.slug}
                    {market.created_by_email ? (
                      <>
                        {" · "}
                        {market.created_by_email}
                      </>
                    ) : (
                      /* A system-created market has no submitter. Saying
                         "system" is honest; leaving the field blank reads as a
                         bug in the query. */
                      <> · system</>
                    )}
                  </p>
                  {/* The facts an operator triages on, on the row itself.
                      Opening each market to learn whether it has volume is the
                      difference between triaging a queue and reading it. */}
                  <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                    <span>
                      <span className="tabular-nums">{market.num_trades.toLocaleString()}</span>{" "}
                      trades
                    </span>
                    <span>
                      <span className="tabular-nums">
                        {Number(market.total_volume).toLocaleString(undefined, {
                          maximumFractionDigits: 0,
                        })}
                      </span>{" "}
                      volume
                    </span>
                    <span>
                      <span className="tabular-nums">
                        {Number(market.total_liquidity).toLocaleString(undefined, {
                          maximumFractionDigits: 0,
                        })}
                      </span>{" "}
                      liquidity
                    </span>
                    {/* Two legs is binary, more is parimutuel. It changes how
                        every price on the row reads, so it is stated rather than
                        left for the operator to infer from the market page. */}
                    <span>
                      {market.outcome_count} {market.outcome_count === 1 ? "outcome" : "outcomes"}
                      {market.outcome_count > 2 ? " · parimutuel" : ""}
                    </span>
                    <span>closes {new Date(market.closes_at).toLocaleDateString()}</span>
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