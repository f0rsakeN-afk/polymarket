/**
 * Decimal arithmetic on decimal *strings*, for money.
 *
 * The API sends treasury figures as strings (`DecimalField`), which is the right
 * choice on the wire: `"0.1"` as a JSON number has already lost the ability to
 * represent itself exactly by the time a parser sees it. The obvious frontend
 * counterpart - `Number(collected) - Number(distributed)` - throws that away
 * again.
 *
 * `0.3 - 0.1` in binary floating point is `0.19999999999999998`. Displaying that
 * to an operator about to move real money is not a cosmetic bug; it is a figure
 * that cannot be reconciled with the ledger. So the subtraction below is exact:
 * scaled BigInt, no floating point anywhere.
 *
 * Kept deliberately minimal - this is not a decimal library, it is the one
 * operation this page needs, done correctly.
 */

interface Scaled {
  units: bigint
  scale: number
}

function parse(value: string): Scaled {
  const trimmed = String(value ?? "").trim()
  if (trimmed === "" || trimmed === ".") return { units: 0n, scale: 0 }

  const negative = trimmed.startsWith("-")
  const unsigned = negative ? trimmed.slice(1) : trimmed
  const [whole = "", fraction = ""] = unsigned.split(".")

  // A bare "." would otherwise produce an empty digit string, which BigInt
  // rejects with an unhelpful message about the *programmer*.
  const digits = `${whole || "0"}${fraction}`
  // Guard against anything that is not a number before BigInt gets it, so a
  // malformed server response renders as zero rather than crashing the page.
  if (!/^\d+$/.test(digits)) return { units: 0n, scale: 0 }

  const units = BigInt(digits) * (negative ? -1n : 1n)
  return { units, scale: fraction.length }
}

function rescale(value: Scaled, scale: number): Scaled {
  if (value.scale === scale) return value
  return { units: value.units * 10n ** BigInt(scale - value.scale), scale }
}

function format(value: Scaled): string {
  const negative = value.units < 0n
  const digits = (negative ? -value.units : value.units).toString().padStart(value.scale + 1, "0")
  if (value.scale === 0) return `${negative ? "-" : ""}${digits}`
  const whole = digits.slice(0, digits.length - value.scale)
  const fraction = digits.slice(digits.length - value.scale)
  return `${negative ? "-" : ""}${whole}.${fraction}`
}

/** Exact decimal subtraction. `subtract("0.3", "0.1") === "0.2"`. */
export function subtract(a: string, b: string): string {
  const left = parse(a)
  const right = parse(b)
  const scale = Math.max(left.scale, right.scale)
  return format({
    units: rescale(left, scale).units - rescale(right, scale).units,
    scale,
  })
}

/** Exact decimal addition, for the same reason. */
export function add(a: string, b: string): string {
  const left = parse(a)
  const right = parse(b)
  const scale = Math.max(left.scale, right.scale)
  return format({
    units: rescale(left, scale).units + rescale(right, scale).units,
    scale,
  })
}

/**
 * Group digits for display: `1234567.5` -> `1,234,567.5`.
 *
 * Applied to the string, never to a number - the whole point of the module.
 */
export function group(value: string): string {
  const trimmed = String(value ?? "").trim()
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(trimmed)
  if (!match) return trimmed
  const sign = match[1] ?? ""
  const whole = match[2] ?? ""
  const fraction = match[3]
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")
  return `${sign}${grouped}${fraction ? `.${fraction}` : ""}`
}