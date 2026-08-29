"use client"

import { useCallback, useRef, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  notificationsApi,
  type PaginatedNotifications,
} from "@/lib/api/notifications"
import { useCurrentUser } from "@/hooks/use-auth"
import { useUserSocket } from "@/hooks/use-user-socket"
import { SettingsBreadcrumb } from "@/components/settings/settings-breadcrumb"
import { Card } from "@workspace/ui/components/card"
import { Button } from "@workspace/ui/components/button"
import { Spinner } from "@workspace/ui/components/spinner"
import {
  Bell,
  BellRing,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  Info,
} from "lucide-react"
import { cn } from "@workspace/ui/lib/utils"
import type { Notification } from "@/schemas/notifications"

type NotifType = Notification["type"]

const TYPE_META: Record<
  NotifType,
  { icon: typeof Bell; color: string; label: string }
> = {
  order_filled: {
    icon: CheckCircle,
    color: "text-emerald-500",
    label: "Order Filled",
  },
  order_cancelled: {
    icon: XCircle,
    color: "text-red-500",
    label: "Order Cancelled",
  },
  alert_triggered: {
    icon: AlertTriangle,
    color: "text-amber-500",
    label: "Alert",
  },
  market_resolved: {
    icon: CheckCircle,
    color: "text-violet-500",
    label: "Market Resolved",
  },
  market_closing_soon: {
    icon: Clock,
    color: "text-orange-500",
    label: "Closing Soon",
  },
  weekly_digest: { icon: Info, color: "text-blue-500", label: "Weekly Digest" },
}

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return "just now"
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay}d ago`
  return date.toLocaleDateString()
}

function NotificationItem({ notif }: { notif: Notification }) {
  const notifType = notif.type as NotifType
  const {
    icon: Icon,
    color,
    label,
  } = TYPE_META[notifType] ?? {
    icon: AlertTriangle,
    color: "text-muted-foreground",
    label: "Notification",
  }
  const isUnread = !notif.read_at

  return (
    <div
      className={cn(
        "flex items-start gap-3 px-4 py-3 transition-colors",
        isUnread ? "bg-muted/40" : "hover:bg-muted/30"
      )}
    >
      <div className={cn("mt-0.5 shrink-0", color)}>
        <Icon className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <p
            className={cn(
              "text-sm leading-snug",
              isUnread ? "font-medium" : "text-muted-foreground"
            )}
          >
            {notif.title}
          </p>
          {isUnread && (
            <span className="mt-1 size-2 shrink-0 rounded-full bg-primary" />
          )}
        </div>
        {notif.body && (
          <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
            {notif.body}
          </p>
        )}
        <p className="mt-1 text-[11px] text-muted-foreground/60">
          {label} · {formatRelativeTime(notif.created_at)}
        </p>
      </div>
    </div>
  )
}

export default function NotificationsPage() {
  const { data: user } = useCurrentUser()
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [realtimePrepend, setRealtimePrepend] = useState<Notification[]>([])

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["notifications-list", page] as const,
    queryFn: () => notificationsApi.list({ page, page_size: 30 }),
    enabled: !!user,
  })

  const { mutate: markRead } = useMutation({
    mutationFn: (id: string) => notificationsApi.markRead(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications-list"] }),
  })

  const { mutate: markAllRead } = useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications-list"] })
    },
  })

  const handleWsMessage = useCallback(
    (msg: unknown) => {
      const message = msg as { type?: string; notification?: Notification }
      if (message.type === "notification" && message.notification) {
        setRealtimePrepend((prev) => [message.notification!, ...prev])
        qc.invalidateQueries({ queryKey: ["notifications-list"] })
      }
    },
    [qc]
  )

  useUserSocket({
    userId: user?.id ?? "",
    onMessage: handleWsMessage,
    enabled: !!user?.id,
  })

  const notifications = [...realtimePrepend, ...(data?.data ?? [])]
  const unreadCount =
    (data?.data ?? []).filter((n) => !n.read_at).length +
    realtimePrepend.filter((n) => !n.read_at).length

  const handleMarkAllRead = useCallback(() => {
    markAllRead()
  }, [markAllRead])

  const handleLoadMore = useCallback(() => {
    setPage((p) => p + 1)
  }, [])

  if (!user) return null

  return (
    <div className="container mx-auto max-w-7xl space-y-6 px-4 py-8">
      <SettingsBreadcrumb page="Notifications" />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Notifications</h1>
          {unreadCount > 0 && (
            <p className="mt-0.5 text-sm text-muted-foreground">
              {unreadCount} unread
            </p>
          )}
        </div>
        {unreadCount > 0 && (
          <Button variant="outline" size="sm" onClick={handleMarkAllRead}>
            Mark all read
          </Button>
        )}
      </div>

      <Card className="overflow-hidden pt-0">
        <div
          className="overflow-auto"
          style={{ maxHeight: "600px", minHeight: "200px" }}
        >
          {isLoading ? (
            <div className="flex h-48 items-center justify-center">
              <Spinner className="size-5" />
            </div>
          ) : notifications.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-4 py-16 text-center">
              <div className="mb-4 flex size-12 items-center justify-center rounded-full bg-muted">
                <Bell className="size-6 text-muted-foreground" />
              </div>
              <p className="text-sm font-medium">No notifications</p>
              <p className="mt-1 max-w-52 text-xs text-muted-foreground">
                You'll see order updates, market alerts, and more here
              </p>
            </div>
          ) : (
            <div className="divide-y">
              {notifications.map((n) => (
                <NotificationItem key={n.id} notif={n} />
              ))}
            </div>
          )}
        </div>

        {data?.has_more && (
          <div className="flex justify-center border-t px-4 py-3">
            <Button
              variant="outline"
              size="sm"
              onClick={handleLoadMore}
              disabled={isFetching}
            >
              {isFetching ? <Spinner className="size-3" /> : "Load more"}
            </Button>
          </div>
        )}
      </Card>
    </div>
  )
}
