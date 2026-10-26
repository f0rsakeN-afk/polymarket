export function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffSec = Math.floor(Math.abs(now.getTime() - date.getTime()) / 1000)
  if (diffSec < 60) return "just now"
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay}d ago`
  return `${diffDay}d ago · ${date.toLocaleDateString()}`
}

export function formatCurrency(amount: number | string | null | undefined, decimals = 2): string {
  if (amount == null || amount === "") return "$0.00"
  const num = Number(amount)
  if (isNaN(num)) return "$0.00"
  return `$${num.toFixed(decimals)}`
}

export function formatLargeNumber(num: number | string | null | undefined, notation: "short" | "long" = "short"): string {
  if (num == null || num === "") return "0"
  const n = Number(num)
  if (isNaN(n)) return "0"
  
  if (notation === "short") {
    if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`
    if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
    if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`
    return n.toLocaleString()
  } else {
    // Long form
    if (n >= 1e9) return `${(n / 1e9).toFixed(1)} billion`
    if (n >= 1e6) return `${(n / 1e6).toFixed(1)} million`
    if (n >= 1e3) return `${(n / 1e3).toFixed(1)} thousand`
    return n.toLocaleString()
  }
}

export function formatVolume(volume: number | string | null | undefined): string {
  if (volume == null || volume === "") return "$0"
  const n = Number(volume)
  if (isNaN(n)) return "$0"
  // Format as dollars with appropriate suffix
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `$${(n / 1e3).toFixed(1)}K`
  return `$${n.toFixed(0)}`
}

export function formatLiquidity(liquidity: number | string | null | undefined): string {
  if (liquidity == null || liquidity === "") return "$0"
  const n = Number(liquidity)
  if (isNaN(n)) return "$0"
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `$${(n / 1e3).toFixed(1)}K`
  return `$${n.toFixed(0)}`
}