import { boolean, literal, maxValue, minValue, number, object, optional, pipe, string, union } from "valibot"

const sideLiteral = (v: "buy" | "sell") => pipe(literal(v))

export const PlaceOrderSchema = object({
  market_id: string(),
  outcome: optional(string(), "yes"),
  side: optional(union([sideLiteral("buy"), sideLiteral("sell")]), "buy"),
  order_type: optional(
    union([literal("market"), literal("limit"), literal("fill_or_kill")]),
    "market"
  ),
  amount: pipe(number(), minValue(0.01)),
  price: optional(pipe(number(), minValue(0.001), maxValue(0.999))),
  post_only: optional(boolean(), false),
  expires_at: optional(string()),
  client_order_id: optional(string()),
})

export const DepositSchema = object({
  amount: pipe(number(), minValue(1)),
})

export const WithdrawSchema = object({
  amount: pipe(number(), minValue(1)),
})

export type PlaceOrderInput = {
  market_id: string
  outcome: string
  side: "buy" | "sell"
  order_type: "market" | "limit" | "fill_or_kill"
  amount: number
  price?: number
  post_only: boolean
  expires_at?: string
  client_order_id?: string
}
