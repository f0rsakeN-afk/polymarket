"use client"

/**
 * The landing page.
 *
 * Previously a blind redirect to `/users`. That is the wrong shape for a page
 * someone bookmarks: an operator who opens the admin app mid-shift wants to know
 * what is waiting, not to be told which list to open.
 *
 * So this answers the three questions that are actually asked of an admin tool:
 * **what needs me**, **what did I just do**, and **what did somebody else do
 * that failed**. Failures are on the front page deliberately - a ruling that was
 * refused and a step-up that was guessed at are the events worth noticing, and
 * burying them one click deep on a separate trail is how they go unread.
 */

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { Landmark, Scale, ScrollText, ShieldAlert, Store, TriangleAlert, Users } from "lucide-react"

import { adminApi } from "@workspace/api-client/admin"
import { queryKeys } from "@/lib/queryKeys"
import { group } from "@/lib/decimal"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Badge } from "@workspace/ui/components/badge"
import { buttonVariants } from "@workspace/ui/components/button"
import { Spinner } from "@workspace/ui/components/spinner"
import { cn } from "@workspace/ui/lib/utils"

/**
 * `500000.00000000` -> `500,000`.
 *
 * Display only, for a glanceable figure on a card. The exact string is what the
 * treasury page shows, because that is the page where an operator may be about
 * to move money and needs every decimal place.
 *
 * The fraction is split off before the zeros are trimmed, so a whole number like
 * `"100"` keeps its trailing zeros instead of becoming `"1"`.
 */
function glance(value: string | undefined): string | undefined {
  if (value === undefined) return undefined
  const [whole, fraction] = value.split(".")
  if (fraction === undefined) return group(whole ?? value)
  const trimmed = fraction.replace(/0+$/, "")
  return group(trimmed ? `${whole}.${trimmed}` : (whole ?? "0"))
}

/**
 * One figure, clickable through to whatever it describes.
 *
 * Three states, because they mean different things and were being conflated:
 * loading, failed, and loaded. `value === null` is a failure and says so, where
 * the previous version spun indefinitely - on the one screen an operator opens
 * when something is already broken.
 *
 * `value` is a number for counts and a string for money, because a treasury
 * balance is a decimal string end to end and rendering it as a float is exactly
 * the rounding this app refuses to do everywhere else.
 */
function Stat({
  href,
  icon: Icon,
  label,
  value,
  tone,
  hint,
}: {
  href: string
  icon: typeof Users
  label: string
  value: number | string | null | undefined
  tone?: "default" | "warning"
  hint: string
}) {
  const warning = tone === "warning" && typeof value === "number" && value > 0

  return (
    <Link href={href} className="group">
      <Card className="h-full transition-colors group-hover:bg-accent/40">
        <CardContent className="px-5 py-4">
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">{label}</p>
            <Icon
              className={cn(
                "size-4",
                warning ? "text-amber-600" : "text-muted-foreground"
              )}
              aria-hidden
            />
          </div>
          {value === undefined ? (
            <div className="mt-2 flex h-8 items-center" role="status">
              <Spinner className="size-4" />
              <span className="sr-only">Loading {label}</span>
            </div>
          ) : value === null ? (
            <>
              <p className="mt-1 text-2xl font-bold text-muted-foreground">&mdash;</p>
              {/* Not silent. A dash with no explanation reads as "zero" to
                  anyone scanning quickly, which is the opposite of the truth. */}
              <p className="mt-1 text-xs text-destructive">Could not load</p>
            </>
          ) : (
            <p
              className={cn(
                "mt-1 text-2xl font-bold tabular-nums",
                warning && "text-amber-600"
              )}
            >
              {typeof value === "number" ? value.toLocaleString() : value}
            </p>
          )}
          <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
        </CardContent>
      </Card>
    </Link>
  )
}

export function AdminDashboardClient() {
  // Each panel fetches what it needs; one failing endpoint must not blank the
  // page an operator opened during an incident.
  // The whole `Page<T>` is kept, not `r.data`. `total` lives on the envelope, so
  // unwrapping to the array first and reading `.total` off it yields `undefined`
  // forever - which is what made this counter read zero no matter how many
  // markets were queued. The rows come off `data`; the count comes off `total`.
  const pending = useQuery({
    queryKey: queryKeys.adminMarkets("pending_review", 1),
    queryFn: () =>
      adminApi.markets({ status: "pending_review", page: 1, pageSize: 1 }),
    retry: false,
  });

  const failures = useQuery({
    queryKey: queryKeys.adminActions(1, { success: "failure" }),
    queryFn: () =>
      adminApi.actions({ page: 1, pageSize: 10, success: "failure" }),
    retry: false,
  });

  const recent = useQuery({
    queryKey: queryKeys.adminActions(1, {}),
    queryFn: () => adminApi.actions({ page: 1, pageSize: 8 }).then((r) => r.data),
    retry: false,
  });

  // What else is waiting. An operator opening this app during an incident needs
  // open disputes in the same glance as pending reviews — both are queues with
  // people waiting on them, and having one on the landing page and the other
  // two clicks away means the quieter one is the one that waits.
  const openDisputes = useQuery({
    queryKey: queryKeys.adminDisputes("open", 1, ""),
    queryFn: () => adminApi.disputes({ status: "open", page: 1, pageSize: 1 }),
    retry: false,
  });

  // Platform size. Not actionable, but it is the first question anyone asks an
  // operator ("how many users do we have?") and it was unanswerable from here.
  const totalUsers = useQuery({
    queryKey: queryKeys.adminUsers(1, "", "all", "newest"),
    queryFn: () => adminApi.users({ page: 1, pageSize: 1 }),
    retry: false,
  });

  const totalMarkets = useQuery({
    queryKey: queryKeys.adminMarkets("all", 1),
    queryFn: () => adminApi.markets({ page: 1, pageSize: 1 }),
    retry: false,
  });

  const liveMarkets = useQuery({
    queryKey: queryKeys.adminMarkets("active", 1),
    queryFn: () => adminApi.markets({ status: "active", page: 1, pageSize: 1 }),
    retry: false,
  });

  // Where the money is. A balance with no context is not useful, so the fees
  // already collected sit beside it rather than only being reachable by
  // navigating to the treasury page.
  const treasury = useQuery({
    queryKey: queryKeys.treasury(),
    queryFn: () => adminApi.treasury(),
    retry: false,
  });

  /**
   * Count from a paged endpoint, distinguishing three states the old cast
   * collapsed into two:
   *
   * - `undefined` while loading - the operator sees a spinner
   * - `null` on failure - the operator is told it did not load
   * - a number otherwise
   *
   * Conflating the last two is how a stat card ends up spinning forever on the
   * one screen an operator opens when the API is already misbehaving.
   */
  const count = (q: { data?: { total?: number }; isLoading: boolean; isError: boolean }) =>
    q.isLoading ? undefined : q.isError ? null : (q.data?.total ?? 0)

  const pendingTotal = count(pending)
  const failureTotal = count(failures)
  const disputeTotal = count(openDisputes)
  const userTotal = count(totalUsers)
  const marketTotal = count(totalMarkets)
  const liveTotal = count(liveMarkets)

  const recentRows = recent.data ?? []
  const failureRows = failures.data?.data ?? []

  const summary = treasury.data?.data
  const feesCollected = summary?.total_fees_collected

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Overview</h1>
        <p className="text-sm text-muted-foreground">
          What is waiting, and what happened.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat
          href="/markets"
          icon={ShieldAlert}
          label="Awaiting review"
          value={pendingTotal}
          tone="warning"
          hint="Submitted markets, not yet tradable"
        />
        <Stat
          href="/disputes"
          icon={Scale}
          label="Open disputes"
          value={disputeTotal}
          tone="warning"
          hint="Rulings outstanding"
        />
        <Stat
          href="/audit"
          icon={TriangleAlert}
          label="Failed privileged actions"
          value={failureTotal}
          tone="warning"
          hint="Refusals and step-up failures"
        />
      </div>

      {/* Platform size and the money. Not queues, but an operator is asked these
          within a minute of opening the app, and having to guess or go looking
          is what makes the first answer a guess. */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat
          href="/users"
          icon={Users}
          label="Users"
          value={userTotal}
          hint={
            userTotal !== undefined && userTotal !== null
              ? `${userTotal.toLocaleString()} registered`
              : "Registered accounts"
          }
        />
        <Stat
          href="/markets"
          icon={Store}
          label="Live markets"
          value={liveTotal}
          hint={
            marketTotal !== undefined && marketTotal !== null
              ? `of ${marketTotal.toLocaleString()} total`
              : "Currently tradable"
          }
        />
        <Stat
          href="/treasury"
          icon={Landmark}
          label="Treasury balance"
          value={treasury.isLoading ? undefined : treasury.isError ? null : glance(summary?.balance)}
          hint={
            feesCollected !== undefined
              ? `${glance(feesCollected)} USDC in fees collected`
              : "USDC held by the treasury"
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardContent className="space-y-3 px-5 py-4">
            <div className="flex items-center justify-between">
              <p className="flex items-center gap-1.5 text-sm font-medium">
                <TriangleAlert className="size-3.5 text-amber-600" aria-hidden />
                Failed privileged actions
              </p>
              <Link
                href="/audit"
                className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
              >
                See all
              </Link>
            </div>
            {failures.isLoading ? (
              <div className="flex h-24 items-center justify-center" role="status">
                <Spinner className="size-4" />
                <span className="sr-only">Loading failed actions…</span>
              </div>
            ) : failureRows.length === 0 ? (
              <p className="py-4 text-sm text-muted-foreground">
                Nothing has failed. A trail holding only what went through would be
                a log of what happened to be permitted, so this being empty is the
                point.
              </p>
            ) : (
              <ul className="space-y-2">
                {failureRows.slice(0, 6).map((row) => (
                  <li key={row.id} className="flex items-start justify-between gap-3 text-xs">
                    <div className="min-w-0">
                      <p className="font-medium">{row.action}</p>
                      <p className="truncate text-muted-foreground">
                        {row.failure_reason ?? row.summary ?? "—"}
                      </p>
                    </div>
                    <span className="shrink-0 whitespace-nowrap text-muted-foreground">
                      {new Date(row.created_at).toLocaleString()}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-3 px-5 py-4">
            <div className="flex items-center justify-between">
              <p className="flex items-center gap-1.5 text-sm font-medium">
                <ScrollText className="size-3.5" aria-hidden />
                Recent privileged actions
              </p>
              <Link
                href="/audit"
                className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
              >
                See all
              </Link>
            </div>
            {recent.isLoading ? (
              <div className="flex h-24 items-center justify-center" role="status">
                <Spinner className="size-4" />
                <span className="sr-only">Loading recent actions…</span>
              </div>
            ) : recentRows.length === 0 ? (
              <p className="py-4 text-sm text-muted-foreground">
                No privileged actions have been taken yet.
              </p>
            ) : (
              <ul className="space-y-2">
                {recentRows.map((row) => (
                  <li key={row.id} className="flex items-start justify-between gap-3 text-xs">
                    <div className="min-w-0">
                      <p className="font-medium">{row.action}</p>
                      <p className="truncate text-muted-foreground">
                        {row.actor_email ?? row.actor_id ?? "unknown actor"}
                      </p>
                    </div>
                    <Badge
                      variant={row.success === "success" ? "secondary" : "destructive"}
                      className="shrink-0"
                    >
                      {row.success}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
