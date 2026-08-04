"use client"

import { useState, useCallback, useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useNotifications, useMarkNotificationRead, useMarkAllNotificationsRead } from "@/hooks/use-notifications"
import { useCurrentUser } from "@/hooks/use-auth"
import { useUserSocket } from "@/hooks/use-user-socket"
import { Bell } from "lucide-react"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Spinner } from "@workspace/ui/components/spinner"

interface NotificationItem {
  id: string
  type: string
  title: string
  body: string | null
  data: Record<string, unknown> | null
  read_at: string | null
  created_at: string
}

export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const qc = useQueryClient()
  const { data: user } = useCurrentUser()
  const { data, isLoading, refetch } = useNotifications({ page_size: 20 })
  const { mutate: markRead } = useMarkNotificationRead()
  const { mutate: markAllRead } = useMarkAllNotificationsRead()

  // Initialize notifications from REST API
  useEffect(() => {
    if (data) {
      setNotifications(data)
    }
  }, [data])

  // Real-time WebSocket updates
  const handleWsMessage = useCallback((msg: unknown) => {
    const message = msg as { type?: string; notification?: NotificationItem }
    if (message.type === "notification" && message.notification) {
      setNotifications(prev => [message.notification!, ...prev])
    }
  }, [])

  const { status } = useUserSocket({
    userId: user?.id ?? "",
    onMessage: handleWsMessage,
    enabled: !!user?.id,
  })

  const unreadCount = notifications.filter(n => !n.read_at).length

  const handleMarkAllRead = useCallback(() => {
    markAllRead()
    setNotifications(prev => prev.map(n => ({ ...n, read_at: new Date().toISOString() })))
  }, [markAllRead])

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative p-2 hover:bg-muted rounded-lg transition-colors"
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
                  <div className="flex justify-center p-4"><Spinner className="size-5" /></div>
                ) : notifications.length === 0 ? (
                  <p className="text-sm text-muted-foreground p-4 text-center">No notifications</p>
                ) : (
                  notifications.map(n => (
                    <div
                      key={n.id}
                      className={`p-3 border-b last:border-0 ${!n.read_at ? "bg-muted/50" : ""}`}
                    >
                      <p className="text-sm font-medium">{n.title}</p>
                      {n.body && <p className="text-xs text-muted-foreground mt-1">{n.body}</p>}
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
