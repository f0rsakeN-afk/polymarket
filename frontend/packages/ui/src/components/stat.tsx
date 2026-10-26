"use client"

import { Users, Ban, Shield, AlertCircle, CheckCircle2, Clock, Landmark, Scale, ScrollText, ShieldAlert, Store, TriangleAlert } from "lucide-react"

import { cn } from "@workspace/ui/lib/utils"

/**
 * Stat card for admin dashboards.
 *
 * Displays a single metric with an icon, label, value, and clickable link.
 * Tone colors provide immediate visual feedback on the metric's state.
 */
interface StatProps {
  /** Link destination (e.g "/users", "/markets") */
  href: string
  /** Lucide React icon component */
  icon: typeof Users
  /** Label displayed above the value */
  label: string
  /** The metric value (number, string, or null/undefined) */
  value: number | string | null | undefined
  /** Color tone: "default" | "success" | "warning" | "critical" */
  tone?: "default" | "success" | "warning" | "critical"
  /** Accessible hint text shown on hover/focus */
  hint: string
}

/**
 * Format a number with commas (e.g. "500,000").
 */
function formatNumber(value: number): string {
  return value.toLocaleString()
}

/**
 * Determine the tone based on the value.
 * - Critical: negative / zero / very low
 * - Warning: moderate / above threshold
 * - Default: healthy / normal
 */
function determineTone(tone: "default" | "success" | "warning" | "critical", value: number | string | null | undefined): "default" | "success" | "warning" | "critical" {
  if (tone !== "default") return tone
  if (value === null || value === undefined) return "critical"
  if (typeof value === "number") {
    if (value === 0) return "critical"
    if (value < 10) return "warning"
    return "default"
  }
  return "default"
}

function Stat({
  href,
  icon,
  label,
  value,
  tone: toneProp = "default",
  hint,
}: StatProps) {
  const tone = determineTone(toneProp, typeof value === "number" ? value : 0)

  return (
    <a
      href={href}
      className="group"
      aria-label={hint}
    >
      <Card tone={tone} className="h-full transition-colors group-hover:bg-accent/30">
        <CardContent className="px-5 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <icon
                className={cn(
                  "size-4",
                  tone === "critical" ? "text-critical" : tone === "warning" ? "text-warning" : tone === "success" ? "text-success" : "text-muted-foreground"
                )}
                aria-hidden
              />
              <span className="sr-only">{label}</span>
            </div>

            <span className="text-xs text-muted-foreground truncate max-w-xs">
              {label}
            </span>
          </div>

          {/* Value section */}
          {value === undefined ? (
            <div className="mt-2 flex h-8 items-center" role="status">
              <span className="sr-only">Loading {label}</span>
              <svg
                className="size-4 animate-spin opacity-50"
                viewBox="0 0 24 24"
                fill="currentColor"
              >
                <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.21L5 12.27l-1.18-6.88L2 9.27l-5-4.87L2 2z" />
              </svg>
            </div>
          ) : value === null ? (
            <>
              <p className="mt-1 text-2xl font-bold text-critical">—</p>
              <p className="text-xs text-muted-foreground">No data</p>
            </>
          ) : typeof value === "number" ? (
            <p className={cn(
              "mt-1 text-2xl font-bold",
              tone === "critical" ? "text-critical" : tone === "warning" ? "text-warning" : tone === "success" ? "text-success" : "text-primary-foreground"
            )}>
              {formatNumber(value)}
            </p>
          ) : (
            <p className="mt-1 text-lg font-medium">{value}</p>
          )}

          {/* Hint / description below value */}
          {hint && (
            <p className="mt-1 text-xs text-muted-foreground" title={hint}>
              {hint.substring(0, 40)}${hint.length > 40 ? "..." : ""}
            </p>
          )}
        </CardContent>
      </Card>
    </a>
  )
}

export { Stat }
