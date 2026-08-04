export interface Wallet {
  balance: number
  locked_balance: number
  available_balance: number
  currency: string
}

export interface Transaction {
  id: string
  type: "deposit" | "withdrawal" | "trade" | "refund"
  amount: number
  balance_after: number
  status: "pending" | "completed" | "failed"
  created_at: string
}

export interface TransactionsResponse {
  success: boolean
  data: {
    transactions: Transaction[]
    page: number
    page_size: number
  }
}
