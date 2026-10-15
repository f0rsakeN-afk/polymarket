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
import { ScrollText, ShieldAlert, TriangleAlert, Users } from "lucide-react"

import { adminApi } from "@workspace/api-client/admin"
import { queryKeys } from "@/lib/queryKeys"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Badge } from "@workspace/ui/components/badge"
import { buttonVariants } from "@workspace/ui/components/button"
import { Spinner } from "@workspace/ui/components/spinner"
import { cn } from "@workspace/ui/lib/utils"

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
  value: number | undefined
  tone: "default" | "warning"
  hint: string
}) {
  return (
    <Link href={href} className="group">
      <Card className="h-full transition-colors group-hover:bg-accent/40">
        <CardContent className="px-5 py-4">
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">{label}</p>
            <Icon
              className={cn(
                "size-4",
                tone === "warning" ? "text-amber-600" : "text-muted-foreground"
              )}
              aria-hidden
            />
          </div>
          {value === undefined ? (
            <div className="mt-2 flex h-8 items-center" role="status">
              <Spinner className="size-4" />
              <span className="sr-only">Loading {label}</span>
            </div>
          ) : (
            <p
              className={cn(
                "mt-1 text-2xl font-bold tabular-nums",
                tone === "warning" && value > 0 && "text-amber-600"
              )}
            >
              {value}
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
  const pending = useQuery({
    queryKey: queryKeys.adminMarkets("pending_review", 1),
    queryFn: () => adminApi.markets("pending_review", 1, 1).then((r) => r.data),
    retry: false,
  });

  const failures = useQuery({
    queryKey: queryKeys.adminActions(1, { success: "failure" }),
    queryFn: () =>
      adminApi.actions({ page: 1, pageSize: 10, success: "failure" }).then((r) => r.data),
    retry: false,
  });

  const recent = useQuery({
    queryKey: queryKeys.adminActions(1, {}),
    queryFn: () => adminApi.actions({ page: 1, pageSize: 8 }).then((r) => r.data),
    retry: false,
  });

  const pendingTotal = (pending.data as { total?: number } | undefined)?.total ?? 0
  const failureTotal = (failures.data as { total?: number } | undefined)?.total ?? 0
  const recentRows = recent.data ?? []
  const failureRows = failures.data ?? []

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
          value={pending.isError ? undefined : pendingTotal}
          tone="warning"
          hint="Submitted markets, not yet tradable"
        />
        <Stat
          href="/audit"
          icon={TriangleAlert}
          label="Failed privileged actions"
          value={failures.isError ? undefined : failureTotal}
          tone="warning"
          hint="Refusals and step-up failures"
        />
        <div>
          <Card className="h-full">
            <CardContent className="px-5 py-4">
              <p className="text-xs text-muted-foreground">Sections</p>
              <div className="mt-3 flex flex-col gap-1.5 text-sm">
                <Link href="/users" className="text-primary hover:underline">
                  Users &amp; investigations
                </Link>
                <Link href="/disputes" className="text-primary hover:underline">
                  Dispute queue
                </Link>
                <Link href="/markets" className="text-primary hover:underline">
                  Moderation queue
                </Link>
                <Link href="/treasury" className="text-primary hover:underline">
                  Treasury &amp; fees
                </Link>
                <Link href="/audit" className="text-primary hover:underline">
                  Audit trail
                </Link>
              </div>
            </CardContent>
          </Card>
        </div>
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
