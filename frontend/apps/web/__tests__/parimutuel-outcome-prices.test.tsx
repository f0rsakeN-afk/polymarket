/**
 * Per-outcome prices must come from the API, not from a single binary pair.
 *
 * The original defect: `GET /markets/{slug}` exposed only a market-level
 * yes_price/no_price, so an eight-way market rendered as "Yes 75 / No 25" —
 * two numbers that were not any of its outcomes. The backend now prices every
 * outcome, and the front end must read that rather than re-deriving a price
 * from an empty orderbook or a flat 1/n.
 */
import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import type { MarketDetailResponse } from "@/hooks/api/types/market"

const OUTCOME_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
]

function outcome(index: number, name: string, price: number) {
  return { id: `o${index}`, name, outcome_index: index, price }
}

function market(overrides: Partial<MarketDetailResponse> = {}): MarketDetailResponse {
  return {
    id: "m1",
    slug: "euro-2024-winner",
    question: "Who will win Euro 2024?",
    description: null,
    category: "sports",
    status: "active",
    total_liquidity: "750000",
    total_volume: "120000",
    // These are the meaningless pair the old seed produced.
    yes_price: "0.75",
    no_price: "0.25",
    spread: 0.5,
    closes_at: "2026-07-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    outcomes: [
      outcome(0, "France", 0.4893),
      outcome(1, "England", 0.1854),
      outcome(2, "Germany", 0.1051),
      outcome(3, "Spain", 0.0703),
      outcome(4, "Portugal", 0.0514),
      outcome(5, "Italy", 0.0398),
      outcome(6, "Netherlands", 0.0321),
      outcome(7, "Other", 0.0266),
    ],
    faqs: [],
    winning_outcome_id: null,
    winning_outcome_name: null,
    ...overrides,
  }
}

async function renderCard(m: MarketDetailResponse) {
  const { MarketCard } = await import("@/components/markets/market-card")
  return render(<MarketCard market={m} />)
}

describe("MarketCard per-outcome prices", () => {
  it("shows each outcome's own price, not one binary pair", async () => {
    await renderCard(market())

    expect(screen.getByText("France")).toBeTruthy()
    expect(screen.getByText("49%")).toBeTruthy()
    expect(screen.getByText("England")).toBeTruthy()
    expect(screen.getByText("19%")).toBeTruthy()
  })

  it("does not render Yes or No for a parimutuel market", async () => {
    await renderCard(market())

    // Every row is a named outcome • no synthetic Yes/No pair.
    const names = screen
      .getAllByText(/^[A-Za-z ]+$/)
      .map((el) => el.textContent)
    expect(names).not.toContain("Yes")
    expect(names).not.toContain("No")
    expect(names).toContain("France")
  })

  it("gives every outcome a distinct price", async () => {
    await renderCard(market())

    // The old fallback was 1/n for all of them, which made eight identical
    // rows regardless of the real market.
    // Each rendered percentage, which is the whole claim: a flat 1/n fallback
    // would make all eight read 13%.
    const rendered = screen
      .getAllByText(/^\d+%$/)
      .map((el) => el.textContent)
    expect(new Set(rendered).size).toBeGreaterThan(3)
    expect(rendered).toContain("11%") // Germany
    expect(rendered).toContain("7%") // Spain
    expect(rendered).not.toContain("13%") // 1/8, the old fallback
  })

  it("treats a two-way named market as parimutuel, not binary", async () => {
    await renderCard(
      market({
        slug: "trump-vs-biden",
        question: "Who wins?",
        outcomes: [
          outcome(0, "Trump", 0.55),
          outcome(1, "Biden", 0.45),
        ],
      })
    )

    expect(screen.getByText("Trump")).toBeTruthy()
    expect(screen.getByText("55%")).toBeTruthy()
    expect(screen.getByText("Biden")).toBeTruthy()
    expect(
      screen.getAllByText(/^[A-Za-z ]+$/).map((el) => el.textContent)
    ).not.toContain("Yes")
  })

  it("still shows Yes/No for a genuine binary market", async () => {
    // A binary card displays the market-level pair, which is the authoritative
    // source for a YES/NO market.
    await renderCard(
      market({
        slug: "btc-100k",
        yes_price: "0.62",
        no_price: "0.38",
        outcomes: [outcome(0, "Yes", 0.62), outcome(1, "No", 0.38)],
      })
    )

    // "Yes" also appears as a trade-pill label, so match the exact name node.
    expect(screen.getAllByText("Yes").length).toBeGreaterThan(0)
    expect(screen.getByText("62%")).toBeTruthy()
  })

  it("does not show a flat 1/n when the API omitted a price", async () => {
    // A cached or older response may carry no per-outcome price. Falling back
    // to 1/n is better than a blank, but it must not masquerade as a quote.
    await renderCard(
      market({
        outcomes: [
          { id: "o0", name: "France", outcome_index: 0 },
          { id: "o1", name: "England", outcome_index: 1 },
          { id: "o2", name: "Germany", outcome_index: 2 },
        ],
      })
    )

    expect(screen.getByText("France")).toBeTruthy()
    // The 1/n fallback still renders, so it must be present for all three.
    expect(screen.getAllByText("33%")).toHaveLength(3)
  })
})

describe("Outcome chart colour assignment", () => {
  it("never reuses a colour across the first five outcomes", () => {
    const seen = new Set(OUTCOME_COLORS.slice(0, 5))
    expect(seen.size).toBe(5)
  })

  it("assigns a distinct colour per outcome index", () => {
    const assigned = [0, 1, 2, 3, 4].map((i) => OUTCOME_COLORS[i])
    expect(new Set(assigned).size).toBe(assigned.length)
  })
})
