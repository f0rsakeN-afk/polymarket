"use client"

import { useCallback, useState } from "react"
import Link from "next/link"
import { Ban, RotateCcw, Search } from "lucide-react"

import { useQuery } from "@tanstack/react-query"

import { adminApi, type AdminUserRow } from "@workspace/api-client/admin"
import { queryKeys } from "@/lib/queryKeys"
import { PageHeader } from "@/components/page-header"
import { Pagination } from "@/components/pagination"
import { BanUserDialog, UnbanUserDialog } from "@/components/ban-dialog"
import { userSearchSchema } from "@/schemas/privileged"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"

/** Mirrors the backend's `status` pattern on `GET /admin/users`. */
const USER_STATUSES = [
  { value: "all", label: "All accounts" },
  { value: "active", label: "Active" },
  { value: "banned", label: "Banned" },
  { value: "admins", label: "Admins" },
  { value: "unverified", label: "Unverified email" },
] as const

type UserStatus = (typeof USER_STATUSES)[number]["value"]

/** Mirrors the backend's `sort` pattern on `GET /admin/users`. */
const USER_SORTS = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "email", label: "Email A-Z" },
] as const

type UserSort = (typeof USER_SORTS)[number]["value"]

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
  const [search, setSearch] = useState("")
  const [applied, setApplied] = useState("")
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<UserStatus>("all")
  const [sort, setSort] = useState<UserSort>("newest")

  const { data, isLoading, isFetching } = useQuery({
    // The envelope, not `r.data`. `total` and `has_more` live on the envelope,
    // so unwrapping to the row array first and reading them off it yields
    // `undefined` forever - which is why this header said "Loading…" permanently
    // and the page counter had nothing to count.
    queryKey: queryKeys.adminUsers(page, applied, status, sort),
    queryFn: () =>
      adminApi.users({
        page,
        pageSize: 20,
        search: applied || undefined,
        status,
        sort,
      }),
    // `is_active` is on the row and `is_deleted` is not exposed here, so an
    // erased account still appears. Worth knowing before an operator bans one by
    // mistake - the detail view is where they find out.
    retry: false,
  })

  // The ban/unban logic now lives in the dialogs, because both need input first:
  // a ban cannot be sent without a reason the user will read, and a reversal is a
  // decision worth recording even when its note is optional. What stays here is
  // *which* user is being acted on.
  const [banning, setBanning] = useState<AdminUserRow | null>(null)
  const [unbanning, setUnbanning] = useState<AdminUserRow | null>(null)

  const rows = data?.data ?? []
  const total = data?.total
  const hasMore = data?.has_more ?? false

  /**
   * The search box is bounded for the same reason the query parameter is: it is
   * pasted straight into a URL, and an unbounded "search" is both a useless
   * result and a string nobody wants in a log.
   *
   * An empty value is allowed and means "everyone" — clearing the box should not
   * raise a validation error, it should return the list.
   */
  const searchProblem = applied ? userSearchSchema.safeParse(applied) : null
  const searchError =
    searchProblem && !searchProblem.success
      ? (searchProblem.error.issues[0]?.message ?? "That search is not valid")
      : null

  const onSearch = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      // Not applied when it cannot succeed. Pushing it into the query anyway
      // leaves the operator looking at an unchanged list with an error beside
      // the box, having no way to tell the search was refused from it being slow.
      if (search.trim() && !userSearchSchema.safeParse(search).success) return
      setApplied(search.trim())
      setPage(1)
    },
    [search]
  )

  /**
   * Both filters reset to page 1, and the reason is not tidiness.
   *
   * Changing a filter while sitting on page 7 shows page 7 *of the new result*.
   * A banned-only filter over 40 accounts leaves page 7 empty, and an empty list
   * with no rows and no explanation reads as "nobody is banned" - the exact
   * wrong conclusion during an incident.
   */
  const onStatus = useCallback((value: UserStatus | null) => {
    // Null is the clearable case, not a real filter. Ignoring it leaves the
    // previous filter in place while the trigger reads as unfiltered.
    if (!value) return
    setStatus(value)
    setPage(1)
  }, [])

  const onSort = useCallback((value: UserSort | null) => {
    if (!value) return
    setSort(value)
    setPage(1)
  }, [])

  const filtered = status !== "all" || applied !== ""

  return (
    <div className="space-y-4">
      <PageHeader
        title="Users"
        description={
          total !== undefined ? `${total.toLocaleString()} account${total === 1 ? "" : "s"}` : "Loading…"
        }
        actions={
          /* A wrapper, because the search box and its error are two nodes and
             `actions` takes one. `items-end` keeps the error aligned under the
             input rather than stretching the box it belongs to. */
          <div className="flex w-full flex-col items-end gap-1.5 sm:w-auto sm:items-stretch">
            {/* `role="search"` rather than a bare form: a screen reader user
                landing here is looking for a way to find a specific account, and
                "search" is what tells them one exists. */}
            <form role="search" onSubmit={onSearch} className="flex w-full gap-2 sm:w-auto">
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search email or username"
                aria-label="Search users"
                aria-invalid={searchError ? true : undefined}
                aria-describedby={searchError ? "user-search-error" : undefined}
                className="min-w-0 flex-1 sm:w-64 sm:flex-none"
              />
              <Button type="submit" variant="outline" size="sm">
                <Search className="size-3.5" />
                Search
              </Button>
            </form>
            {/* Next to the box rather than in a toast: the failure is about one
                input, and an error that appears somewhere else is an error about
                something else. */}
            {searchError ? (
              <p id="user-search-error" role="alert" className="text-xs text-destructive">
                {searchError}
              </p>
            ) : null}
          </div>
        }
      />

      {/* Above the table rather than inside `actions`, so the filters stay put
          when the header's description changes from "Loading…" to a count. A
          control that moves as data arrives is a control you cannot click twice. */}
      <div className="flex flex-wrap items-center gap-2">
        <Select value={status} onValueChange={onStatus}>
          <SelectTrigger aria-label="Filter accounts by state" className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {USER_STATUSES.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={sort} onValueChange={onSort}>
          <SelectTrigger aria-label="Sort accounts" className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {USER_SORTS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Says what is being narrowed, and offers the way back. An operator who
            arrived with a filter applied by a shared link needs to know it was not
            their own search returning nothing. */}
        {filtered ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setStatus("all")
              setApplied("")
              setSearch("")
              setPage(1)
            }}
          >
            Clear filters
          </Button>
        ) : null}
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
            <p className="font-medium text-foreground">
              {filtered ? "No accounts match" : "No users found"}
            </p>
            <p className="text-xs">
              {applied
                ? `Nothing matches “${applied}”${
                    status !== "all"
                      ? ` in ${USER_STATUSES.find((s) => s.value === status)?.label.toLowerCase()}`
                      : ""
                  }.`
                : status !== "all"
                  ? `No accounts are ${
                      USER_STATUSES.find((s) => s.value === status)?.label.toLowerCase()
                    }.`
                  : "There are no accounts yet."}
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
                    isPending={false}
                    onBan={(u) => setBanning(u)}
                    onUnban={(u) => setUnbanning(u)}
                  />
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>

      <BanUserDialog
        key={banning?.id ?? "no-ban-target"}
        user={banning}
        onOpenChange={(open) => !open && setBanning(null)}
      />
      <UnbanUserDialog
        key={unbanning?.id ?? "no-unban-target"}
        user={
          unbanning
            ? { id: unbanning.id, email: unbanning.email, banReason: unbanning.ban_reason }
            : null
        }
        onOpenChange={(open) => !open && setUnbanning(null)}
      />

      {/* The shared control, like every other list in this app. The hand-rolled
          pair this replaces gave no "1-20 of 1,284" line, so an operator could
          not tell how much they had not looked at - which is exactly the number
          that decides whether a filtered result is trustworthy. */}
      <Pagination
        page={page}
        pageSize={20}
        total={total}
        hasMore={hasMore}
        itemLabel="accounts"
        isLoading={isLoading}
        onPageChange={setPage}
      />
    </div>
  )
}