export interface Alert {
  id: string
  market_id: string
  outcome: "yes" | "no" | null
  condition: "above" | "below"
  trigger_price: number
  triggered: boolean
  triggered_at: string | null
}
