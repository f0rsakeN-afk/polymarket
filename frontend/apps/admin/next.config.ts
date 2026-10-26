import type { NextConfig } from "next"
import { config } from "@workspace/api-client/config"

/**
 * Admin app configuration.
 *
 * Separate from `apps/web` on purpose, and the CSP is where that separation
 * pays off first: this origin talks to the API and nothing else. No websocket,
 * no third-party media, no analytics. An operator tool that only reads and
 * writes the API should not be able to reach anything else, and the browser is
 * a better place to enforce that than a convention.
 */
function origin(raw: string): string {
  try {
    return new URL(raw).origin
  } catch {
    return raw
  }
}

const apiOrigin = origin(config.apiUrl)
const isDev = process.env.NODE_ENV !== "production"

const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  // API only. No `ws:` entry - nothing in the admin surface opens a socket.
  `connect-src 'self' ${apiOrigin}`,
  "font-src 'self' data:",
  "object-src 'none'",
  // An operator tool must not be embeddable: clickjacking an admin action is
  // the one clickjacking that matters.
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ")

const nextConfig: NextConfig = {
  transpilePackages: ["@workspace/ui", "@workspace/api-client"],
  output: "standalone",
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Permissions-Policy", value: "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()" },
        ],
      },
    ]
  },
}

export default nextConfig
