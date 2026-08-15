export interface Wallet {
  balance: string
  locked_balance: string
  available_balance: string
  currency: string
}

export interface Transaction {
  id: string
  type: "deposit" | "withdrawal" | "trade" | "refund"
  amount: string
  balance_after: string
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
