import { api } from "./client"
import type { MutationResponse } from "@/lib/api/client"

export interface MeResponse {
  id: string;
  email: string;
  username: string;
  is_email_verified: boolean;
  is_admin: boolean;
  is_2fa_enabled: boolean;
  referral_code?: string;
  is_2fa_pending?: boolean;
}

export interface Session {
  id: string;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
  last_active_at: string;
  expires_at: string;
}

// ─── Auth ──────────────────────────────────────────────────────────────────────

export const authApi = {
  me: () => api.get<{ success: boolean; data: MeResponse }>("/api/v1/auth/me"),

  login: (email: string, password: string, totpCode?: string) =>
    api.post<MutationResponse<{ id: string }>>("/api/v1/auth/login", {
      email,
      password,
      totp_code: totpCode,
    }),

  logout: () => api.post<MutationResponse<void>>("/api/v1/auth/logout"),

  logoutAll: () => api.post<MutationResponse<void>>("/api/v1/auth/logout-all"),

  sessions: () =>
    api.get<{ success: boolean; data: Session[] }>("/api/v1/auth/sessions"),

  revokeSession: (sessionId: string) =>
    api.delete<MutationResponse<void>>(`/api/v1/auth/sessions/${sessionId}`),

  refresh: () => api.post<MutationResponse<void>>("/api/v1/auth/refresh"),
};

// ─── Registration ──────────────────────────────────────────────────────────────

export const registerApi = {
  register: (email: string, username: string, password: string, referralCode?: string) =>
    api.post<MutationResponse<{ id: string; email: string; username: string }>>("/api/v1/auth/register", {
      email,
      username,
      password,
      referral_code: referralCode,
    }),

  verifyEmail: (email: string, code: string) =>
    api.post<MutationResponse<{ id: string; email: string; verified: boolean }>>("/api/v1/auth/verify-email", { email, code }),

  resendVerification: (email: string) =>
    api.post<MutationResponse<{ email_resent: boolean }>>(
      "/api/v1/auth/resend-verification",
      { email }
    ),
};

// ─── Magic link ────────────────────────────────────────────────────────────────

export const magicLinkApi = {
  sendCode: (email: string) =>
    api.post<MutationResponse<void>>("/api/v1/auth/magic-link", { email }),

  verifyCode: (email: string, code: string, totpCode?: string) =>
    api.post<MutationResponse<{ id: string; email: string; username: string }>>("/api/v1/auth/verify-magic", {
      email,
      code,
      totp_code: totpCode,
    }),

  requestUrl: (email: string) =>
    api.post<MutationResponse<void>>("/api/v1/auth/magic-link/url", { email }),

  verifyUrl: (token: string) =>
    api.post<MutationResponse<{ id: string; email: string; username: string }>>(
      "/api/v1/auth/verify-magic-url",
      { token }
    ),

  verifyUrl2fa: (partialToken: string, totpCode: string) =>
    api.post<MutationResponse<{ id: string; email: string; username: string }>>("/api/v1/auth/verify-magic-url-2fa", {
      partial_token: partialToken,
      totp_code: totpCode,
    }),

  verifyMagic2fa: (partialToken: string, totpCode: string) =>
    api.post<MutationResponse<{ id: string; email: string; username: string }>>("/api/v1/auth/verify-magic-2fa", {
      partial_token: partialToken,
      totp_code: totpCode,
    }),
};

// ─── Password reset ────────────────────────────────────────────────────────────

export const passwordApi = {
  forgotPassword: (email: string) =>
    api.post<MutationResponse<void>>(
      "/api/v1/auth/forgot-password",
      { email }
    ),

  resetPassword: ({ email, code, newPassword }: { email: string; code: string; newPassword: string }) =>
    api.post<MutationResponse<void>>("/api/v1/auth/reset-password", {
      email,
      code,
      new_password: newPassword,
    }),
}

// ─── Password (authenticated) ──────────────────────────────────────────────────

export const accountApi = {
  setPassword: (password: string) =>
    api.post<MutationResponse<{ status: string }>>("/api/v1/auth/set-password", { password }),

  changePassword: (params: { old_password: string; new_password: string; totp_code?: string }) =>
    api.post<MutationResponse<void>>("/api/v1/auth/change-password", params),
}

// ─── 2FA ──────────────────────────────────────────────────────────────────────

export interface TwoFactorSetup {
  uri: string;
}

export interface TwoFactorStatus {
  is_2fa_enabled: boolean;
  is_2fa_pending: boolean;
}

export const twoFactorApi = {
  status: () =>
    api.get<{ success: boolean; data: TwoFactorStatus }>("/api/v1/auth/2fa/status"),

  setup: () =>
    api.get<MutationResponse<TwoFactorSetup>>("/api/v1/auth/2fa/setup"),

  enable: (code: string) =>
    api.post<MutationResponse<void>>("/api/v1/auth/2fa/enable", { code }),

  disable: (code: string, password: string) =>
    api.post<MutationResponse<void>>("/api/v1/auth/2fa/disable", {
      code,
      password,
    }),
};
