"use client"

import { SettingsBreadcrumb } from "@/components/settings/settings-breadcrumb"
import { useNotificationPreferences, useUpdateNotificationPreferences } from "@/hooks/api/use-notifications"
import { Switch } from "@workspace/ui/components/switch"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@workspace/ui/components/card"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { sileo } from "sileo"
import type { NotificationPreference } from "@/schemas/notifications"

interface ToggleRowProps {
  label: string
  description: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}

function ToggleRow({ label, description, checked, onChange, disabled }: ToggleRowProps) {
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="flex-1">
        <p className="text-sm font-medium">{label}</p>
        <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
      </div>
      <Switch checked={checked} onCheckedChange={onChange} disabled={disabled} />
    </div>
  )
}

export function NotificationPreferencesClient() {
  const { data: prefs, isLoading } = useNotificationPreferences()
  const updateMutation = useUpdateNotificationPreferences()

  const handleToggle = (key: keyof NotificationPreference, value: boolean) => {
    updateMutation.mutate(
      { [key]: value },
      {
        onSuccess: () => sileo.success({ title: "Preferences saved" }),
        onError: () => sileo.error({ title: "Failed to save preferences" }),
      }
    )
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        {/* Email notifications card skeleton */}
        <Card>
          <CardHeader className="pb-3">
            <Skeleton className="h-4 w-36" />
            <Skeleton className="h-3 w-24 mt-1" />
          </CardHeader>
          <CardContent className="divide-y">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="flex items-center justify-between py-3 gap-4">
                <div className="space-y-1.5">
                  <Skeleton className="h-3.5 w-28" />
                  <Skeleton className="h-3 w-40" />
                </div>
                <Skeleton className="h-5 w-10 rounded-full" />
              </div>
            ))}
          </CardContent>
        </Card>
        {/* In-app notifications card skeleton */}
        <Card>
          <CardHeader className="pb-3">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3 w-32 mt-1" />
          </CardHeader>
          <CardContent className="divide-y">
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex items-center justify-between py-3 gap-4">
                <div className="space-y-1.5">
                  <Skeleton className="h-3.5 w-32" />
                  <Skeleton className="h-3 w-48" />
                </div>
                <Skeleton className="h-5 w-10 rounded-full" />
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    )
  }

  const p = prefs ?? {
    email_alerts: false,
    email_order_fills: false,
    email_market_resolution: false,
    email_weekly_digest: false,
    push_alerts: false,
    push_order_fills: false,
    push_market_resolution: false,
  }

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8 space-y-6">
      <SettingsBreadcrumb page="Notifications" />
      <div>
        <h1 className="text-2xl font-semibold">Notification Preferences</h1>
        <p className="text-sm text-muted-foreground mt-1">Manage how you receive alerts</p>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Email Notifications</CardTitle>
          <CardDescription>Receive updates via email</CardDescription>
        </CardHeader>
        <CardContent className="divide-y">
          <ToggleRow
            label="Order Fills"
            description="Get notified when your orders are filled"
            checked={p.email_order_fills}
            onChange={(v) => handleToggle("email_order_fills", v)}
            disabled={updateMutation.isPending}
          />
          <ToggleRow
            label="Price Alerts"
            description="Updates on markets you're tracking"
            checked={p.email_alerts}
            onChange={(v) => handleToggle("email_alerts", v)}
            disabled={updateMutation.isPending}
          />
          <ToggleRow
            label="Market Resolution"
            description="When markets resolve and settle"
            checked={p.email_market_resolution}
            onChange={(v) => handleToggle("email_market_resolution", v)}
            disabled={updateMutation.isPending}
          />
          <ToggleRow
            label="Weekly Digest"
            description="A summary of your activity each week"
            checked={p.email_weekly_digest}
            onChange={(v) => handleToggle("email_weekly_digest", v)}
            disabled={updateMutation.isPending}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">In-App Notifications</CardTitle>
          <CardDescription>Real-time alerts via WebSocket</CardDescription>
        </CardHeader>
        <CardContent className="divide-y">
          <ToggleRow
            label="All Notifications"
            description="Receive real-time updates for order fills and market activity"
            checked={p.push_alerts}
            onChange={(v) => handleToggle("push_alerts", v)}
            disabled={updateMutation.isPending}
          />
          <ToggleRow
            label="Order Fills"
            description="Get notified when your orders are filled"
            checked={p.push_order_fills}
            onChange={(v) => handleToggle("push_order_fills", v)}
            disabled={updateMutation.isPending}
          />
          <ToggleRow
            label="Market Resolution"
            description="When markets resolve and settle"
            checked={p.push_market_resolution}
            onChange={(v) => handleToggle("push_market_resolution", v)}
            disabled={updateMutation.isPending}
          />
        </CardContent>
      </Card>
    </div>
  )
}
