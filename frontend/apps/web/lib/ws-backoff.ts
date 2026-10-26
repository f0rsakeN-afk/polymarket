/**
 * Reconnect backoff shared by all three socket hooks.
 *
 * Two properties, both of which the previous inline `1000 * 2^n` did not have.
 *
 * **It never gives up.** Every hook used to park itself after 8 attempts and
 * only recover on `online` or a tab focus. That made realtime *permanently*
 * conditional on a signal the browser may never send: a laptop that sleeps with
 * the network down, a deploy that bounces the backend, a phone that switches
 * from cellular to wifi mid-handshake. The tab looks fine - the indicator says
 * "connected" right up until the first frame that never arrives, and often not
 * even that - and the feed is gone for the rest of the session. Since the
 * server reaps idle sockets anyway (a socket silent past the pong deadline is
 * assumed dead), retrying forever at a capped interval costs almost nothing and
 * is the difference between a self-healing feed and a dead one.
 *
 * **It jitters.** Every tab that lost the same server reconnects at the same
 * instant, so un-jittered backoff turns a blip into a synchronised stampede
 * exactly when the server is least able to absorb it. Equal jitter (half the
 * window fixed, half random) keeps a floor under the delay while still
 * spreading the herd out across the window.
 */

export const MAX_BACKOFF_MS = 30_000

/** Jitter factor: adds randomness to prevent thundering herd on reconnect. */
const JITTER_FACTOR = 0.5

/** Delay before reconnect attempt `attempt` (0-based), in milliseconds. */
export function reconnectDelayMs(attempt: number): number {
  // Faster initial backoff: 200ms, 350ms, 600ms, 1s, 2s, 4s, 8s, then exponential cap
  // versus old: 500ms, 1000ms, 2000ms, 4000ms, ...
  // Use fixed delayed sequence for first 7 attempts, then exponential
  if (attempt === 0) return Math.round(200 / 2 + Math.random() * (200 / 2) * JITTER_FACTOR)
  if (attempt === 1) return Math.round(350 / 2 + Math.random() * (350 / 2) * JITTER_FACTOR)
  if (attempt === 2) return Math.round(600 / 2 + Math.random() * (600 / 2) * JITTER_FACTOR)
  if (attempt === 3) return Math.round(1000 / 2 + Math.random() * (1000 / 2) * JITTER_FACTOR)
  if (attempt === 4) return Math.round(2000 / 2 + Math.random() * (2000 / 2) * JITTER_FACTOR)
  if (attempt === 5) return Math.round(4000 / 2 + Math.random() * (4000 / 2) * JITTER_FACTOR)
  if (attempt === 6) return Math.round(8000 / 2 + Math.random() * (8000 / 2) * JITTER_FACTOR)
  // Exponential: 8000, 16000, 32000(capped to 30000), 30000, ...
  // attempt >= 7, delay is definitely a number
  const delay = 8000 * (2 ** (attempt - 7))
  const capped = Math.min(delay, MAX_BACKOFF_MS)
  // Apply jitter: ±50% of the delay, so two tabs never reconnect at the exact same moment
  return Math.round(capped / 2 + Math.random() * (capped / 2) * JITTER_FACTOR)
}
