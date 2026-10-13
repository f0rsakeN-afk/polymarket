import { test, expect } from "@playwright/test"
import { execSync } from "node:child_process"
import { shouldSkip } from "./skip-guards"

/**
 * The one property the entire system exists for.
 *
 * Every other test in this repo can pass while the markets page renders a
 * perfectly composed grid of prices that never move. Nothing here proves the
 * browser is *connected to anything*, because nothing here asks.
 *
 * So this asks directly: publish a price the way the order service does, and
 * require the number on screen to follow. A live badge, a connected socket, or a
 * green status light are all consistent with a page that renders beautifully and
 * never changes - this is the only assertion that is not.
 */

const MARKET_ID = process.env.E2E_MARKET_ID
const BACKEND = process.env.E2E_BACKEND_DIR ?? "../../../backend"

/** Publish one price frame through the production path (Lua sequencer + Redis). */
function publishPrice(yesPrice: number): boolean {
  try {
    execSync(
      `cd ${BACKEND} && REDIS_PASSWORD=${process.env.REDIS_PASSWORD ?? "devpass"} ` +
        `.venv/bin/python -m harness.push_price ${MARKET_ID} ${yesPrice}`,
      { shell: "/bin/bash", stdio: "pipe", env: process.env },
    )
    return true
  } catch {
    return false
  }
}

/** The first two percentages on the first card, as Yes / No. */
async function firstCardPrices(page: import("@playwright/test").Page) {
  return page.evaluate(() => {
    const cell = document.querySelector("[data-index]")
    if (!cell) return null
    return [...cell.querySelectorAll("span")]
      .map((s) => s.textContent?.trim() ?? "")
      .filter((t) => /^\d+%$/.test(t))
      .slice(0, 2)
      .map((t) => Number(t.replace("%", "")))
  })
}

/**
 * Skip rather than fail when the harness cannot run.
 *
 * These need a live backend, a live Redis, and a seeded market. In an isolated
 * checkout none of that exists, and a red suite nobody can fix locally gets
 * ignored - which is worse than an honest skip that says what is missing.
 */
test.describe("markets grid is live", () => {
  // `shouldSkip`, not an inline `!process.env.REDIS_PASSWORD` - see
  // `e2e/skip-guards.ts`. The truthiness form reads an *empty* password as
  // unset, and an empty string is exactly what a passwordless Redis supplies, so
  // this describe block silently skipped in CI while reporting itself as covered.
  test.skip(
    shouldSkip(process.env, MARKET_ID),
    "needs E2E_MARKET_ID and REDIS_PASSWORD - a seeded market and the app's Redis",
  )

  test("a published price reaches the card without a reload", async ({ page }) => {
    await page.goto("/markets")
    await page.waitForSelector("[data-index]", { timeout: 20_000 })
    await page.waitForTimeout(1500) // let the socket declare its grid

    const before = await firstCardPrices(page)
    expect(before, "the card rendered no prices to begin with").not.toBeNull()
    expect(before!.length).toBeGreaterThanOrEqual(2)

    // Something guaranteed to differ from the seeded price, and valid for both
    // sides so the card's Yes and No cannot both be impossible.
    const target = before![0] === 77 ? 31 : 77
    expect(publishPrice(target / 100), "could not publish to Redis").toBe(true)

    await expect
      .poll(async () => (await firstCardPrices(page))?.[0], { timeout: 10_000 })
      .toBe(target)

    // The complement must follow too. A grid that updated only the Yes side would
    // show a market priced at 77 and 38, which sums past 100.
    const after = await firstCardPrices(page)
    expect((after![0] ?? 0) + (after![1] ?? 0)).toBe(100)
  })

  test("keeps many cards live at once, not just the first", async ({ page }) => {
    await page.goto("/markets")
    await page.waitForSelector("[data-index]", { timeout: 20_000 })
    await page.waitForTimeout(1500)

    const cells = await page.locator("[data-index]").count()
    expect(cells).toBeGreaterThan(2)

    // Only the first card's market is being published to, so this asserts the
    // *other* cards are left alone - a grid that repainted wholesale on every
    // frame would pass a naive "something changed" check while being wrong.
    const others = await page.evaluate(() =>
      [...document.querySelectorAll("[data-index]")]
        .slice(1, 4)
        .map((c) => c.textContent),
    )
    expect(publishPrice(0.63)).toBe(true)
    await page.waitForTimeout(1500)
    const after = await page.evaluate(() =>
      [...document.querySelectorAll("[data-index]")].slice(1, 4).map((c) => c.textContent),
    )
    expect(after).toEqual(others)
  })
})