import { z } from "zod"

export const notificationPreferenceSchema = z.object({
  email_alerts: z.boolean(),
  email_order_fills: z.boolean(),
  email_market_resolution: z.boolean(),
  email_weekly_digest: z.boolean(),
  push_alerts: z.boolean(),
  push_order_fills: z.boolean(),
  push_market_resolution: z.boolean(),
})

export const updateNotificationPreferencesSchema =
  notificationPreferenceSchema.partial()

export const notificationSchema = z.object({
  id: z.string(),
  type: z.string(),
  title: z.string(),
  body: z.string().nullable(),
  data: z.record(z.string(), z.unknown()).nullable(),
  read_at: z.string().nullable(),
  created_at: z.string(),
})

export type NotificationPreference = z.infer<
  typeof notificationPreferenceSchema
>
export type UpdateNotificationPreferences = z.infer<
  typeof updateNotificationPreferencesSchema
>
export type Notification = z.infer<typeof notificationSchema>
