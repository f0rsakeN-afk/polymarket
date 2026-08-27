"use client"

import { useRouter } from "next/navigation"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useCallback } from "react"
import { authApi } from "@/lib/api/auth"
import { Button } from "@workspace/ui/components/button"
import { Card, CardContent, CardHeader, CardTitle } from "@workspace/ui/components/card"
import { Badge } from "@workspace/ui/components/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@workspace/ui/components/table"
import { Spinner } from "@workspace/ui/components/spinner"
import { sileo } from "sileo"
import { Globe, Monitor, Smartphone, Trash2 } from "lucide-react"
import { cn } from "@workspace/ui/lib/utils"
import { SettingsBreadcrumb } from "@/components/settings/settings-breadcrumb"

function formatDate(dateStr: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(dateStr))
}

function parseDevice(ua: string | null | undefined): { icon: typeof Globe; label: string; sub: string } {
  if (!ua) return { icon: Globe, label: "Unknown Device", sub: "Unknown device" }
  const isMobile = /iPhone|iPad|iPod|Android/i.test(ua)
  const browser = ua.includes("Chrome") ? "Chrome"
    : ua.includes("Firefox") ? "Firefox"
    : ua.includes("Safari") ? "Safari"
    : ua.includes("Edge") ? "Edge" : "Other"
  const os = ua.includes("Windows") ? "Windows"
    : ua.includes("Mac") ? "macOS"
    : ua.includes("Linux") ? "Linux"
    : ua.includes("Android") ? "Android"
    : ua.includes("iOS") ? "iOS" : "Other"
  return {
    icon: isMobile ? Smartphone : Monitor,
    label: `${browser} on ${os}`,
    sub: ua.length > 60 ? ua.slice(0, 60) + "…" : ua,
  }
}

function CurrentBadge() {
  return (
    <Badge className="bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300 text-xs capitalize">
      current
    </Badge>
  )
}

// ── Session Row ────────────────────────────────────────────────────────────────

function SessionRow({ session, onRevoke, isRevoking }: {
  session: { id: string; ip_address?: string; last_active_at: string; expires_at: string; user_agent?: string; is_current?: boolean }
  onRevoke: (id: string) => () => void
  isRevoking: boolean
}) {
  const { icon: Icon, label, sub } = parseDevice(session.user_agent)
  const isExpired = new Date(session.expires_at) < new Date()

  return (
    <TableRow className="hover:bg-accent/30 transition-colors">
      <TableCell>
        <div className="flex items-center gap-3">
          <div className="size-8 rounded-lg bg-accent flex items-center justify-center shrink-0">
            <Icon className="size-4 text-muted-foreground" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium truncate">{label}</p>
              {session.is_current && <CurrentBadge />}
              {isExpired && (
                <Badge variant="secondary" className="text-xs capitalize">expired</Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground truncate mt-0.5">{sub}</p>
          </div>
        </div>
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">
        {session.ip_address ?? "—"}
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">
        {formatDate(session.last_active_at)}
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">
        {formatDate(session.expires_at)}
      </TableCell>
      <TableCell className="text-right">
        {!session.is_current && (
          <button
            onClick={onRevoke(session.id)}
            disabled={isRevoking}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-50",
            )}
          >
            <Trash2 className="size-3" />
            Revoke
          </button>
        )}
      </TableCell>
    </TableRow>
  )
}

// ── Sessions Table ─────────────────────────────────────────────────────────────

function SessionsTable({ sessions, isLoading, onRevoke, isRevoking }: {
  sessions: Array<{ id: string; ip_address?: string; last_active_at: string; expires_at: string; user_agent?: string; is_current?: boolean }>
  isLoading: boolean
  onRevoke: (id: string) => () => void
  isRevoking: boolean
}) {
  if (isLoading) {
    return (
      <Card className="overflow-hidden pt-0">
        <CardContent className="flex h-48 items-center justify-center">
          <Spinner className="size-5" />
        </CardContent>
      </Card>
    )
  }

  if (sessions.length === 0) {
    return (
      <Card className="overflow-hidden pt-0">
        <CardContent className="flex h-48 items-center justify-center text-sm text-muted-foreground">
          No active sessions found
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="overflow-hidden pt-0">
      <div className="overflow-auto" style={{ maxHeight: "600px", minHeight: "200px" }}>
        <Table noWrapper className="w-full" style={{ tableLayout: "fixed" }}>
          <colgroup>
            <col className="w-[35%]" />
            <col className="w-[15%]" />
            <col className="w-[20%]" />
            <col className="w-[20%]" />
            <col className="w-[10%]" />
          </colgroup>
          <TableHeader className="sticky top-0 z-20 bg-muted">
            <TableRow className="hover:bg-transparent">
              <TableHead>Device</TableHead>
              <TableHead>IP Address</TableHead>
              <TableHead>Last Active</TableHead>
              <TableHead>Expires</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {sessions.map((session) => (
              <SessionRow
                key={session.id}
                session={session}
                onRevoke={onRevoke}
                isRevoking={isRevoking}
              />
            ))}
          </TableBody>
        </Table>
      </div>
    </Card>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function SessionsPageClient() {
  const router = useRouter()
  const qc = useQueryClient()

  const { data: sessions, isLoading } = useQuery({
    queryKey: ["sessions"] as const,
    queryFn: () => authApi.sessions().then((r) => r.data as Array<{
      id: string; ip_address?: string; last_active_at: string; expires_at: string; user_agent?: string; is_current?: boolean
    }>),
    retry: false,
  })

  const revokeMutation = useMutation({
    mutationFn: (sessionId: string) => authApi.revokeSession(sessionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sessions"] })
      sileo.success({ title: "Session revoked" })
    },
    onError: () => {
      sileo.error({ title: "Failed to revoke session" })
    },
  })

  const revokeAllMutation = useMutation({
    mutationFn: () => authApi.logoutAll(),
    onSuccess: () => {
      qc.removeQueries({ queryKey: ["sessions"] })
      qc.removeQueries({ queryKey: ["me"] })
      sileo.success({ title: "All other sessions revoked" })
      router.push("/")
    },
    onError: () => {
      sileo.error({ title: "Failed to revoke sessions" })
    },
  })

  const sessionList = sessions ?? []
  const hasOthers = sessionList.length > 1

  const handleRevokeAll = useCallback(() => revokeAllMutation.mutate(), [revokeAllMutation])
  const handleRevoke = useCallback((id: string) => () => revokeMutation.mutate(id), [revokeMutation])

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8 space-y-6">
      <SettingsBreadcrumb page="Sessions" />
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Active Sessions</h1>
          <p className="text-sm text-muted-foreground mt-0.5">{sessionList.length} device{sessionList.length !== 1 ? "s" : ""} logged in</p>
        </div>
        {hasOthers && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleRevokeAll}
            disabled={revokeAllMutation.isPending}
            className="text-destructive hover:text-destructive hover:bg-destructive/10"
          >
            Revoke all other sessions
          </Button>
        )}
      </div>

      {/* Sessions Table */}
      <SessionsTable
        sessions={sessionList}
        isLoading={isLoading}
        onRevoke={handleRevoke}
        isRevoking={revokeMutation.isPending}
      />
    </div>
  )
}
