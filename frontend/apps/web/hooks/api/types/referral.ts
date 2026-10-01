/**
 * Canonical referral types are derived from the zod schemas in
 * `schemas/referrals.ts` (see `lib/api/referrals.ts`). Re-exported here so
 * this path cannot drift from the actual API contract.
 */
export type { ReferralCode, ReferralStats } from "@/lib/schemas/referrals";
