import { z } from "zod"

export const emailSchema = z.object({
  email: z.email("Please enter a valid email"),
})

export const passwordSchema = z.object({
  email: z.email(),
  password: z.string().min(1, "Password is required"),
  totp_code: z.string().optional(),
})

export const loginSchema = z.object({
  email: z.email("Please enter a valid email"),
  password: z.string().min(1, "Password is required"),
  totp_code: z
    .string()
    .regex(/^\d{6}$/)
    .optional(),
})

export const registerSchema = z.object({
  email: z.email("Please enter a valid email"),
  username: z
    .string()
    .min(3, "Username must be at least 3 characters")
    .max(30, "Username must be at most 30 characters")
    .regex(/^[a-zA-Z0-9_-]+$/, "Only letters, numbers, _ and - allowed"),
  password: z
    .string()
    .min(8, "Password must be at least 8 characters")
    .max(128, "Password must be at most 128 characters"),
  referral_code: z.string().optional(),
})

export const verifyEmailSchema = z.object({
  email: z.email(),
  code: z
    .string()
    .length(6, "Code must be 6 digits")
    .regex(/^\d{6}$/, "Code must be 6 digits"),
})

export const resendVerificationSchema = z.object({
  email: z.string().email(),
})

export const setPasswordSchema = z.object({
  password: z.string().min(8).max(128),
})

export const changePasswordSchema = z.object({
  old_password: z.string().min(1),
  new_password: z.string().min(8).max(128),
  totp_code: z
    .string()
    .regex(/^\d{6}$/)
    .optional(),
})

export const forgotPasswordSchema = z.object({
  email: z.email("Please enter a valid email"),
})

export const resetPasswordSchema = z
  .object({
    email: z.email(),
    code: z
      .string()
      .length(6, "Code must be 6 digits")
      .regex(/^\d{6}$/, "Code must be 6 digits"),
    newPassword: z
      .string()
      .min(8, "Password must be at least 8 characters")
      .max(128),
    confirmPassword: z.string(),
  })
  .refine((d) => d.newPassword === d.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  })

export const magicLinkRequestSchema = z.object({
  email: z.email("Please enter a valid email"),
})

export const verifyMagicSchema = z.object({
  email: z.email("Please enter a valid email"),
  code: z
    .string()
    .length(6, "Code must be 6 digits")
    .regex(/^\d{6}$/, "Code must be 6 digits"),
  totp_code: z
    .string()
    .regex(/^\d{6}$/)
    .optional(),
})

export const verifyMagicUrlSchema = z.object({
  token: z.string(),
})

export const magicUrl2FASchema = z.object({
  partial_token: z.string().min(1),
  totp_code: z
    .string()
    .length(6)
    .regex(/^\d{6}$/),
})

export const refreshSchema = z.object({})

export const totpCodeSchema = z.object({
  code: z
    .string()
    .length(6, "Code must be 6 digits")
    .regex(/^\d{6}$/, "Code must be 6 digits"),
})

export const totpDisableSchema = z.object({
  code: z
    .string()
    .length(6, "Code must be 6 digits")
    .regex(/^\d{6}$/, "Code must be 6 digits"),
  password: z.string().min(1),
})

export const twoFactorSetupResponseSchema = z.object({
  uri: z.string(),
})

export const twoFactorStatusResponseSchema = z.object({
  is_2fa_enabled: z.boolean(),
  is_2fa_pending: z.boolean(),
})

export type LoginInput = z.infer<typeof loginSchema>
export type RegisterInput = z.infer<typeof registerSchema>
export type VerifyEmailInput = z.infer<typeof verifyEmailSchema>
export type ResendVerificationInput = z.infer<typeof resendVerificationSchema>
export type SetPasswordInput = z.infer<typeof setPasswordSchema>
export type ChangePasswordInput = z.infer<typeof changePasswordSchema>
export type ForgotPasswordInput = z.infer<typeof forgotPasswordSchema>
export type ResetPasswordInput = z.infer<typeof resetPasswordSchema>
export type MagicLinkRequestInput = z.infer<typeof magicLinkRequestSchema>
export type VerifyMagicInput = z.infer<typeof verifyMagicSchema>
export type VerifyMagicUrlInput = z.infer<typeof verifyMagicUrlSchema>
export type MagicUrl2FAInput = z.infer<typeof magicUrl2FASchema>
export type TOTPCodeInput = z.infer<typeof totpCodeSchema>
export type TOTPDisableInput = z.infer<typeof totpDisableSchema>
