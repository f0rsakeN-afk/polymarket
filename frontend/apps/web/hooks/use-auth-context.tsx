"use client"

import React, { createContext, useContext, useCallback } from "react"
import { useRouter } from "next/navigation"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { authApi, MeResponse } from "@/lib/api/auth"
import { queryKeys } from "@/lib/api/queryKeys"
import { useCurrentUser } from "./use-auth"

interface AuthContextValue {
  user: MeResponse | null | undefined
  isLoading: boolean
  isAuthenticated: boolean
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient()
  const router = useRouter()
  const { data: user, isLoading } = useCurrentUser()

  const logoutMutation = useMutation({
    mutationFn: () => authApi.logout(),
    onSuccess: () => {
      // Remove all auth-related queries; keep market/position/order caches intact
      queryClient.removeQueries({ queryKey: queryKeys.me() })
      queryClient.removeQueries({ queryKey: queryKeys.positions() })
      queryClient.removeQueries({ queryKey: queryKeys.orders() })
      queryClient.removeQueries({ queryKey: queryKeys.notifications() })
      router.push("/")
    },
    onError: () => {
      // Even if server logout fails, clear local auth state
      queryClient.removeQueries({ queryKey: queryKeys.me() })
      queryClient.removeQueries({ queryKey: queryKeys.positions() })
      queryClient.removeQueries({ queryKey: queryKeys.orders() })
      queryClient.removeQueries({ queryKey: queryKeys.notifications() })
      router.push("/")
    },
  })

  const logout = useCallback(async () => {
    await logoutMutation.mutateAsync()
  }, [logoutMutation])

  return (
    <AuthContext.Provider
      value={{
        user: user ?? null,
        isLoading,
        isAuthenticated: !!user,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>")
  return ctx
}
