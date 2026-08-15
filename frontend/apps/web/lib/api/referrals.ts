import { z } from "zod"
import { api } from "./client"
import { referralCodeSchema, referralStatsSchema } from "@/lib/schemas/referrals"

export function getReferralCode() {
  return api.get<{ success: boolean; data: z.infer<typeof referralCodeSchema> }>("/api/v1/referrals/code")
}

export function getReferralStats() {
  return api.get<{ success: boolean; data: z.infer<typeof referralStatsSchema> }>("/api/v1/referrals/stats")
}
