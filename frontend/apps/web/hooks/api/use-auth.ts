"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  authApi,
  registerApi,
  magicLinkApi,
  passwordApi,
  accountApi,
  twoFactorApi,
} from "@/lib/api/auth"
import { queryKeys } from "@/lib/api/queryKeys"
import { sileo } from "sileo"
import type { ApiError } from "@/lib/api/client"

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
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Login successful" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Login failed" })
    },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: authApi.logout,
    onSuccess: (res) => {
      qc.clear()
      sileo.success({ title: res.message ?? "Signed out" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Sign out failed" })
    },
  })
}

export function useLogoutAll() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: authApi.logoutAll,
    onSuccess: (res) => {
      qc.clear()
      sileo.success({ title: res.message ?? "All sessions revoked" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Failed to revoke sessions" })
    },
  })
}

export function useSessions() {
  return useQuery({
    queryKey: queryKeys.sessions(),
    queryFn: () => authApi.sessions().then((r) => r.data),
  })
}

export function useRevokeSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) => authApi.revokeSession(sessionId),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: queryKeys.sessions() })
      sileo.success({ title: res.message ?? "Session revoked" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Failed to revoke session" })
    },
  })
}

// ─── Registration ──────────────────────────────────────────────────────────────

export function useRegister() {
  const qc = useQueryClient()
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
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Account created — check your email to verify" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Registration failed" })
    },
  })
}

export function useVerifyEmail() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ email, code }: { email: string; code: string }) =>
      registerApi.verifyEmail(email, code),
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Email verified" })
      qc.invalidateQueries({ queryKey: queryKeys.me() })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Verification failed" })
    },
  })
}

export function useResendVerification() {
  return useMutation({
    mutationFn: (email: string) => registerApi.resendVerification(email),
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Verification email sent" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Failed to resend" })
    },
  })
}

// ─── Magic link ───────────────────────────────────────────────────────────────

export function useSendMagicLink() {
  return useMutation({
    mutationFn: (email: string) => magicLinkApi.sendCode(email),
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Login code sent" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Failed to send code" })
    },
  })
}

export function useVerifyMagicCode() {
  return useMutation({
    mutationFn: ({ email, code, totpCode }: { email: string; code: string; totpCode?: string }) =>
      magicLinkApi.verifyCode(email, code, totpCode),
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Login successful" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Verification failed" })
    },
  })
}

export function useRequestMagicUrl() {
  return useMutation({
    mutationFn: (email: string) => magicLinkApi.requestUrl(email),
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Login link sent" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Failed to send link" })
    },
  })
}

export function useVerifyMagicUrl() {
  return useMutation({
    mutationFn: (token: string) => magicLinkApi.verifyUrl(token),
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Login successful" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Verification failed" })
    },
  })
}

// ─── Password ──────────────────────────────────────────────────────────────────

export function useForgotPassword() {
  return useMutation({
    mutationFn: (email: string) => passwordApi.forgotPassword(email),
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Reset code sent" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Failed to send reset code" })
    },
  })
}

export function useResetPassword() {
  return useMutation({
    mutationFn: ({ email, code, newPassword }: { email: string; code: string; newPassword: string }) =>
      passwordApi.resetPassword({ email, code, newPassword }),
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Password reset successful" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Password reset failed" })
    },
  })
}

export function useSetPassword() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (password: string) => accountApi.setPassword(password),
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Password set successfully" })
      qc.invalidateQueries({ queryKey: queryKeys.me() })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Failed to set password" })
    },
  })
}

export function useChangePassword() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ oldPassword, newPassword, totpCode }: { oldPassword: string; newPassword: string; totpCode?: string }) =>
      accountApi.changePassword({ old_password: oldPassword, new_password: newPassword, totp_code: totpCode }),
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Password changed" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Failed to change password" })
    },
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
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "2FA setup ready" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Failed to setup 2FA" })
    },
  })
}

export function useTwoFactorEnable() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (code: string) => twoFactorApi.enable(code),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: queryKeys.me() })
      qc.invalidateQueries({ queryKey: queryKeys.twoFactorStatus() })
      sileo.success({ title: res.message ?? "2FA enabled" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Failed to enable 2FA" })
    },
  })
}

export function useTwoFactorDisable() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ code, password }: { code: string; password: string }) =>
      twoFactorApi.disable(code, password),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: queryKeys.me() })
      qc.invalidateQueries({ queryKey: queryKeys.twoFactorStatus() })
      sileo.success({ title: res.message ?? "2FA disabled" })
    },
    onError: (err) => {
      sileo.error({ title: (err as ApiError).message || "Failed to disable 2FA" })
    },
  })
}
