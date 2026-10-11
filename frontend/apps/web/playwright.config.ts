import { defineConfig, devices } from "@playwright/test"

/**
 * Browser tests, pointed at a running stack.
 *
 * Everything else in this repo tests *code*. None of it tests *layout*, because
 * jsdom has no layout engine: `grid-cols-3` and `width: 100%` are indistinguishable
 * to it, and neither is a card at 416px next to two others on the same row.
 *
 * That hole is not theoretical. The markets grid shipped as a single column twice,
 * with a nested scroller inside the page, and every one of those tests passed -
 * because they all asserted *how many* cards render, never *how they are
 * arranged*. A browser is the only layer that can see the difference.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  // One worker: these assert on layout in a shared dev server, and a parallel
  // reload storm makes a green run flaky, which is worse than a slow one.
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 15_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
})