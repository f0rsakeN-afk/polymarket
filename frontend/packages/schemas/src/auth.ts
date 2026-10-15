/**
 * Auth validation rules shared by both front ends.
 *
 * ## Why these live in a package
 *
 * `apps/web` had them app-local, and the admin app then needed the same three
 * things - an email, a password, a six-digit code. Copying them would have been
 * the fourth place the "what is a valid email" question gets answered, and two
 * apps disagreeing about a form rule produces a form that passes validation in
 * one app and 422s in the other, which is a genuinely confusing bug to chase.
 *
 * A validation rule is not app policy. It is the contract the API enforces, and
 * the API enforces it once.
 *
 * ## The rules themselves
 *
 * Deliberately permissive where the server is permissive. A stricter client rule
 * is not free validation - it rejects input the API would have accepted, so an
 * operator with a longer-than-expected password is locked out of the admin app
 * while the storefront works fine. `MAX_PASSWORD_LENGTH` mirrors the API's own
 * `max_length=128` rather than guessing a product rule.
 */

import { z } from "zod"

/** Mirrors the API's `min_length=1`; a client cannot check password strength. */
export const MIN_PASSWORD_LENGTH = 1
/** Mirrors `StepUpRequest.password` / `LoginRequest.password` `max_length=128`. */
export const MAX_PASSWORD_LENGTH = 128

/** TOTP is always six digits - mirrors the API's `min_length=6, max_length=6`. */
export const totpCodeSchema = z
  .string()
  .regex(/^\d{6}$/, "Enter the 6-digit code from your authenticator")

export const emailSchema = z.email("Enter a valid email address")

export const passwordSchema = z
  .string()
  .min(MIN_PASSWORD_LENGTH, "Password is required")
  .max(MAX_PASSWORD_LENGTH, "That password is too long")

/**
 * An optional code, for the two-step case where the server decides whether one is
 * needed. `undefined` means "no code"; a code that is present but wrong must still
 * fail validation, or a six-box field would accept three characters.
 */
export const optionalTotpSchema = totpCodeSchema.optional()

/**
 * Admin sign-in.
 *
 * Note there is no `is_admin` rule here. Whether this account may use the admin
 * app is the *server's* answer, and a client that refused to submit for a
 * non-admin would be a client-side copy of an authorisation decision that lives in
 * exactly one place.
 */
export const adminLoginSchema = z.object({
  email: emailSchema,
  password: passwordSchema,
  /** Only sent once the server has said this account has 2FA. */
  totp_code: optionalTotpSchema,
})

export type AdminLoginInput = z.infer<typeof adminLoginSchema>

/**
 * Step-up credentials for a privileged action.
 *
 * `code` is optional *in the schema* and required *by the server* when the
 * account has 2FA. That asymmetry is the point: the client cannot be the thing
 * that decides whether a privileged action is adequately authenticated, because a
 * client that decided "no code needed" would let itself through.
 */
export const stepUpSchema = z.object({
  password: passwordSchema,
  code: optionalTotpSchema,
})

export type StepUpInput = z.infer<typeof stepUpSchema>