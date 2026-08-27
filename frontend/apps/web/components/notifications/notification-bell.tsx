"use client"

import Link from "next/link"
import React, { useCallback, useMemo, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@workspace/ui/components/popover"
import {
  useNotifications,
  useMarkNotificationRead,
  useMarkAllNotificationsRead,
} from "@/hooks/api/use-notifications"
import { useCurrentUser } from "@/hooks/use-auth"
import { useUserSocket } from "@/hooks/use-user-socket"
import type { Notification } from "@/lib/schemas/notifications"
import { Bell, BellRing, CheckCircle, XCircle, AlertTriangle, Clock, Info } from "lucide-react"
import { Spinner } from "@workspace/ui/components/spinner"
import { cn } from "@workspace/ui/lib/utils"

type NotifType = Notification["type"]

const TYPE_META: Record<NotifType, { icon: typeof Bell; color: string; label: string }> = {
  order_filled: { icon: CheckCircle, color: "text-emerald-500", label: "Order Filled" },
  order_cancelled: { icon: XCircle, color: "text-red-500", label: "Order Cancelled" },
  alert_triggered: { icon: AlertTriangle, color: "text-amber-500", label: "Alert" },
  market_resolved: { icon: CheckCircle, color: "text-violet-500", label: "Market Resolved" },
  market_closing_soon: { icon: Clock, color: "text-orange-500", label: "Closing Soon" },
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

const NotificationItem = React.memo(function NotificationItem({
  notif,
  onRead,
}: {
  notif: Notification
  onRead: (id: string) => void
}) {
  const notifType = notif.type as NotifType
  const { icon: Icon, color, label } = TYPE_META[notifType] ?? {
    icon: AlertTriangle,
    color: "text-muted-foreground",
    label: "Notification",
  }
  const isUnread = !notif.read_at

  const handleClick = useCallback(() => {
    if (!isUnread) return
    onRead(notif.id)
  }, [isUnread, notif.id, onRead])

  return (
    <button
      onClick={handleClick}
      className={cn(
        "w-full text-left flex items-start gap-3 px-4 py-3 transition-colors focus-visible:outline-none focus-visible:bg-muted/50",
        isUnread ? "bg-muted/40" : "hover:bg-muted/30"
      )}
    >
      <div className={cn("mt-0.5 shrink-0", color)}>
        <Icon className="size-4" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <p className={cn("text-sm leading-snug", isUnread ? "font-medium" : "text-muted-foreground")}>
            {notif.title}
          </p>
          {isUnread && (
            <span className="mt-1 size-2 shrink-0 rounded-full bg-primary" />
          )}
        </div>
        {notif.body && (
          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
            {notif.body}
          </p>
        )}
        <p className="text-[11px] text-muted-foreground/60 mt-1">
          {label} · {formatRelativeTime(notif.created_at)}
        </p>
      </div>
    </button>
  )
})

const NotificationSkeleton = React.memo(function NotificationSkeleton() {
  return (
    <div className="flex items-start gap-3 px-4 py-3 animate-pulse">
      <div className="size-4 rounded-full bg-muted mt-0.5 shrink-0" />
      <div className="flex-1 space-y-2">
        <div className="h-3 bg-muted rounded w-3/4" />
        <div className="h-2.5 bg-muted rounded w-1/2" />
        <div className="h-2 bg-muted rounded w-1/3" />
      </div>
    </div>
  )
})

const EmptyState = React.memo(function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-10 px-4 text-center">
      <div className="size-10 rounded-full bg-muted flex items-center justify-center mb-3">
        <Bell className="size-5 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium">No notifications</p>
      <p className="text-xs text-muted-foreground mt-1 max-w-44">
        You'll see order updates, market alerts, and more here
      </p>
    </div>
  )
})

export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()
  const { data: user } = useCurrentUser()
  const { data: notifData = [], isLoading } = useNotifications({ page_size: 20 })
  const { mutate: markRead } = useMarkNotificationRead()
  const { mutate: markAllRead } = useMarkAllNotificationsRead()

  const [overlay, setOverlay] = useState<{
    prepends: Notification[]
    readIds: Set<string>
  }>({ prepends: [], readIds: new Set() })

  const notifications = useMemo(
    () => [...overlay.prepends, ...notifData].filter((n) => !overlay.readIds.has(n.id)),
    [overlay, notifData]
  )

  const unreadCount = notifications.filter((n) => !n.read_at).length

  const handleWsMessage = useCallback(
    (msg: unknown) => {
      const message = msg as { type?: string; notification?: Notification }
      if (message.type === "notification" && message.notification) {
        setOverlay((prev) => ({
          ...prev,
          prepends: [message.notification!, ...prev.prepends],
        }))
        qc.invalidateQueries({ queryKey: ["notifications"] })
      }
    },
    [qc]
  )

  useUserSocket({
    userId: user?.id ?? "",
    onMessage: handleWsMessage,
    enabled: !!user?.id,
  })

  const handleMarkRead = useCallback(
    (id: string) => {
      setOverlay((prev) => ({ ...prev, readIds: new Set([...prev.readIds, id]) }))
      markRead(id)
    },
    [markRead]
  )

  const handleMarkAllRead = useCallback(() => {
    setOverlay((prev) => {
      const allIds = new Set(prev.readIds)
      notifications.forEach((n) => allIds.add(n.id))
      return { ...prev, readIds: allIds }
    })
    markAllRead()
  }, [markAllRead, notifications])

  const handleViewAllClick = useCallback(() => {
    setOpen(false)
  }, [])

  if (!user) return null

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        className="relative p-2 hover:bg-muted rounded-lg transition-colors"
        aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ""}`}
      >
        {unreadCount > 0 ? (
          <BellRing className="size-5" />
        ) : (
          <Bell className="size-5" />
        )}
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 size-4 rounded-full bg-red-500 text-white text-[10px] font-medium flex items-center justify-center">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </PopoverTrigger>

      <PopoverContent align="end" side="bottom" sideOffset={8} className="w-80 p-0 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b shrink-0">
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold">Notifications</p>
            {unreadCount > 0 && (
              <span className="px-1.5 py-0.5 rounded-full bg-red-500 text-[10px] text-white font-medium">
                {unreadCount}
              </span>
            )}
          </div>
          {unreadCount > 0 && (
            <button
              onClick={handleMarkAllRead}
              className="text-[11px] text-muted-foreground hover:text-foreground transition-colors font-medium"
            >
              Mark all read
            </button>
          )}
        </div>

        {/* Scrollable List */}
        <div className="max-h-80 overflow-y-auto divide-y scrollbar-hide">
          {isLoading ? (
            <>
              <NotificationSkeleton />
              <NotificationSkeleton />
              <NotificationSkeleton />
            </>
          ) : notifications.length === 0 ? (
            <EmptyState />
          ) : (
            notifications.map((n) => (
              <NotificationItem key={n.id} notif={n} onRead={handleMarkRead} />
            ))
          )}
        </div>

        {/* Footer */}
        {notifications.length > 0 && (
          <div className="px-4 py-2.5 border-t shrink-0">
            <Link
              href="/notifications"
              onClick={handleViewAllClick}
              className="block w-full text-center text-xs text-muted-foreground hover:text-foreground transition-colors font-medium"
            >
              View all notifications
            </Link>
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}
