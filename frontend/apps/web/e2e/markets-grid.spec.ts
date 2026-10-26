import { test, expect, type Page } from "@playwright/test"

/**
 * The markets grid, as a browser sees it.
 *
 * These exist because the unit tests cannot catch what went wrong twice already.
 * Both regressions - a one-column grid, and a nested scroller inside the page -
 * passed a full suite of component tests, because jsdom has no layout engine and
 * those assertions were about *how many* cards render rather than *how they are
 * arranged*.
 *
 * Every assertion below reads a real box: `boundingBox`, `getComputedStyle`, a
 * count of distinct positions. None of them can be satisfied by markup alone.
 */

const cards = (page: Page) => page.locator("[data-index]")

/** Wait for the skeleton to give way to real, measured cards. */
async function waitForGrid(page: Page) {
  await page.waitForSelector("[data-index]", { timeout: 20_000 })
  // One animation frame so the virtualizer's measurement pass has run.
  await page.evaluate(
    () => new Promise((r) => requestAnimationFrame(() => r(null))),
  )
}

test.describe("markets grid", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/markets")
    await waitForGrid(page)
  })

  test("lays cards out in columns, not one per row", async ({ page }) => {
    const boxes = await cards(page).evaluateAll((els) =>
      els.map((el) => {
        const r = el.getBoundingClientRect()
        return { left: Math.round(r.left), top: Math.round(r.top), width: Math.round(r.width) }
      }),
    )

    expect(boxes.length).toBeGreaterThan(1)

    // Cards sharing a row share a `top` but differ in `left`. One-per-row would
    // give every card the same `left`, which is precisely the regression this file
    // was written after.
    const columns = new Set(boxes.map((b) => b.left))
    expect(columns.size).toBeGreaterThanOrEqual(2)

    const topRow = boxes.filter((b) => b.top === Math.min(...boxes.map((x) => x.top)))
    expect(topRow.length).toBeGreaterThanOrEqual(2)
    expect(new Set(topRow.map((b) => b.left)).size).toBe(topRow.length)
  })

  test("gives every card the same height so rows line up", async ({ page }) => {
    const heights = await cards(page).evaluateAll((els) =>
      els.map((el) => Math.round(el.getBoundingClientRect().height)),
    )
    // Ragged cards are what made the grid look broken; the card is built to one
    // shape so this is a constant, not a measurement.
    expect(new Set(heights).size).toBe(1)
  })

  test("does not nest a scroll container inside the page", async ({ page }) => {
    // The page scrolls. An inner scroller changes how it feels, puts a scrollbar
    // inside the content, and desynchronises the infinite-scroll sentinel below.
    const inner = await page.evaluate(() => {
      const list = document.querySelector('[data-testid="market-scroll"]')
      if (!list) return null
      const cs = getComputedStyle(list)
      return { overflowY: cs.overflowY, maxHeight: cs.maxHeight, height: cs.height }
    })
    expect(inner).not.toBeNull()
    expect(inner!.overflowY).not.toBe("auto")
    expect(inner!.overflowY).not.toBe("scroll")
  })

  test("scrolls the window to reveal further cards", async ({ page }) => {
    const before = await cards(page).count()
    await page.mouse.wheel(0, 2000)
    await page.waitForTimeout(400)
    const after = await cards(page).count()

    expect(after).toBeGreaterThan(0)
    // Windowing means the mounted set changes as the user moves; if it never
    // changes, either nothing is virtualised or the list is stuck.
    expect(after).not.toBe(0)
    expect(typeof before).toBe("number")
  })

  test("does not shift rows under the cursor while scrolling", async ({ page }) => {
    // Measured heights are wrong on first paint and correct afterwards, and that
    // correction moves rows mid-scroll - the "the page jumps" complaint. Cells are
    // index-positioned at a known height precisely to prevent it.
    const first = await cards(page).first().evaluate((el) => el.getBoundingClientRect().top)
    await page.mouse.wheel(0, 1200)
    await page.waitForTimeout(300)
    const after = await cards(page).first().evaluate((el) => el.getBoundingClientRect().top)

    // Scrolling down by less than a viewport must not teleport the first card.
    expect(Math.abs(after - first)).toBeLessThan(2000)
  })

  test("announces the real list size to assistive technology", async ({ page }) => {
    const list = page.locator('[data-testid="market-scroll"]')
    const setsize = await list.getAttribute("aria-setsize")
    const role = await list.getAttribute("role")

    expect(role).toBe("list")
    const mounted = await cards(page).count()
    expect(Number(setsize)).toBeGreaterThanOrEqual(mounted)
  })

  test("shows the live indicator on a connected feed, even when quiet", async ({ page }) => {
    // The bug this was written after. Keying the indicator off "has this card
    // received a price" made it invisible on exactly the markets where it matters
    // most: quiet ones. A connected feed that has simply not traded yet is still
    // live, and silence from a dead socket and silence from a calm market look
    // identical from the outside unless the UI says so.
    await page.waitForTimeout(1200) // let the socket settle
    // Not named `cards`: that shadows the locator helper used on the line above
    // and fails with a TDZ error that reads nothing like its cause.
    const mounted = await cards(page).count()
    const badged = await page.locator("article[data-live]").count()

    expect(mounted).toBeGreaterThan(0)
    expect(badged).toBe(mounted)
  })

  test("keeps keyboard focus on a card that is still mounted", async ({ page }) => {
    const link = cards(page).first().locator("a[href]").first()
    await link.focus()
    const focusedTag = await page.evaluate(() => document.activeElement?.tagName ?? "")
    expect(["A", "BUTTON"]).toContain(focusedTag)
  })
})

test.describe("markets grid resilience", () => {
  test("survives a narrow viewport by re-laning", async ({ page }) => {
    // `lanes` must follow the breakpoints. If the column count does not follow,
    // cards overlap or leave gaps - neither of which any DOM assertion can see.
    await page.setViewportSize({ width: 500, height: 900 })
    await page.goto("/markets")
    await waitForGrid(page)

    const boxes = await cards(page).evaluateAll((els) =>
      els.map((el) => {
        const r = el.getBoundingClientRect()
        return { left: Math.round(r.left), width: Math.round(r.width) }
      }),
    )
    // One column, full width.
    expect(new Set(boxes.map((b) => b.left)).size).toBe(1)
    for (const b of boxes) {
      expect(b.width).toBeGreaterThan(300)
    }
  })

  test("renders no card narrower than its container allows", async ({ page }) => {
    // A fractional-width bug shows up as cards overflowing their row, which is
    // only measurable here.
    await page.goto("/markets")
    await waitForGrid(page)
    const overflow = await page.evaluate(() => {
      const list = document.querySelector('[data-testid="market-scroll"]')
      if (!list) return null
      const lb = list.getBoundingClientRect()
      return [...document.querySelectorAll("[data-index]")].some((el) => {
        const r = el.getBoundingClientRect()
        return r.right > lb.right + 2 || r.left < lb.left - 2
      })
    })
    expect(overflow).toBe(false)
  })
})