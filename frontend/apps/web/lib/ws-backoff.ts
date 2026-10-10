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

/** Delay before reconnect attempt `attempt` (0-based), in milliseconds. */
export function reconnectDelayMs(attempt: number): number {
  const capped = Math.min(1000 * Math.pow(2, attempt), MAX_BACKOFF_MS)
  return Math.round(capped / 2 + Math.random() * (capped / 2))
}