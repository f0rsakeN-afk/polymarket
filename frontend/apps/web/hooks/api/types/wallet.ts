export interface Wallet {
  balance: number
  locked: number
  available: number
}

export interface Transaction {
  id: string
  type: "deposit" | "withdrawal" | "trade" | "refund"
  amount: number
  status: "pending" | "completed" | "failed"
  created_at: string
}

export interface TransactionsResponse {
  success: boolean
  data: Transaction[]
  page: number
  page_size: number
  has_more: boolean
}
