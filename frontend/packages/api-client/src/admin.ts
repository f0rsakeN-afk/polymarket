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
  /** Why the account was deactivated. Null unless it is banned. */
  ban_reason: string | null
  /** When it was deactivated. Null unless it is banned. */
  banned_at: string | null
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
  closes_at: string
  category: string | null
  subcategory: string | null
  /** Who submitted it. Null for a system-created market. */
  created_by_email: string | null
  description: string | null
  /** How the market resolves, when the submitter supplied it. */
  resolution_criteria: string | null
  /** Why an admin declined the submission. Null unless it was rejected. */
  rejection_reason: string | null
  /** When it was declined. Null unless it was rejected. */
  rejected_at: string | null
  total_volume: string
  total_liquidity: string
  num_trades: number
  /**
   * How many legs this market has.
   *
   * Not decoration: two means binary, anything more means parimutuel, and every
   * price on it is read differently. It is the first thing an operator checks when
   * a market's numbers look wrong.
   */
  outcome_count: number
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

/** One movement in and out of the treasury. */
export interface TreasuryLogRow {
  id: string
  /** fee_collected | distribution */
  event: string
  amount: string
  reference_type: string | null
  reference_id: string | null
  created_at: string
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

/**
 * One active session.
 *
 * `is_current` rather than a client-side guess from the user agent: the server
 * knows which `sid` issued the token in hand, and an operator looking at a list of
 * sessions cannot tell which one they are on by reading a user-agent string.
 */
export interface AdminSession {
  id: string
  ip_address: string | null
  user_agent: string | null
  created_at: string
  last_active_at: string
  expires_at: string
  is_current: boolean
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
  /**
   * `status` and `sort` are not conveniences. "Show me the banned accounts" is
   * the first lookup during an incident, and without a filter it means paging
   * the whole list hoping the row you need is on the page you land on.
   */
  users: (
    params: {
      page?: number
      pageSize?: number
      search?: string
      status?: "all" | "active" | "banned" | "admins" | "unverified"
      sort?: "newest" | "oldest" | "email"
    } = {}
  ) =>
    api.get<Page<AdminUserRow>>(
      `/api/v1/admin/users${qs({
        page: params.page ?? 1,
        page_size: params.pageSize ?? 20,
        search: params.search,
        status: params.status,
        sort: params.sort,
      })}`
    ),

  user: (userId: string, include?: string[]) =>
    api.get<NormalizedResponse<AdminUserDetail>>(
      `/api/v1/admin/users/${userId}${qs({ include: include?.join(",") })}`
    ),

  /**
   * Ban a user. `reason` is required and is shown to them at sign-in.
   *
   * Not optional in the type, deliberately: a reason is the difference between a
   * decision a user can appeal and one they can only guess at, and making it
   * optional in the client is how it quietly becomes optional in practice.
   */
  ban: (userId: string, body: { reason: string; note?: string }) =>
    api.patch<NormalizedResponse<BanResult>>(`/api/v1/admin/users/${userId}/ban`, body),

  unban: (userId: string, body?: { note?: string }) =>
    api.patch<NormalizedResponse<{ status: string; user_id: string }>>(
      `/api/v1/admin/users/${userId}/unban`,
      // A `PATCH` with no body and no content type: sending `{}` would be fine,
      // but omitting it keeps the request identical to the one a curl would make.
      body ? body : undefined
    ),

  /**
   * The whole catalogue, admin's view of it.
   *
   * `status` is optional and omitting it is the point: it returns every market
   * including the three states the public catalogue hides. An operator asking
   * "is anything broken" is not asking about one status, and the previous
   * signature made `status` required - so there was no way to see all of them.
   *
   * `q` matches the question, the slug, and the submitter's email or username.
   * The submitter is most often how a moderator is looking for a market, from a
   * support ticket, and matching only the question text misses that entirely.
   */
  markets: (
    params: {
      status?: string
      q?: string
      sort?: "newest" | "oldest" | "volume" | "liquidity" | "closing_soon" | "closing_late"
      page?: number
      pageSize?: number
    } = {}
  ) =>
    api.get<Page<AdminMarketRow>>(
      `/api/v1/admin/markets${qs({
        status: params.status,
        q: params.q,
        sort: params.sort,
        page: params.page ?? 1,
        page_size: params.pageSize ?? 50,
      })}`
    ),

  approveMarket: (marketId: string) =>
    api.post<NormalizedResponse<{ status: string }>>(
      `/api/v1/admin/markets/${marketId}/approve`
    ),

  /**
   * Reject a market submission. `reason` is required and is shown to the author.
   *
   * It used to be optional with `reason || "Declined by a moderator"` as the
   * fallback — so every rejection made through this UI was recorded with that
   * sentence instead of anything an operator wrote, which is worse than no
   * reason at all: it looks like a reason and is none. The author of a declined
   * market needs to know whether the problem was the wording, the category or
   * the resolution criteria, and "Declined by a moderator" answers none of them.
   */
  rejectMarket: (marketId: string, body: { reason: string; note?: string }) =>
    api.post<NormalizedResponse<{ status: string; rejection_reason: string }>>(
      `/api/v1/admin/markets/${marketId}/reject`,
      body
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

  /**
   * The movement history: every collection and every withdrawal, newest first.
   *
   * The page this backs had no way to answer "where did this balance come from",
   * which is the first question anyone asks about money. The endpoint existed
   * and was never called.
   */
  treasuryLogs: (params: { page?: number; pageSize?: number; event?: string } = {}) =>
    api.get<Page<TreasuryLogRow>>(
      `/api/v1/treasury/logs${qs({
        page: params.page ?? 1,
        page_size: params.pageSize ?? 20,
        event: params.event,
      })}`
    ),

  /**
   * Withdraw a specific amount to the treasury.
   *
   * Distinct from `distributeProtocolFees`, which sweeps whatever the fee
   * balance happens to be. This one moves a stated number, so it takes an amount
   * as well as step-up credentials — and it is the operation that should feel
   * deliberate, because the amount is chosen rather than derived.
   */
  treasuryDistribute: (body: { amount: number; password: string; code?: string }) =>
    api.post<NormalizedResponse<{ status: string; amount: string }>>(
      "/api/v1/treasury/distribute?amount=" + encodeURIComponent(String(body.amount)),
      { password: body.password, ...(body.code ? { totp_code: body.code } : {}) }
    ),

  distributeProtocolFees: (body: StepUpBody) =>
    api.post<NormalizedResponse<FeeDistributionResult>>(
      "/api/v1/admin/distribute-protocol-fees",
      body
    ),

  // ── The operator's own session and factor ────────────────────────────────
  //
  // Present in the admin app because "which other sessions does this account
  // have" is the first question a security-conscious operator asks, and answering
  // it somewhere else means an extra tab and a context switch to the storefront.

  sessions: () => api.get<NormalizedResponse<AdminSession[]>>("/api/v1/auth/sessions"),

  revokeSession: (sessionId: string) =>
    api.delete<NormalizedResponse<{ revoked: string }>>(`/api/v1/auth/sessions/${sessionId}`),

  twoFactorStatus: () =>
    api.get<NormalizedResponse<{ is_2fa_enabled: boolean; is_2fa_pending: boolean }>>(
      "/api/v1/auth/2fa/status"
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