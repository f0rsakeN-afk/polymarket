"use client"

import { useCallback, useState } from "react"
import Link from "next/link"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { sileo } from "sileo"
import { Ban, RotateCcw, Search } from "lucide-react"

import { adminApi, type AdminUserRow } from "@workspace/api-client/admin"
import { apiErrorMessage } from "@workspace/api-client/client"
import { queryKeys } from "@/lib/queryKeys"
import { Button } from "@workspace/ui/components/button"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Input } from "@workspace/ui/components/input"
import { Badge } from "@workspace/ui/components/badge"
import { Spinner } from "@workspace/ui/components/spinner"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"

/**
 * User administration.
 *
 * ## Why ban reports what it cancelled
 *
 * Banning now cancels the user's resting orders and releases the reserved USDC -
 * a banned user cannot trade, so an order left in the book is money locked
 * against a market they are locked out of, and they are unreachable to release
 * it. So the count and the order ids come back in the response and are shown,
 * rather than being an invisible side effect. "You cancelled 3 orders" is what
 * makes the action reviewable instead of surprising.
 */
function UserRow({
  user,
  onBan,
  onUnban,
  isPending,
}: {
  user: AdminUserRow
  onBan: (u: AdminUserRow) => void
  onUnban: (u: AdminUserRow) => void
  isPending: boolean
}) {
  return (
    <TableRow className="hover:bg-accent/30">
      <TableCell>
        <Link
          href={`/users/${user.id}`}
          className="text-sm font-medium hover:underline"
        >
          {user.email}
        </Link>
        <p className="text-xs text-muted-foreground">@{user.username}</p>
      </TableCell>
      <TableCell className="text-sm">
        <div className="flex flex-wrap gap-1">
          {user.is_admin && (
            <Badge className="bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-300">
              admin
            </Badge>
          )}
          <Badge
            variant={user.is_active ? "secondary" : "destructive"}
            className="capitalize"
          >
            {user.is_active ? "active" : "banned"}
          </Badge>
          {!user.is_email_verified && <Badge variant="outline">unverified</Badge>}
          {user.is_2fa_enabled && <Badge variant="outline">2fa</Badge>}
        </div>
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">
        {new Date(user.created_at).toLocaleDateString()}
      </TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-1">
          {user.is_admin ? (
            // Ban already refuses admins server-side; disabling here keeps the UI
            // honest about what is possible instead of offering a button that 403s.
            <span className="text-xs text-muted-foreground">—</span>
          ) : user.is_active ? (
            <Button
              variant="outline"
              size="sm"
              disabled={isPending}
              onClick={() => onBan(user)}
              className="text-destructive hover:bg-destructive/10"
            >
              <Ban className="size-3.5" />
              Ban
            </Button>
          ) : (
            <Button
              variant="outline"
              size="sm"
              disabled={isPending}
              onClick={() => onUnban(user)}
            >
              <RotateCcw className="size-3.5" />
              Unban
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  )
}

export function AdminUsersClient() {
  const qc = useQueryClient()
  const [search, setSearch] = useState("")
  const [applied, setApplied] = useState("")
  const [page, setPage] = useState(1)

  const { data, isLoading, isFetching } = useQuery({
    queryKey: queryKeys.adminUsers(page, applied),
    queryFn: () =>
      adminApi
        .users({ page, pageSize: 20, search: applied || undefined })
        .then((r) => r.data),
    // `is_active` is on the row and `is_deleted` is not exposed here, so an
    // erased account still appears. Worth knowing before an operator bans one by
    // mistake - the detail view is where they find out.
    retry: false,
  })

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: queryKeys.adminRoot() })
    qc.invalidateQueries({ queryKey: ["admin", "user"] })
  }, [qc])

  const banMutation = useMutation({
    mutationFn: (userId: string) => adminApi.ban(userId),
    onSuccess: (res) => {
      invalidate()
      const cancelled = res.data?.cancelled_order_ids ?? []
      sileo.success({
        title: "User banned",
        // Named, not summarised. The released funds are the part an operator
        // needs to be able to reconcile afterwards.
        description:
          cancelled.length > 0
            ? `${cancelled.length} open order(s) cancelled and funds released: ${cancelled.join(", ")}`
            : "No open orders to cancel.",
      })
    },
    onError: (err) => sileo.error({ title: apiErrorMessage(err, "Could not ban user") }),
  })

  const unbanMutation = useMutation({
    mutationFn: (userId: string) => adminApi.unban(userId),
    onSuccess: () => {
      invalidate()
      sileo.success({ title: "User unbanned" })
    },
    onError: (err) => sileo.error({ title: apiErrorMessage(err, "Could not unban user") }),
  })

  const rows = data ?? []
  const total = data ? (data as unknown as { total?: number }).total : undefined
  const hasMore = data ? (data as unknown as { has_more?: boolean }).has_more : false

  const onSearch = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      setApplied(search.trim())
      setPage(1)
    },
    [search]
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Users</h1>
          <p className="text-sm text-muted-foreground">
            {total !== undefined ? `${total} account${total === 1 ? "" : "s"}` : "Loading…"}
          </p>
        </div>
        <form onSubmit={onSearch} className="flex gap-2">
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search email or username"
            aria-label="Search users"
            className="w-64"
          />
          <Button type="submit" variant="outline" size="sm">
            <Search className="size-3.5" />
            Search
          </Button>
        </form>
      </div>

      <Card className="overflow-hidden pt-0">
        {isLoading ? (
          <CardContent
            role="status"
            className="flex h-48 items-center justify-center"
          >
            <Spinner className="size-5" />
            <span className="sr-only">Loading users…</span>
          </CardContent>
        ) : rows.length === 0 ? (
          <CardContent
            role="status"
            className="flex h-48 flex-col items-center justify-center gap-2 text-sm text-muted-foreground"
          >
            <p className="font-medium text-foreground">No users found</p>
            <p className="text-xs">
              {applied ? `Nothing matches “${applied}”.` : "There are no accounts yet."}
            </p>
          </CardContent>
        ) : (
          <div className="relative overflow-auto" style={{ maxHeight: "65vh" }}>
            {/* Announced, not visible: a page flip replaces the whole table, and a
                screen-reader user otherwise has no idea anything happened. */}
            <p aria-live="polite" className="sr-only">
              {isFetching ? "Refreshing" : `Showing ${rows.length} users`}
            </p>
            <Table noWrapper className="w-full min-w-[720px]">
              <TableHeader className="sticky top-0 z-20 bg-muted">
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Joined</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((user) => (
                  <UserRow
                    key={user.id}
                    user={user}
                    isPending={banMutation.isPending || unbanMutation.isPending}
                    onBan={(u) => banMutation.mutate(u.id)}
                    onUnban={(u) => unbanMutation.mutate(u.id)}
                  />
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>

      <div className="flex items-center justify-between">
        <Button
          variant="outline"
          size="sm"
          disabled={page <= 1}
          onClick={() => setPage((p) => Math.max(1, p - 1))}
        >
          Previous
        </Button>
        <span className="text-sm text-muted-foreground">Page {page}</span>
        <Button
          variant="outline"
          size="sm"
          disabled={!hasMore}
          onClick={() => setPage((p) => p + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  )
}