"use client"

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { adminApi } from "@workspace/api-client/admin"
import { queryKeys } from "@/lib/queryKeys"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import { Card, CardContent } from "@workspace/ui/components/card"
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
 * The two audit trails, side by side.
 *
 * They answer different questions and both belong on one screen:
 *
 *  - **Privileged actions** — who did what that moved money or changed access.
 *    A ruling, a ban, a fee distribution, a step-up failure.
 *  - **Auth events** — who signed in, from where, and whether it worked. Login
 *    and password-reset, for every account.
 *
 * The failure filter is deliberately prominent on the privileged list. A log
 * holding only what went through is a log of what happened to be permitted, so
 * the refused attempts are the ones an operator is usually looking for.
 */
export function AdminAuditClient() {
  const [tab, setTab] = useState<"actions" | "auth">("actions")
  const [success, setSuccess] = useState<"success" | "failure" | undefined>()

  const actions = useQuery({
    queryKey: queryKeys.adminActions(1, { success }),
    queryFn: () => adminApi.actions({ page: 1, pageSize: 50, success }).then((r) => r.data),
    enabled: tab === "actions",
    retry: false,
  })

  const events = useQuery({
    queryKey: ["admin", "auth-events", 1],
    queryFn: () => adminApi.auditEvents({ page: 1, pageSize: 50 }).then((r) => r.data),
    enabled: tab === "auth",
    retry: false,
  })

  const actionRows = actions.data ?? []
  const eventRows = events.data ?? []

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Audit trail</h1>
          <p className="text-sm text-muted-foreground">
            Privileged actions and authentication events.
          </p>
        </div>
        <div className="flex gap-2">
          <div className="flex gap-1" role="group" aria-label="Which trail">
            <Button
              variant={tab === "actions" ? "default" : "outline"}
              size="sm"
              onClick={() => setTab("actions")}
              aria-pressed={tab === "actions"}
            >
              Privileged actions
            </Button>
            <Button
              variant={tab === "auth" ? "default" : "outline"}
              size="sm"
              onClick={() => setTab("auth")}
              aria-pressed={tab === "auth"}
            >
              Auth events
            </Button>
          </div>
          {tab === "actions" && (
            <Button
              variant={success === "failure" ? "default" : "outline"}
              size="sm"
              onClick={() =>
                setSuccess((s) => (s === "failure" ? undefined : "failure"))
              }
              aria-pressed={success === "failure"}
            >
              {success === "failure" ? "Showing failures" : "Failures only"}
            </Button>
          )}
        </div>
      </div>

      <Card className="overflow-hidden pt-0">
        {tab === "actions" ? (
          actions.isLoading ? (
            <CardContent role="status" className="flex h-48 items-center justify-center">
              <Spinner className="size-5" />
              <span className="sr-only">Loading actions…</span>
            </CardContent>
          ) : actionRows.length === 0 ? (
            <CardContent role="status" className="flex h-48 items-center justify-center text-sm text-muted-foreground">
              No privileged actions recorded.
            </CardContent>
          ) : (
            <div className="max-h-[65vh] overflow-auto">
              <Table noWrapper className="w-full min-w-[760px]">
                <TableHeader className="sticky top-0 z-10 bg-muted">
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Actor</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>Target</TableHead>
                    <TableHead>Outcome</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {actionRows.map((row) => (
                    <TableRow key={row.id} className="hover:bg-accent/30">
                      <TableCell className="text-xs whitespace-nowrap">
                        {new Date(row.created_at).toLocaleString()}
                      </TableCell>
                      <TableCell className="text-xs">
                        {row.actor_email ?? (
                          <span className="text-muted-foreground">
                            {row.actor_id ?? "unknown actor"}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-xs font-medium">{row.action}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {row.target_type ? `${row.target_type}` : "—"}
                        {row.target_id ? ` · ${row.target_id.slice(0, 8)}` : ""}
                      </TableCell>
                      <TableCell className="text-xs">
                        <Badge
                          variant={row.success === "success" ? "secondary" : "destructive"}
                        >
                          {row.success}
                        </Badge>
                        {row.failure_reason && (
                          <p className="mt-1 max-w-xs truncate text-muted-foreground" title={row.failure_reason}>
                            {row.failure_reason}
                          </p>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )
        ) : events.isLoading ? (
          <CardContent role="status" className="flex h-48 items-center justify-center">
            <Spinner className="size-5" />
            <span className="sr-only">Loading auth events…</span>
          </CardContent>
        ) : eventRows.length === 0 ? (
          <CardContent role="status" className="flex h-48 items-center justify-center text-sm text-muted-foreground">
            No authentication events recorded.
          </CardContent>
        ) : (
          <div className="max-h-[65vh] overflow-auto">
            <Table noWrapper className="w-full min-w-[760px]">
              <TableHeader className="sticky top-0 z-10 bg-muted">
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Event</TableHead>
                  <TableHead>User</TableHead>
                  <TableHead>IP</TableHead>
                  <TableHead>Outcome</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {eventRows.map((row) => (
                  <TableRow key={row.id} className="hover:bg-accent/30">
                    <TableCell className="text-xs whitespace-nowrap">
                      {new Date(row.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-xs font-medium">{row.event}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {row.user_id?.slice(0, 8) ?? "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {row.ip_address ?? "—"}
                    </TableCell>
                    <TableCell className="text-xs">
                      <Badge variant={row.success === "success" ? "secondary" : "destructive"}>
                        {row.success}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>
    </div>
  )
}