"use client";

import { useQuery } from "@tanstack/react-query";
import { authApi } from "@/lib/api/auth";

export function useCurrentUser() {
  return useQuery({
    queryKey: ["me"] as const,
    queryFn: () => authApi.me().then((r) => r.data),
    retry: false,
    staleTime: 60_000,
  });
}
