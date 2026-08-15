import { z } from "zod"

export const referralSchema = z.object({
  id: z.string(),
  referred_id: z.string(),
  status: z.string(),
  reward_amount: z.number(),
  created_at: z.string(),
  completed_at: z.string().nullable(),
})

export const referralStatsSchema = z.object({
  referral_code: z.string(),
  total_referrals: z.number(),
  completed_referrals: z.number(),
  total_rewards_earned: z.number(),
  referrals: z.array(referralSchema).optional(),
})

export const referralCodeSchema = z.object({
  referral_code: z.string(),
})

export type Referral = z.infer<typeof referralSchema>
export type ReferralStats = z.infer<typeof referralStatsSchema>
export type ReferralCode = z.infer<typeof referralCodeSchema>
