import { api, apiErrorCode } from "./client"
import type { NormalizedResponse } from "./client"

/**
 * The admin surface.
 *
 * Types mirror `backend/app/api/admin.py`. Money arrives as a string for the same
 * reason it does in `account.ts`: the backend serialises `Decimal` as a string
 * because `float()` rounds it, and the person reading an admin balance screen is
 * precisely the one who would reconcile it against a ledger.
 */

/** Shape A from the normaliser: `PaginatedResponse` carries page/total alongside `data`. */
type Page<T> = NormalizedResponse<T[]> & {
  page: number
  page_size: number
  has_more: boolean
  total: number
}

export interface AdminUserRow {
  id: string
  email: string
  username: string
  is_active: boolean
  is_admin: boolean
  is_email_verified: boolean
  is_2fa_enabled: boolean
  created_at: string
}

/** GET /admin/users/{id} → data. */
export interface AdminUserDetail {
  id: string
  email: string
  username: string
  is_active: boolean
  is_admin: boolean
  is_email_verified: boolean
  is_2fa_enabled: boolean
  is_2fa_pending: boolean
  referral_code: string | null
  created_at: string
  is_deleted: boolean
  wallet: {
    balance: string
    locked_balance: string
    currency: string
  } | null
  counts: {
    orders: number
    open_orders: number
    positions: number
    trades: number
    transactions: number
    disputes: number
  }
  /**
   * Computed server-side rather than left for this layer to derive.
   *
   * The point is that these are the conditions that become a support ticket: a
   * user holding funds they cannot reach is a problem *before* it is a dispute,
   * and nothing else on the screen says so.
   */
  findings: string[]
  trades?: Record<string, unknown>[]
  orders?: Record<string, unknown>[]
  positions?: Record<string, unknown>[]
  transactions?: Record<string, unknown>[]
}

export interface AdminActionRow {
  id: string
  actor_id: string | null
  actor_email: string | null
  action: string
  target_type: string | null
  target_id: string | null
  summary: string | null
  payload: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
  success: string
  failure_reason: string | null
}

export interface AdminAuditEventRow {
  id: string
  user_id: string | null
  event: string
  ip_address: string | null
  user_agent: string | null
  success: string
  failure_reason: string | null
  created_at: string
}

export interface AdminMarketRow {
  id: string
  slug: string
  question: string
  status: string
  created_at: string
}

export interface BanResult {
  status: string
  user_id: string
  cancelled_order_ids: string[]
}

/**
 * A dispute as it appears in the moderation queue.
 *
 * `market_question` and `evidence` travel in the same row on purpose. A ruling
 * taken from the summary line alone is a coin toss with a payout attached, and
 * making the moderator open the market in another tab means the decision gets
 * made from memory.
 */
export interface AdminDisputeRow {
  id: string
  market_id: string
  market_slug: string
  market_question: string
  market_status: string
  proposed_outcome_id: string | null
  user_id: string
  proposer_username: string | null
  evidence: string | null
  evidence_url: string | null
  status: string
  created_at: string
}

export interface AdminDisputeDetail extends AdminDisputeRow {
  /** The criterion an upheld ruling is judged against. */
  resolution_criteria: string | null
  resolution_source: string | null
  proposed_outcome_name: string | null
}

export interface AdjudicateResult {
  dispute_id: string
  ruling: string
  /** `null` when the ruling did not resolve the market - not every uphold ends here. */
  market_status: string | null
}

export interface TreasurySummary {
  balance: string
  total_fees_collected: string
  total_fees_distributed: string
}

export interface FeeDistributionResult {
  total_distributed: string
  markets_processed: number
}

/** Step-up credentials, attached to a privileged write. */
export interface StepUpBody {
  password: string
  /** Omitted unless the server asks for it - see `useStepUp`. */
  code?: string
}

/**
 * Query strings built by hand, one key at a time.
 *
 * Absent filters are *omitted* rather than sent empty. Beyond producing URLs
 * nobody wants to read, an empty `search=` is a different query key from no
 * `search` at all, so react-query would hold two entries for what is the same
 * request and refetch both.
 */
function qs(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value))
  }
  const query = search.toString()
  return query ? `?${query}` : ""
}

export const adminApi = {
  users: (params: { page?: number; pageSize?: number; search?: string } = {}) =>
    api.get<Page<AdminUserRow>>(
      `/api/v1/admin/users${qs({
        page: params.page ?? 1,
        page_size: params.pageSize ?? 20,
        search: params.search,
      })}`
    ),

  user: (userId: string, include?: string[]) =>
    api.get<NormalizedResponse<AdminUserDetail>>(
      `/api/v1/admin/users/${userId}${qs({ include: include?.join(",") })}`
    ),

  ban: (userId: string) =>
    api.patch<NormalizedResponse<BanResult>>(`/api/v1/admin/users/${userId}/ban`),

  unban: (userId: string) =>
    api.patch<NormalizedResponse<{ status: string; user_id: string }>>(
      `/api/v1/admin/users/${userId}/unban`
    ),

  markets: (status: string, page = 1, pageSize = 20) =>
    api.get<Page<AdminMarketRow>>(
      `/api/v1/admin/markets${qs({ status, page, page_size: pageSize })}`
    ),

  approveMarket: (marketId: string) =>
    api.post<NormalizedResponse<{ status: string }>>(
      `/api/v1/admin/markets/${marketId}/approve`
    ),

  rejectMarket: (marketId: string, reason?: string) =>
    api.post<NormalizedResponse<{ status: string }>>(
      `/api/v1/admin/markets/${marketId}/reject`,
      { reason: reason || "Declined by a moderator" }
    ),

  actions: (
    params: {
      page?: number
      pageSize?: number
      action?: string
      targetType?: string
      targetId?: string
      success?: "success" | "failure"
    } = {}
  ) =>
    api.get<Page<AdminActionRow>>(
      `/api/v1/admin/admin-actions${qs({
        page: params.page ?? 1,
        page_size: params.pageSize ?? 50,
        action: params.action,
        target_type: params.targetType,
        target_id: params.targetId,
        success: params.success,
      })}`
    ),

  auditEvents: (
    params: { page?: number; pageSize?: number; event?: string; success?: string } = {}
  ) =>
    api.get<Page<AdminAuditEventRow>>(
      `/api/v1/admin/audit-events${qs({
        page: params.page ?? 1,
        page_size: params.pageSize ?? 50,
        event: params.event,
        success: params.success,
      })}`
    ),

  /**
   * The dispute queue. Defaults to open, oldest first.
   *
   * `status: "all"` because "why did that one get rejected?" is a real question
   * with no other way to answer it, and a queue that only shows pending work
   * cannot answer it.
   */
  disputes: (params: { status?: string; page?: number; pageSize?: number } = {}) =>
    api.get<Page<AdminDisputeRow>>(
      `/api/v1/admin/disputes${qs({
        status: params.status ?? "open",
        page: params.page ?? 1,
        page_size: params.pageSize ?? 25,
      })}`
    ),

  dispute: (disputeId: string) =>
    api.get<NormalizedResponse<AdminDisputeDetail>>(`/api/v1/admin/disputes/${disputeId}`),

  /**
   * Rule on a dispute.
   *
   * Not under `/admin` because it is not an administrative setting - it is the
   * market's own resolution path, and an admin reaching it through the admin
   * namespace would suggest the two are interchangeable.
   */
  adjudicate: (
    disputeId: string,
    body: { ruling: "upheld" | "dismissed"; admin_note?: string } & StepUpBody
  ) =>
    api.post<NormalizedResponse<AdjudicateResult>>(
      `/api/v1/disputes/${disputeId}/adjudicate`,
      body
    ),

  treasury: () =>
    api.get<NormalizedResponse<TreasurySummary>>("/api/v1/treasury"),

  distributeProtocolFees: (body: StepUpBody) =>
    api.post<NormalizedResponse<FeeDistributionResult>>(
      "/api/v1/admin/distribute-protocol-fees",
      body
    ),
}

/** The step-up error codes an admin UI has to tell apart. */
export const STEP_UP_CODES = [
  "STEP_UP_PASSWORD_INVALID",
  "STEP_UP_2FA_REQUIRED",
  "STEP_UP_2FA_INVALID",
] as const

export function isStepUpError(err: unknown): boolean {
  const code = apiErrorCode(err)
  return typeof code === "string" && (STEP_UP_CODES as readonly string[]).includes(code)
}