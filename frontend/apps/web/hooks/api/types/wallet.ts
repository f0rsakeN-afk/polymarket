/**
 * Types mirror GET /api/v1/wallet/ + GET /api/v1/wallet/transactions
 * (app/api/wallet.py, app/schemas/wallet.py).
 */

export interface Wallet {
  balance: string
  locked_balance: string
  available_balance: string
  currency: string
}

/**
 * Every `type` value the backend writes (grep: `Transaction(` in
 * app/services + app/api + app/workers). Extend when adding a new kind.
 */
export type TransactionType =
  | "deposit"
  | "withdrawal"
  | "trade_buy"
  | "trade_sell"
  | "split"
  | "merge"
  | "liquidity_add"
  | "liquidity_remove"
  | "liquidity_removal"
  | "settlement_win"
  | "settlement_loss"
  | "referral_reward"
  | "protocol_fee"

export type TransactionStatus = "pending" | "completed" | "failed"

export interface Transaction {
  id: string
  type: TransactionType
  /**
   * SIGNED decimal string: negative = money out, positive = money in.
   * Derive the display sign from this • never from `type`.
   */
  amount: string
  balance_after: string
  status: TransactionStatus
  /** null while the row is still pending */
  created_at: string | null
}

export interface TransactionsResponse {
  success: boolean
  data: {
    transactions: Transaction[]
    page: number
    page_size: number
  }
}
