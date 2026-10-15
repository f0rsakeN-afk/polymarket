/**
 * Validation for the privileged actions.
 *
 * Two rules carry their reasoning in the field itself, because both are places
 * where a client-side check can be right and still be the wrong thing to rely on.
 */

import { z } from "zod"

import {
  optionalTotpSchema,
  passwordSchema,
  totpCodeSchema,
} from "@workspace/schemas/auth"

/** Mirrors `AdjudicateDisputeRequest.ruling`. */
export const rulingSchema = z.enum(["upheld", "dismissed"], {
  message: "Choose uphold or dismiss",
})

export type Ruling = z.infer<typeof rulingSchema>

/**
 * The note on a ruling.
 *
 * Optional as a *string* and required as a *ruling*, because the two rulings are
 * not symmetric:
 *
 * - An **uphold** resolves the market and pays out. The evidence is in the dispute
 *   and the criterion is in the market; the trail records which ruling and who
 *   made it, and that is enough to reconstruct the decision.
 * - A **dismissal** closes someone's dispute with **no payout**. The next
 *   question - always - is "on what grounds", and if the note was optional in
 *   spirit then even a filled-in field becomes "Declined by a moderator".
 *
 * So the requirement is conditional. Enforcing a note on upholds would put a
 * pointless text box in front of the operator at the moment they are trying to
 * resolve a live market.
 */
export const rulingNoteSchema = z
  .string()
  .max(2000, "That note is too long") // mirrors the API's max_length=2000
  .optional()

/**
 * A dismissal must carry a reason. Separate from `rulingNoteSchema` so the rule
 * lives with the ruling that needs it rather than being re-implemented at the
 * call site.
 */
export function validateRuling(ruling: Ruling, note: string | undefined): string | null {
  if (ruling === "dismissed" && !note?.trim()) {
    return "A dismissal needs a reason. The proposer is not told anything else."
  }
  return null
}

/**
 * Step-up credentials, as sent to any privileged write.
 *
 * `code` is optional *in the schema* and required *by the server* when the
 * account has 2FA. That asymmetry is the point: the client cannot be the thing
 * that decides whether a privileged action is adequately authenticated, because a
 * client that decided "no code needed" would let itself through.
 */
export const stepUpSchema = z.object({
  password: passwordSchema,
  /** Omitted unless the server asked for it — see `useStepUp`. */
  code: optionalTotpSchema,
})

/**
 * Step-up validation, given what the server has already told us.
 *
 * A factory rather than a constant because "is a code required" is not knowable
 * until the server answers. Two schemas would mean two rule sets to keep in step;
 * this keeps one, parameterised by a fact.
 */
export function stepUpSchemaFor(requiresCode: boolean) {
  return z.object({
    password: passwordSchema,
    code: requiresCode ? totpCodeSchema : optionalTotpSchema,
  })
}

/**
 * Client-side pre-flight for the fee distribution.
 *
 * The server is authoritative and this is a courtesy check: catching "there is
 * nothing to move" before a step-up prompt opens means the operator is not asked
 * to prove who they are in order to be told there was no work to do.
 */
export function canDistribute(pending: string | undefined): boolean {
  if (pending === undefined) return false
  // `pending` is an exact decimal string from `lib/decimal`. A sign check is
  // enough: zero moves nothing, and a negative balance is a discrepancy to
  // investigate rather than a sweep to perform.
  return !pending.startsWith("-") && pending !== "0" && Number(pending) !== 0
}