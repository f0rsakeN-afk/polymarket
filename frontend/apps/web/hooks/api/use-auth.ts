"use client"

import { useMutation, useQuery } from "@tanstack/react-query"
import {
  authApi,
  registerApi,
  magicLinkApi,
  passwordApi,
  accountApi,
  twoFactorApi,
} from "@/lib/api/auth"
import { queryKeys } from "@/lib/api/queryKeys"

// ─── Auth ─────────────────────────────────────────────────────────────────────

export function useCurrentUser() {
  return useQuery({
    queryKey: queryKeys.me(),
    queryFn: () => authApi.me().then((r) => r.data),
  })
}

export function useLogin() {
  return useMutation({
    mutationFn: ({ email, password, totpCode }: { email: string; password: string; totpCode?: string }) =>
      authApi.login(email, password, totpCode),
  })
}

export function useLogout() {
  return useMutation({
    mutationFn: authApi.logout,
  })
}

export function useLogoutAll() {
  return useMutation({
    mutationFn: authApi.logoutAll,
  })
}

export function useSessions() {
  return useQuery({
    queryKey: queryKeys.sessions(),
    queryFn: () => authApi.sessions().then((r) => r.data),
  })
}

export function useRevokeSession() {
  return useMutation({
    mutationFn: (sessionId: string) => authApi.revokeSession(sessionId),
  })
}

// ─── Registration ──────────────────────────────────────────────────────────────

export function useRegister() {
  return useMutation({
    mutationFn: ({
      email,
      username,
      password,
      referralCode,
    }: {
      email: string
      username: string
      password: string
      referralCode?: string
    }) => registerApi.register(email, username, password, referralCode),
  })
}

export function useVerifyEmail() {
  return useMutation({
    mutationFn: ({ email, code }: { email: string; code: string }) =>
      registerApi.verifyEmail(email, code),
  })
}

export function useResendVerification() {
  return useMutation({
    mutationFn: (email: string) => registerApi.resendVerification(email),
  })
}

// ─── Magic link ───────────────────────────────────────────────────────────────

export function useSendMagicLink() {
  return useMutation({
    mutationFn: (email: string) => magicLinkApi.sendCode(email),
  })
}

export function useVerifyMagicCode() {
  return useMutation({
    mutationFn: ({
      email,
      code,
      totpCode,
    }: {
      email: string
      code: string
      totpCode?: string
    }) => magicLinkApi.verifyCode(email, code, totpCode),
  })
}

export function useRequestMagicUrl() {
  return useMutation({
    mutationFn: (email: string) => magicLinkApi.requestUrl(email),
  })
}

export function useVerifyMagicUrl() {
  return useMutation({
    mutationFn: (token: string) => magicLinkApi.verifyUrl(token),
  })
}

// ─── Password ──────────────────────────────────────────────────────────────────

export function useForgotPassword() {
  return useMutation({
    mutationFn: (email: string) => passwordApi.forgotPassword(email),
  })
}

export function useResetPassword() {
  return useMutation({
    mutationFn: ({
      email,
      code,
      newPassword,
    }: {
      email: string
      code: string
      newPassword: string
    }) => passwordApi.resetPassword({ email, code, newPassword }),
  })
}

export function useSetPassword() {
  return useMutation({
    mutationFn: (password: string) => accountApi.setPassword(password),
  })
}

export function useChangePassword() {
  return useMutation({
    mutationFn: ({
      oldPassword,
      newPassword,
      totpCode,
    }: {
      oldPassword: string
      newPassword: string
      totpCode?: string
    }) => accountApi.changePassword({ old_password: oldPassword, new_password: newPassword, totp_code: totpCode }),
  })
}

// ─── 2FA ──────────────────────────────────────────────────────────────────────

export function useTwoFactorStatus() {
  return useQuery({
    queryKey: queryKeys.twoFactorStatus(),
    queryFn: () => twoFactorApi.status().then((r) => r.data),
  })
}

export function useTwoFactorSetup() {
  return useMutation({
    mutationFn: () => twoFactorApi.setup(),
  })
}

export function useTwoFactorEnable() {
  return useMutation({
    mutationFn: (code: string) => twoFactorApi.enable(code),
  })
}

export function useTwoFactorDisable() {
  return useMutation({
    mutationFn: ({ code, password }: { code: string; password: string }) =>
      twoFactorApi.disable(code, password),
  })
}
