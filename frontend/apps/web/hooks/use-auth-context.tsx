"use client"

import React, { createContext, useContext, useCallback } from "react"
import { useRouter } from "next/navigation"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { authApi, MeResponse } from "@/lib/api/auth"
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
      queryClient.removeQueries({ queryKey: ["me"] })
      queryClient.removeQueries({ queryKey: ["positions"] })
      queryClient.removeQueries({ queryKey: ["orders"] })
      queryClient.removeQueries({ queryKey: ["notifications"] })
      router.push("/")
    },
    onError: () => {
      // Even if server logout fails, clear local auth state
      queryClient.removeQueries({ queryKey: ["me"] })
      queryClient.removeQueries({ queryKey: ["positions"] })
      queryClient.removeQueries({ queryKey: ["orders"] })
      queryClient.removeQueries({ queryKey: ["notifications"] })
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
