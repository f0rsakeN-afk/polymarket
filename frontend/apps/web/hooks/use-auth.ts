"use client";

import { useQuery } from "@tanstack/react-query";
import { authApi } from "@/lib/api/auth";

export function useCurrentUser() {
  return useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: () => authApi.me().then((r) => r.data),
    retry: false,
    staleTime: 60_000,
    // Skip the network call entirely when there's no auth cookie — the
    // proxy already lets public pages through without redirecting, so
    // there's no server-side identity to hydrate on the client for public
    // routes. Auth-dependent pages (portfolio, orders, etc.) call this hook
    // and get the cached result or fire the query normally.
    enabled: hasAuthCookie(),
  });
}

const ME_QUERY_KEY = ["me"] as const

function hasAuthCookie(): boolean {
  if (typeof document === "undefined") return true; // SSR: don't block, let it resolve
  return document.cookie.split("; ").some((c) => c.startsWith("access_token="));
}
