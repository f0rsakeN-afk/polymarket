"use client"

import { useState, useCallback } from "react"
import { useQueryClient } from "@tanstack/react-query"
import {
  useNotifications,
  useMarkNotificationRead,
  useMarkAllNotificationsRead,
} from "@/hooks/api/use-notifications"
import { useCurrentUser } from "@/hooks/use-auth"
import { useUserSocket } from "@/hooks/use-user-socket"
import type { Notification } from "@/lib/schemas/notifications"
import { Bell } from "lucide-react"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Spinner } from "@workspace/ui/components/spinner"

export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()
  const { data: user } = useCurrentUser()
  const { data: notifData = [], isLoading } = useNotifications({ page_size: 20 })
  const { mutate: markRead } = useMarkNotificationRead()
  const { mutate: markAllRead } = useMarkAllNotificationsRead()

  // Optimistic overlay for real-time prepends and read updates.
  // WebSocket pushes are prepended here; REST data is the fallback.
  const [overlay, setOverlay] = useState<{
    prepends: Notification[]
    readIds: Set<string>
  }>({ prepends: [], readIds: new Set() })

  // Merge REST data with optimistic overlay
  const notifications = [...overlay.prepends, ...notifData].filter(
    (n) => !overlay.readIds.has(n.id)
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

  const { status } = useUserSocket({
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
  }, [markAllRead])

  if (!user) return null

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative p-2 hover:bg-muted rounded-lg transition-colors"
        aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ""}`}
      >
        <Bell className="size-5" />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 size-4 rounded-full bg-red-500 text-[10px] text-white flex items-center justify-center">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <Card className="absolute right-0 top-full mt-2 w-80 z-50 shadow-lg">
            <CardContent className="p-0">
              <div className="flex items-center justify-between p-3 border-b">
                <h3 className="font-semibold text-sm">Notifications</h3>
                {unreadCount > 0 && (
                  <button
                    onClick={handleMarkAllRead}
                    className="text-xs text-muted-foreground hover:text-foreground"
                  >
                    Mark all read
                  </button>
                )}
              </div>
              <div className="max-h-80 overflow-y-auto">
                {isLoading ? (
                  <div className="flex justify-center p-4">
                    <Spinner className="size-5" />
                  </div>
                ) : notifications.length === 0 ? (
                  <p className="text-sm text-muted-foreground p-4 text-center">
                    No notifications
                  </p>
                ) : (
                  notifications.map((n) => (
                    <div
                      key={n.id}
                      className={`p-3 border-b last:border-0 cursor-pointer hover:bg-muted/50 transition-colors ${
                        !n.read_at ? "bg-muted/30" : ""
                      }`}
                      onClick={() => !n.read_at && handleMarkRead(n.id)}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-sm font-medium leading-tight">{n.title}</p>
                        {!n.read_at && (
                          <span className="mt-1 size-2 shrink-0 rounded-full bg-primary" />
                        )}
                      </div>
                      {n.body && (
                        <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                          {n.body}
                        </p>
                      )}
                      <p className="text-[10px] text-muted-foreground mt-1">
                        {new Date(n.created_at).toLocaleDateString()}
                      </p>
                    </div>
                  ))
                )}
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
