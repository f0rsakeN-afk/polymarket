import { test, expect, type Page } from "@playwright/test"
import { execSync } from "node:child_process"

/**
 * Every surface, asked whether it is actually live.
 *
 * The markets grid had its own test for this. It turned out three other
 * surfaces had never been asked at all - and a surface nobody asks can be
 * permanently static while every other signal says it is fine.
 *
 * What each test does is deliberately blunt: publish a frame through the
 * production path, then require the page to change. Not "the socket is open",
 * not "the handler was called" - the rendered result. A frame that arrives and
 * is dropped is the failure mode this exists to catch, and only a rendered
 * comparison can see it.
 *
 * Two of these tests caught *the test*, not the app:
 *   - the trades tape renders `0.64`, not `64%`, so a percentage-counting probe
 *     saw no change on a feed that was updating perfectly
 *   - the orderbook frame is `{ outcomes: { yes: { bids, asks } } }`, and a
 *     probe publishing flat `bids`/`asks` was sending a different message
 *     entirely - which the detail page correctly ignored
 *
 * Both cost a full debug cycle. The lesson is why these assert on rendered text
 * with a known marker rather than on structure.
 */

const MARKET_ID = process.env.E2E_MARKET_ID
const BACKEND = process.env.E2E_BACKEND_DIR ?? "../../../backend"

function publish(kind: string, value?: string): boolean {
  try {
    execSync(
      `cd ${BACKEND} && REDIS_PASSWORD=${process.env.REDIS_PASSWORD ?? "devpass"} ` +
        `.venv/bin/python -m harness.push_frame ${kind} ${MARKET_ID} ${value ?? ""}`,
      { shell: "/bin/bash", stdio: "pipe", env: process.env },
    )
    return true
  } catch {
    return false
  }
}

/** The first percentage on the first grid card - Yes on a binary market. */
async function firstCardYes(page: Page): Promise<number | null> {
  return page.evaluate(() => {
    const cell = document.querySelector("[data-index]")
    if (!cell) return null
    const hit = [...cell.querySelectorAll("span")]
      .map((s) => s.textContent?.trim() ?? "")
      .find((t) => /^\d+%$/.test(t))
    return hit ? Number(hit.replace("%", "")) : null
  })
}

const skip = !MARKET_ID || !process.env.REDIS_PASSWORD

test.describe("every public surface is live", () => {
  test.skip(skip, "needs E2E_MARKET_ID and REDIS_PASSWORD - a seeded market and the app's Redis")

  test("home grid updates from a socket price", async ({ page }) => {
    await page.goto("/")
    await page.waitForSelector("[data-index]", { timeout: 20_000 })
    await page.waitForTimeout(1500)

    const before = await firstCardYes(page)
    expect(before).not.toBeNull()

    const target = before === 77 ? 31 : 77
    expect(publish("price", String(target / 100))).toBe(true)

    await expect.poll(() => firstCardYes(page), { timeout: 10_000 }).toBe(target)
  })

  test("trades tape prepends an incoming trade", async ({ page }) => {
    await page.goto("/trades")
    await page.waitForTimeout(2500)

    // The tape is a virtualised list of divs, not a table - and it shares the page
    // with nav items, so the first `li` is "Markets". Prices render `$0.621`, not
    // `62%`. A probe written for a table of percentages saw zero rows on a
    // perfectly working feed.
    const rowCount = () => page.evaluate(() => document.querySelectorAll("[data-trade-id]").length)
    const topRow = () =>
      page.evaluate(() => (document.querySelector("[data-trade-id]") as HTMLElement | null)?.innerText ?? "")

    expect(await rowCount()).toBeGreaterThan(0)

    expect(publish("global")).toBe(true)
    // A new trade is prepended; the list is capped, so the count can stay the
    // same while the contents change. Assert on identity, not on size.
    // The list is capped, so the row count can stay put while the contents turn
    // over. Assert on the newest row's contents, not on the count.
    await expect.poll(topRow, { timeout: 10_000 }).toContain("0.64")
  })

  test("market detail renders an incoming orderbook", async ({ page }) => {
    await page.goto(`/markets/${process.env.E2E_MARKET_SLUG ?? "bitcoin-100k-2024"}`)
    await page.waitForTimeout(2500)

    const hasLevel = () => page.evaluate(() => (document.body.innerText ?? "").includes("0.58"))

    expect(await hasLevel(), "the seeded book already had this level").toBe(false)
    expect(publish("book")).toBe(true)

    // The frame is `{ outcomes: { yes: { bids, asks } } }` - the shape
    // `build_orderbook` produces. A probe publishing flat `bids`/`asks` sends a
    // different message, which the page correctly ignores.
    await expect.poll(hasLevel, { timeout: 10_000 }).toBe(true)
  })

  test("market detail reacts to a trade on its own market", async ({ page }) => {
    await page.goto(`/markets/${process.env.E2E_MARKET_SLUG ?? "bitcoin-100k-2024"}`)
    await page.waitForTimeout(2500)

    const before = await page.evaluate(() => (document.body.innerText ?? "").length)
    expect(publish("trade")).toBe(true)
    await expect
      .poll(() => page.evaluate(() => (document.body.innerText ?? "").length), { timeout: 10_000 })
      .not.toBe(before)
  })
})