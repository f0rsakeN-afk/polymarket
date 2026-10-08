import type { NextConfig } from "next"
import { config } from "./lib/config"

/** `https://api.example.com` / `ws://localhost:8000` → `https://api.example.com` */
function origin(raw: string): string {
  try {
    return new URL(raw).origin
  } catch {
    return raw
  }
}

const apiOrigin = origin(config.apiUrl)
const wsOrigin = origin(config.wsUrl)
const siteOrigin = origin(config.siteUrl)

const isDev = process.env.NODE_ENV !== "production"

/**
 * `connect-src` must list EVERY origin the browser talks to, or fetch/WS are
 * silently blocked in production (localhost-only values are a dev fallback).
 * `script-src 'unsafe-eval'` is dropped in production • Next does not need it
 * to hydrate; it is only ever needed by dev-mode tooling.
 */
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: https:",
  `connect-src 'self' ${apiOrigin} ${wsOrigin}`,
  `font-src 'self' data:`,
  "object-src 'none'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ")

const nextConfig: NextConfig = {
  transpilePackages: ["@workspace/ui"],
  output: "standalone",
  experimental: {
    // Barrel imports (lucide-react: 13 consumers, date-fns via ui) resolve
    // to per-module chunks instead of dragging whole packages in.
    optimizePackageImports: ["lucide-react", "date-fns"],
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-XSS-Protection", value: "1; mode=block" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()" },
          // Only meaningful over TLS • ignore in local dev.
          ...(siteOrigin.startsWith("https://")
            ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]
            : []),
        ],
      },
    ]
  },
}

export default nextConfig
