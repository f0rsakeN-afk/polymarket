"use client"

import { useState } from "react"
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { ArrowLeft, TriangleAlert } from "lucide-react"

import { adminApi, type AdminUserDetail } from "@/lib/api/admin"
import { apiErrorMessage } from "@/lib/api/client"
import { queryKeys } from "@/lib/api/queryKeys"
import { Badge } from "@workspace/ui/components/badge"
import { Button, buttonVariants } from "@workspace/ui/components/button"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Spinner } from "@workspace/ui/components/spinner"
import { cn } from "@workspace/ui/lib/utils"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"

/**
 * Everything known about one account, for answering a question about it.
 *
 * The reason this page exists: an admin told "this user says they lost money"
 * previously had no way to check. The ledger to answer it was always there -
 * every transaction carries `balance_after` and a `reference_id` pointing at the
 * order that caused it - but there was no page that showed it.
 *
 * Detail rows load on demand rather than up front. A user with years of trades
 * would make an unconditional dump unusable, and the server caps it anyway.
 */

/** Findings are server-computed; the wording is the operator's, not the API's. */
const FINDING_TEXT: Record<string, { label: string; hint: string }> = {
  has_open_orders: {
    label: "Has open orders",
    hint: "Funds are reserved against orders that may not fill. A ban cancels these and releases the funds.",
  },
  has_locked_funds: {
    label: "Has locked funds",
    hint: "Locked balance is above zero and no live order accounts for it — check for a settlement that did not complete.",
  },
  no_wallet: {
    label: "No wallet",
    hint: "The account cannot hold a balance. Anything attributed to it is not.",
  },
  account_erased: {
    label: "Account erased",
    hint: "Identity has been anonymised; trades and transactions are retained and unattached to a person.",
  },
}

function Finding({ name }: { name: string }) {
  const known = FINDING_TEXT[name]
  return (
    <Badge
      variant="outline"
      className="gap-1 border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-300"
      title={known?.hint ?? name}
    >
      <TriangleAlert className="size-3" />
      {known?.label ?? name}
    </Badge>
  )
}

function DetailTable({
  rows,
  columns,
}: {
  rows: Record<string, unknown>[] | undefined
  columns: string[]
}) {
  if (!rows?.length) {
    return <p className="py-4 text-sm text-muted-foreground">Nothing to show.</p>
  }
  return (
    <div className="max-h-96 overflow-auto">
      <Table noWrapper className="w-full">
        <TableHeader className="sticky top-0 z-10 bg-muted">
          <TableRow>
            {columns.map((c) => (
              <TableHead key={c}>{c}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, i) => (
            <TableRow key={String(row.id ?? i)}>
              {columns.map((c) => (
                <TableCell key={c} className="text-xs">
                  {row[c] === null || row[c] === undefined
                    ? "—"
                    : String(row[c])}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

export function AdminUserDetailClient({ userId }: { userId: string }) {
  const [include, setInclude] = useState<string[]>([])

  const { data: user, isLoading, error } = useQuery({
    queryKey: queryKeys.adminUser(userId),
    queryFn: () => adminApi.user(userId).then((r) => r.data as AdminUserDetail),
    // A 404 here is an answer, not a transient failure, and the auth gate already
    // declines to retry: this is the same reasoning as the session probe.
    retry: false,
  })

  const { data: detail } = useQuery({
    queryKey: queryKeys.adminUser(userId, include),
    queryFn: () =>
      adminApi.user(userId, include).then((r) => r.data as AdminUserDetail),
    enabled: include.length > 0,
    retry: false,
  })

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center" role="status">
        <Spinner className="size-5" />
        <span className="sr-only">Loading account…</span>
      </div>
    )
  }

  if (error || !user) {
    return (
      <Card>
        <CardContent className="space-y-3 py-8 text-sm">
          <p className="font-medium text-destructive">Could not load this account</p>
          <p className="text-muted-foreground">
            {apiErrorMessage(error, "Unknown error")}
          </p>
          <Link
            href="/admin/users"
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            <ArrowLeft className="size-3.5" />
            Back to users
          </Link>
        </CardContent>
      </Card>
    )
  }

  const toggle = (key: string) =>
    setInclude((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <Link
            href="/admin/users"
            className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "-ml-2")}
          >
            <ArrowLeft className="size-3.5" />
            Users
          </Link>
          <h1 className="truncate text-xl font-bold tracking-tight">{user.email}</h1>
          <p className="text-sm text-muted-foreground">@{user.username}</p>
        </div>
        <div className="flex flex-wrap gap-1">
          {user.is_admin && <Badge>admin</Badge>}
          <Badge variant={user.is_active ? "secondary" : "destructive"} className="capitalize">
            {user.is_active ? "active" : "banned"}
          </Badge>
          {user.is_deleted && <Finding name="account_erased" />}
        </div>
      </div>

      {user.findings.length > 0 && (
        <Card className="border-amber-500/40">
          <CardContent className="space-y-2 py-4">
            <p className="text-sm font-medium">Worth a look</p>
            <div className="flex flex-wrap gap-2">
              {user.findings.map((f) => (
                <Finding key={f} name={f} />
              ))}
            </div>
            <ul className="space-y-1 pt-1">
              {user.findings.map((f) => (
                <li key={f} className="text-xs text-muted-foreground">
                  {FINDING_TEXT[f]?.hint ?? f}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardContent className="space-y-2 py-4">
            <p className="text-sm font-medium">Wallet</p>
            {user.wallet ? (
              <dl className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Balance</dt>
                  {/* A string, never parsed to a number: this screen exists to be
                      reconciled against a ledger. */}
                  <dd className="font-medium tabular-nums">
                    {user.wallet.balance} {user.wallet.currency}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Locked</dt>
                  <dd className="font-medium tabular-nums">{user.wallet.locked_balance}</dd>
                </div>
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">No wallet.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-2 py-4">
            <p className="text-sm font-medium">Activity</p>
            <dl className="grid grid-cols-2 gap-1 text-sm">
              {Object.entries(user.counts).map(([key, value]) => (
                <div key={key} className="flex justify-between gap-2">
                  <dt className="capitalize text-muted-foreground">
                    {key.replace("_", " ")}
                  </dt>
                  <dd className="font-medium tabular-nums">{value}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="space-y-3 py-4">
          <p className="text-sm font-medium">Ledger</p>
          <div className="flex flex-wrap gap-2">
            {(
              [
                ["transactions", "Transactions"],
                ["trades", "Trades"],
                ["orders", "Orders"],
                ["positions", "Positions"],
              ] as const
            ).map(([key, label]) => (
              <Button
                key={key}
                variant={include.includes(key) ? "default" : "outline"}
                size="sm"
                onClick={() => toggle(key)}
                aria-pressed={include.includes(key)}
              >
                {label}
              </Button>
            ))}
          </div>
          {include.length > 0 && (
            <div className="space-y-4 pt-2">
              {include.includes("transactions") && (
                <DetailTable
                  rows={detail?.transactions}
                  columns={["id", "type", "amount", "balance_after", "reference_id", "created_at"]}
                />
              )}
              {include.includes("trades") && (
                <DetailTable
                  rows={detail?.trades}
                  columns={["id", "outcome", "side", "price", "amount", "executed_at"]}
                />
              )}
              {include.includes("orders") && (
                <DetailTable
                  rows={detail?.orders}
                  columns={["id", "outcome_id", "side", "amount", "price", "status", "created_at"]}
                />
              )}
              {include.includes("positions") && (
                <DetailTable
                  rows={detail?.positions}
                  columns={["id", "market_id", "outcome_id", "shares_held", "created_at"]}
                />
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}