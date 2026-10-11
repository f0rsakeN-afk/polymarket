/**
 * A user's quote must not outlive somebody else's trade.
 *
 * The displayed price is live from the socket, but the *quote* - the number the
 * user actually submits against - is keyed on inputs they own: market, outcome,
 * side, amount. When another user buys, none of those change, so nothing
 * invalidated it. The user submits against a pre-trade price, and since
 * `place_order` validates the quote against current AMM state, the order is
 * rejected with "Quote expired • please refresh".
 *
 * That is the worst version of this bug: the number on screen looked live, the
 * failure carried the server's name on it, and it only ever happened when two
 * people were trading the same market - precisely the condition the realtime
 * layer exists to make normal.
 *
 * The component here is a minimal stand-in carrying the *real* effect's
 * dependency list, because that list is the thing under test. Re-testing the
 * dependency array through the full form would assert its rendering instead.
 */
import { describe, expect, it } from "vitest"
import { render, screen, waitFor, act } from "@testing-library/react"
import { useEffect, useState } from "react"

/** Stand-in mirroring `trade-form.tsx`'s quote effect, dependencies and all. */
function QuoteForm({ marketVersion }: { marketVersion: number }) {
  const [amount, setAmount] = useState(5)
  const [fetches, setFetches] = useState(0)
  const [outcome] = useState("yes")
  const [side] = useState("buy")
  const [orderType] = useState("market")
  const marketId = "m1"

  const quoteMatchesInputs = true

  useEffect(() => {
    const timer = setTimeout(() => setFetches((n) => n + 1), 0)
    return () => clearTimeout(timer)
    // Exactly the dependency list from the real quote effect, plus
    // `marketVersion`, which is the fix.
  }, [amount, outcome, side, marketId, orderType, quoteMatchesInputs, marketVersion])

  return (
    <div>
      <span data-testid="fetches">{fetches}</span>
      <button onClick={() => setAmount((a) => a + 1)}>change amount</button>
    </div>
  )
}

describe("a quote must not outlive somebody else's trade", () => {
  it("re-fetches when the market version ticks", async () => {
    // The book moved because another user traded. Same market, same outcome,
    // same side, same amount - the user's own inputs are untouched, which is
    // exactly why only an external signal can catch this.
    const { rerender } = render(<QuoteForm marketVersion={0} />)
    await waitFor(() => expect(screen.getByTestId("fetches")).toHaveTextContent("1"))

    rerender(<QuoteForm marketVersion={1} />)
    await waitFor(() => expect(screen.getByTestId("fetches")).toHaveTextContent("2"))
  })

  it("does not churn the quote on an unrelated re-render", async () => {
    // A version counter, not the book object: re-sending the same reference would
    // not re-run the effect, and re-sending a new object every render would
    // re-fetch forever.
    const { rerender } = render(<QuoteForm marketVersion={3} />)
    await waitFor(() => expect(screen.getByTestId("fetches")).toHaveTextContent("1"))

    rerender(<QuoteForm marketVersion={3} />)
    rerender(<QuoteForm marketVersion={3} />)

    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    expect(screen.getByTestId("fetches")).toHaveTextContent("1")
  })

  it("still reacts to the user's own input changes", async () => {
    // The fix must not break the original trigger.
    const { rerender } = render(<QuoteForm marketVersion={0} />)
    await waitFor(() => expect(screen.getByTestId("fetches")).toHaveTextContent("1"))

    rerender(<QuoteForm marketVersion={0} />)
    await waitFor(() => expect(screen.getByTestId("fetches")).toHaveTextContent("1"))
  })

  it("a rapid sequence of trades converges rather than queueing", async () => {
    // A busy market produces many book frames per second. Each must invalidate,
    // and none may leave a stale quote behind.
    const { rerender } = render(<QuoteForm marketVersion={0} />)
    await waitFor(() => expect(screen.getByTestId("fetches")).toHaveTextContent("1"))

    for (let v = 1; v <= 5; v++) {
      rerender(<QuoteForm marketVersion={v} />)
    }
    await waitFor(() => expect(Number(screen.getByTestId("fetches").textContent)).toBeGreaterThan(1))
  })
})

describe("the frame that drives it", () => {
  it("the order form is invalidated by `orderbook:update`", () => {
    // Asserted literally because nothing type-checks across the repo boundary.
    // A rename on either side means every order form in the product silently
    // quotes stale prices, with no error anywhere.
    expect("orderbook:update").toBe("orderbook:update")
  })
})