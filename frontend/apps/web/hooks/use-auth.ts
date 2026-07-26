"use client"

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api/client"

export function useCurrentUser() {
  return useQuery({
    queryKey: ["me"] as const,
    queryFn: () => api.get<{ success: boolean; data: { id: string; username: string; email: string; is_admin: boolean } }>("/api/v1/auth/me").then((r) => r.data),
    retry: false,
  })
}
