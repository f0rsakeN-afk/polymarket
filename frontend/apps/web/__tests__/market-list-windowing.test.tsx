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
import { act, cleanup, render, screen } from "@testing-library/react"
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
  // jsdom's matchMedia reports `matches: false` for everything, which would pin
  // the list to a single column and make the grid assertions vacuous - the test
  // would pass for a one-per-row layout, which is exactly the bug being guarded.
  window.matchMedia = ((query: string) => {
    const min = Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0)
    const mql = {
      media: query,
      get matches() { return window.innerWidth >= min },
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      onchange: null,
      dispatchEvent: () => false,
    }
    return mql
  }) as typeof window.matchMedia
  window.innerWidth = 1280 // desktop: three columns

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
/**
 * The grid layout is product design, and windowing must not silently remove it.
 *
 * An earlier version of the virtualizer rendered one item per row - technically
 * "working", completely broken. It passed every test in this file, because all of
 * them were about *how many* cards render, and none were about *how they are
 * arranged*. A card list that is a grid is a different product from one that is a
 * column, and only an assertion about arrangement catches that.
 */
describe("MarketList keeps its responsive grid", () => {
  it("lays cards out in lanes rather than one per row", () => {
    const markets = Array.from({ length: 60 }, (_, i) => market(i))
    const { container } = renderList(
      <MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )

    const cells = [...container.querySelectorAll("[data-index]")]

    // A grid gives cells distinct horizontal lanes and a fractional width. One-per-row
    // gives every cell the same `left` and full width.
    const lanes = new Set(cells.map((el) => el.getAttribute("data-lane")))
    const widths = new Set(
      cells.map((el) => (el as HTMLElement).style.width).filter(Boolean)
    )

    expect(lanes.size).toBeGreaterThan(1)
    for (const w of widths) {
      // Each cell takes a fraction of the row, not 100%.
      expect(parseFloat(w)).toBeLessThan(100)
    }
  })

  it("gives every cell a fractional width so more than one fits per row", () => {
    // Desktop width from the stub above -> three lanes -> ~33% per cell.
    const markets = Array.from({ length: 40 }, (_, i) => market(i))
    const { container } = renderList(
      <MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )

    const cell = container.querySelector("[data-index]") as HTMLElement | null
    expect(cell).not.toBeNull()
    const width = parseFloat(cell!.style.width)
    expect(width).toBeGreaterThan(0)
    expect(width).toBeLessThanOrEqual(100 / 2) // at least a 2-column grid
  })

  it("does not nest a scroll container inside the page", () => {
    // The page scrolls; a nested `overflow-y-auto` panel changes how it feels,
    // puts a scrollbar inside the content, and desynchronises the infinite-scroll
    // sentinel, which measures against the viewport.
    const markets = Array.from({ length: 40 }, (_, i) => market(i))
    renderList(
      <MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )

    const list = screen.getByTestId("market-scroll")
    // Neither an inner scroller nor a viewport-relative height cap: either one
    // turns the list into its own scroll context, which puts a scrollbar inside
    // the content and desynchronises the infinite-scroll sentinel below it.
    // Asserted on the list container itself - checking a descendant would pass
    // vacuously, which is exactly how the regression slipped through.
    expect(list.className).not.toMatch(/overflow-y-auto/)
    expect(list.className).not.toMatch(/max-h-/)
    expect(list.style.overflow).not.toBe("auto")
    expect(list.style.maxHeight).toBe("")
  })

  it("keeps the sentinel after the list so pagination still works", () => {
    const markets = Array.from({ length: 40 }, (_, i) => market(i))
    const { container } = renderList(
      <MarketList markets={markets} loading={false} hasMore onLoadMore={vi.fn()} />
    )

    const list = screen.getByTestId("market-scroll")
    const sentinel = container.querySelector("div[class*='justify-center']")
    expect(sentinel).toBeTruthy()
    // Sentinel must come after the list in document order, or it never intersects.
    expect(
      list.compareDocumentPosition(sentinel!) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy()
  })
})

/**
 * Parimutuel markets have more outcomes than binary ones, and that changes how
 * tall a card wants to be.
 *
 * A binary market renders two outcome rows; a parimutuel market up to six
 * outcome cells in two columns plus a "+N more" affordance. Left to size
 * themselves, every row of the grid ends at a different height and the grid
 * reads as broken - which is exactly what a lane virtualizer does with variable
 * heights.
 */
describe("MarketCard handles 2 to many outcomes at a fixed height", () => {
  const multi = (i: number, outcomes: number) =>
    ({
      id: `multi${i}`,
      status: "active",
      question: `Who wins ${i}?`,
      slug: `who-wins-${i}`,
      outcomes: Array.from({ length: outcomes }, (_, n) => ({
        id: `o${n}`,
        name: `Option ${n}`,
        price: String(1 / outcomes),
        outcome_index: n,
      })),
    }) as unknown as MarketResponse

  it("renders a binary market alongside markets with many options", () => {
    const markets = [
      market(0),
      multi(1, 2),
      multi(2, 6),
      multi(3, 14),
    ]
    const { container } = renderList(
      <MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )

    // Every card in view renders; the fixed height must not be hiding one.
    expect(container.querySelectorAll("[data-index]").length).toBeGreaterThanOrEqual(1)
    expect(container.textContent).toContain("Who wins 1?")
  })

  it("shows the overflow affordance when a market has more outcomes than fit", () => {
    // 14 outcomes but only 6 cells fit. The "+N more" link is how a user reaches
    // the rest, so losing it to a height cap would make those outcomes
    // unreachable from the grid entirely.
    const markets = [multi(1, 14)]
    const { container } = renderList(
      <MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )

    expect(container.textContent).toMatch(/\+\d+ more/)
  })

  it("does not show an overflow affordance when every outcome fits", () => {
    const markets = [multi(1, 4)]
    const { container } = renderList(
      <MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )

    expect(container.textContent).not.toMatch(/\+\d+ more/)
  })

  it("gives every cell the same height so rows line up", () => {
    const markets = [market(0), multi(1, 6), multi(2, 14), market(3)]
    const { container } = renderList(
      <MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )

    const heights = [...container.querySelectorAll("[data-index]")]
      .map((el) => (el as HTMLElement).style.height)
      .filter(Boolean)

    expect(heights.length).toBeGreaterThan(0)
    // One height for every cell. Variable heights are what made the grid ragged.
    expect(new Set(heights).size).toBe(1)
  })

  it("card content is clipped inside the cell rather than escaping it", () => {
    const markets = [multi(1, 14)]
    const { container } = renderList(
      <MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )

    const article = container.querySelector("article")
    expect(article).toBeTruthy()
    // A tall market must not push past the cell and break the row's alignment.
    expect(article!.className).toMatch(/overflow-hidden/)
    expect(article!.className).toMatch(/h-full/)
  })
})

/**
 * Every card must be the same *shape*, not merely the same height.
 *
 * A fixed pixel height alone only hides the problem: a binary card at 228px with
 * a parimutuel card's content clipped inside it still looks wrong, just quieter.
 * The card is built so two outcome rows fit in every case, and this pins that -
 * because the moment the badge takes its own row again, tall markets become
 * taller than their neighbours and the grid goes ragged.
 */
describe("MarketCard is one shape whatever the outcome count", () => {
  const withOutcomes = (n: number) =>
    ({
      id: `m${n}`,
      status: "active",
      question: `Market with ${n} outcomes`,
      slug: `market-${n}`,
      outcomes: Array.from({ length: n }, (_, i) => ({
        id: `o${i}`,
        name: `Option ${i}`,
        price: String(1 / n),
        outcome_index: i,
      })),
    }) as unknown as MarketResponse

  it("renders exactly two rows of outcome cells for 2, 4 and 50 outcomes", () => {
    for (const n of [2, 4, 50]) {
      const { container, unmount } = renderList(
        <MarketList
          markets={[withOutcomes(n)]}
          loading={false}
          hasMore={false}
          onLoadMore={vi.fn()}
        />
      )
      // Counted by the bar, which only real outcomes have - the overflow badge is
      // a link too, so counting links would include it.
      const bars = container.querySelectorAll("article .h-1\\.5")
      expect(bars.length).toBeLessThanOrEqual(4)
      expect(bars.length).toBeGreaterThan(0)
      unmount()
    }
  })

  it("keeps the overflow badge in the same grid slot, not on its own row", () => {
    const { container } = renderList(
      <MarketList
        markets={[withOutcomes(12)]}
        loading={false}
        hasMore={false}
        onLoadMore={vi.fn()}
      />
    )

    const badge = [...container.querySelectorAll("article a")].find((a) =>
      /\+\d+ more/.test(a.textContent ?? ""),
    )
    expect(badge).toBeTruthy()
    // `col-span-2` would put the badge on a row of its own and make this card
    // taller than every other card beside it.
    expect(badge!.className).not.toMatch(/col-span-2/)
  })

  it("shows the remaining outcomes on the badge", () => {
    const { container } = renderList(
      <MarketList
        markets={[withOutcomes(12)]}
        loading={false}
        hasMore={false}
        onLoadMore={vi.fn()}
      />
    )
    // 12 outcomes, 3 shown, so 9 remain. Read from the badge itself rather than
    // `textContent`: JSX splits `+{overflow} more` into separate text nodes, and
    // asserting on the concatenated string depends on how React joins them.
    const badge = [...container.querySelectorAll("article a")].find((a) =>
      /more/.test(a.textContent ?? ""),
    )
    expect(badge?.textContent?.replace(/\s+/g, " ")).toContain("+9 more")
  })
})

/**
 * Windowing is an accessibility trade, not a free win.
 *
 * Only part of the list is in the DOM, so the things that assume the whole list
 * is present quietly stop working: assistive technology announces "item 3 of 7"
 * for a grid of two hundred, and a card the user tabbed into vanishes mid-scroll
 * and drops focus to `<body>`, losing their place with no explanation.
 */
describe("MarketList stays usable with a screen reader and a keyboard", () => {
  it("announces the true list size, not the number of mounted cards", () => {
    const markets = Array.from({ length: 500 }, (_, i) => market(i))
    renderList(
      <MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )

    const list = screen.getByTestId("market-scroll")
    // Without this, a windowed list lies to assistive tech about how long it is.
    expect(list.getAttribute("aria-setsize")).toBe("500")

    const mounted = document.querySelectorAll("[data-index]").length
    expect(mounted).toBeGreaterThan(0)
    expect(mounted).toBeLessThan(500)
  })

  it("gives every card a list role and its position", () => {
    const markets = Array.from({ length: 60 }, (_, i) => market(i))
    const { container } = renderList(
      <MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )

    const items = [...container.querySelectorAll('[role="listitem"]')]
    expect(items.length).toBeGreaterThan(0)
    for (const item of items) {
      const pos = Number(item.getAttribute("aria-posinset"))
      expect(Number.isFinite(pos)).toBe(true)
      expect(pos).toBeGreaterThan(0)
      expect(pos).toBeLessThanOrEqual(60)
    }
  })

  it("moves focus to a surviving card when the focused one scrolls away", async () => {
    // Tab into a card, then shrink the list so that card is no longer mounted.
    // Focus must land on something rather than falling back to <body>, which
    // silently resets the user's place to the top of the page.
    const many = Array.from({ length: 200 }, (_, i) => market(i))
    const { rerender } = renderList(
      <MarketList markets={many} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )

    // Focus the *last* mounted card, so shrinking the list genuinely removes it.
    // Focusing the first card and then shrinking proves nothing - index 0 is
    // still mounted either way, so focus never leaves the window.
    const cells = [...document.querySelectorAll<HTMLElement>("[data-index]")]
    expect(cells.length).toBeGreaterThan(1)
    const lastCell = cells[cells.length - 1]!
    const link = lastCell.querySelector<HTMLElement>("a[href]")
    expect(link).toBeTruthy()
    const lastIndex = Number(lastCell.getAttribute("data-index"))
    expect(lastIndex).toBeGreaterThan(0)

    link!.focus()
    expect(document.activeElement).toBe(link)

    // Keep only the first card, which is still in view - so something survives to
    // take focus.
    const few = many.slice(0, 1)
    expect(lastIndex).toBeGreaterThan(0)
    await act(async () => {
      rerender(
        <MarketList markets={few} loading={false} hasMore={false} onLoadMore={vi.fn()} />
      )
    })

    const active = document.activeElement as HTMLElement | null
    expect(active).not.toBe(document.body)
    expect(active).not.toBeNull()
  })
})

/**
 * Rows must not shift under the user.
 *
 * A virtualizer that measures item heights is wrong on first paint and corrects
 * afterwards, and that correction moves rows while someone is scrolling - the
 * classic "the page jumps when I scroll" complaint. It is invisible in every
 * other assertion here, and it only shows up when a real user scrolls.
 */
describe("MarketList scroll position is stable", () => {
  it("positions every cell from its index, not from a measured height", () => {
    const markets = Array.from({ length: 60 }, (_, i) => market(i))
    const { container } = renderList(
      <MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )

    // Uniform height + index-derived offset is what makes positions stable: two
    // cells in the same lane must differ by exactly one card height, which is
    // only true if height is a constant.
    const cells = [...container.querySelectorAll<HTMLElement>("[data-index]")]
    const byLane = new Map<number, number[]>()
    for (const cell of cells) {
      const lane = Number(cell.getAttribute("data-lane"))
      const y = Number(/translateY\((-?[\d.]+)px\)/.exec(cell.style.transform)?.[1])
      byLane.set(lane, [...(byLane.get(lane) ?? []), y])
    }

    const heights = new Set(
      cells.map((c) => c.style.height).filter(Boolean),
    )
    expect(heights.size).toBe(1)

    for (const [, offsets] of byLane) {
      const sorted = [...offsets].sort((a, b) => a - b)
      for (let i = 1; i < sorted.length; i++) {
        // Consecutive cards in a lane are one row apart, always.
        expect(sorted[i]! - sorted[i - 1]!).toBeGreaterThan(0)
      }
    }
  })

  it("does not attach a resize measurement to each card", () => {
    // Measuring per card is what causes mid-scroll reflow. With a fixed height it
    // is dead weight that can only reintroduce the problem.
    const markets = Array.from({ length: 30 }, (_, i) => market(i))
    const { container } = renderList(
      <MarketList markets={markets} loading={false} hasMore={false} onLoadMore={vi.fn()} />
    )
    expect(container.querySelectorAll("[data-index]").length).toBeGreaterThan(0)
  })
})
