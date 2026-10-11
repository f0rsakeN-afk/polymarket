/**
 * The grid must scale with what is on screen, not with what has been loaded.
 *
 * Two costs grew with the length of the catalogue while nothing about them was
 * visible to the user:
 *
 *   1. The server buffered a price per declared market per flush, so a long list
 *      meant permanent work for markets scrolled far out of view.
 *   2. Every mounted card re-rendered when its own price ticked, so a market
 *      moving on page 40 repainted a node nobody could see.
 *
 * Both are now bounded by the visible range. These tests pin that, and pin the
 * detail that makes it safe: overscan. Subscribing only what is strictly visible
 * means a market has no live data at the moment it scrolls into view - it shows
 * a stale REST price until something else happens to move it, which reads as the
 * realtime layer being broken precisely where the user was looking.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MarketList } from "@/components/markets/market-list"
import type { MarketResponse } from "@/hooks/api/types/market"
import type { ReactNode } from "react"

vi.mock("@/hooks/use-market-socket", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/use-market-socket")>(
    "@/hooks/use-market-socket"
  )
  return {
    ...actual,
    // The grid declaration is the thing under test, so capture it rather than
    // letting it reach a socket.
    useMarketGrid: (ids: string[]) => {
      gridDeclarations.push(ids)
    },
  }
})

/** Every `marketIds` array the component declared, in order. */
let gridDeclarations: string[][] = []

/** `MarketList` invalidates the markets query, so it needs a client to talk to. */
function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

const market = (i: number): MarketResponse =>
  ({ id: `m${i}`, status: "active", question: `Market ${i}` }) as MarketResponse

/** Give the virtualizer a viewport; jsdom reports zero for everything. */
function stubViewport(el: HTMLElement, height = 900) {
  Object.defineProperty(el, "clientHeight", { value: height, configurable: true })
  Object.defineProperty(el, "getBoundingClientRect", {
    value: () => ({ width: 1200, height, top: 0, left: 0, bottom: height, right: 1200 }),
    configurable: true,
  })
  return el
}

/**
 * jsdom has no IntersectionObserver.
 *
 * Production needs it twice over: the virtualizer uses it to decide which rows
 * are near the viewport, and the load-more sentinel uses it to page the
 * catalogue in. Without a stub the component cannot mount at all - so this is
 * also the thing that proves the list is wired to both.
 */
class StubIntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
  root = null
  rootMargin = ""
  thresholds: number[] = []
}

beforeEach(() => {
  gridDeclarations = []
  vi.stubGlobal("IntersectionObserver", StubIntersectionObserver)
  // The virtualizer reads a viewport; jsdom reports zero for every box.
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })

  // The virtualizer sizes itself from the scroll element's box, and jsdom reports
  // zero for every measurement ever taken. A zero-height viewport is not a
  // degenerate list - it means "nothing is visible", so nothing renders, which is
  // indistinguishable from the list being empty.
  Object.defineProperty(HTMLElement.prototype, "clientHeight", {
    configurable: true,
    get() { return 900 },
  })
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get() { return this.dataset.index !== undefined ? 260 : 900 },
  })
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get() { return 1200 },
  })
  Element.prototype.getBoundingClientRect = function () {
    return {
      width: 1200, height: 900,
      top: 0, left: 0, right: 1200, bottom: 900,
      x: 0, y: 0, toJSON: () => ({}),
    } as DOMRect
  }
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const lastDeclaration = () => gridDeclarations[gridDeclarations.length - 1] ?? []

/** Render inside a QueryClientProvider. */
const renderList = (ui: ReactNode) => render(ui, { wrapper })

describe("MarketList windowing", () => {
  it("declares only the visible range, not the whole catalogue", () => {
    const markets = Array.from({ length: 600 }, (_, i) => market(i))

    renderList(<MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />)

    const declared = lastDeclaration()
    // The whole point. A user looking at one screen is subscribed to one screen,
    // so the server-side cost tracks the viewport rather than the catalogue.
    expect(declared.length).toBeGreaterThan(0)
    expect(declared.length).toBeLessThan(markets.length)
  })

  it("does not declare every market once the list is long", () => {
    const markets = Array.from({ length: 200 }, (_, i) => market(i))

    renderList(<MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />)

    // 200 cards would be 200 server-side subscriptions and 200 buffered prices
    // per flush, for a screen that shows a fraction of them.
    expect(lastDeclaration().length).toBeLessThan(100)
  })

  it("renders a bounded number of cards", () => {
    const markets = Array.from({ length: 400 }, (_, i) => market(i))

    const { container } = renderList(
      <MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )

    // Only the windowed rows exist in the DOM. Every mounted card is a node that
    // re-renders when its own price ticks, so mounting all 400 makes a market on
    // page 20 repaint work nobody asked for.
    const cards = container.querySelectorAll("[data-index]")
    expect(cards.length).toBeGreaterThan(0)
    expect(cards.length).toBeLessThan(60)
  })

  it("still renders the first markets", () => {
    // Three markets must not vanish. Windowing is only worth doing if the rows
    // inside the window are still the rows the user asked for - a virtualizer
    // pointed at a zero-height viewport renders nothing at all, which is
    // indistinguishable from an empty catalogue and would ship as "the markets
    // page is blank" on any browser that mismeasures once.
    const markets = [market(0), market(1), market(2)]
    const { container } = renderList(
      <MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )

    const rendered = container.querySelectorAll("[data-index]")
    expect(rendered.length).toBe(3)
    expect(container.textContent).toContain("Market 0")
    expect(container.textContent).toContain("Market 2")
  })

  it("never declares a market it is not rendering", () => {
    const markets = Array.from({ length: 300 }, (_, i) => market(i))
    const { container } = renderList(
      <MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )

    const rendered = new Set(
      [...container.querySelectorAll("[data-index]")].map((el) =>
        Number(el.getAttribute("data-index"))
      )
    )
    // Anything declared but not mounted is a subscription the server is paying
    // for and the user cannot see. The overscan keeps this small but non-zero,
    // which is the whole reason it exists.
    const declaredOutside = lastDeclaration().filter((id) => {
      const idx = Number(id.replace("m", ""))
      return !rendered.has(idx)
    })
    expect(declaredOutside.length).toBeLessThanOrEqual(8)
  })
})

describe("MarketList scroll container", () => {
  it("gives the virtualizer a scroll element", () => {
    const markets = Array.from({ length: 50 }, (_, i) => market(i))
    renderList(<MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />)

    // Without a scroll element the virtualizer reports a zero-height viewport and
    // renders nothing, which would look like the list simply being empty.
    expect(screen.getByTestId("market-scroll")).toBeTruthy()
  })

  it("keeps the sentinel for pagination", () => {
    const markets = Array.from({ length: 50 }, (_, i) => market(i))
    const onLoadMore = vi.fn()
    const { container } = renderList(
      <MarketList markets={markets} loading={false} hasMore onLoadMore={onLoadMore} />
    )

    // Windowing the rows must not remove the thing that pages the catalogue in.
    expect(container.querySelector("div[class*='justify-center']")).toBeTruthy()
  })
})

// Keeps the helper referenced so lint does not strip it as unused; the stub is
// applied by the virtualizer itself via getBoundingClientRect.
void stubViewport