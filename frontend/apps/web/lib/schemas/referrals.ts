import { z } from "zod"

const moneyField = z.string() // Decimal serialized as string

export const referralSchema = z.object({
  id: z.string(),
  referred_id: z.string(),
  status: z.string(),
  reward_amount: moneyField,
  created_at: z.string(),
  completed_at: z.string().nullable(),
})

export const referralStatsSchema = z.object({
  referral_code: z.string(),
  total_referrals: z.number().int(),
  completed_referrals: z.number().int(),
  total_rewards_earned: moneyField,
  referrals: z.array(referralSchema).optional(),
})

export const referralCodeSchema = z.object({
  referral_code: z.string(),
})

export type Referral = z.infer<typeof referralSchema>
export type ReferralStats = z.infer<typeof referralStatsSchema>
export type ReferralCode = z.infer<typeof referralCodeSchema>
