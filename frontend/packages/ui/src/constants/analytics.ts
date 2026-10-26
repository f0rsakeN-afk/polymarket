/**
 * Canonical analytics event names.
 *
 * Add new events here — never as free-form strings in payload — and add a
 * migration + retention policy. The frontend must import from this file so the
 * event name is validated at compile time rather than mismatched at runtime.
 */

export const ANALYTICS_EVENTS = {
  // Chart feature usage
  CHART_TOGGLE: "chart_toggle",
  INTERVAL_SELECT: "interval_select",

  // Admin actions
  USER_LIST: "admin_user_list",
  USER_DETAIL_VIEW: "admin_user_detail_view",
  USER_BAN: "admin_user_ban",
  USER_UNBAN: "admin_user_unban",

  // System metrics (server-side only)
  MARKET_CREATE: "market_create",
  MARKET_APPROVE: "market_approve",
  MARKET_REJECT: "market_reject",

  // General
  PAGE_VIEW: "page_view",
} as const

export type AnalyticsEventName = typeof ANALYTICS_EVENTS[keyof typeof ANALYTICS_EVENTS]
