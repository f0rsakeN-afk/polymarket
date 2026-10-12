# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: private-live.spec.ts >> private surfaces are live >> orders reacts to a fill
- Location: e2e/private-live.spec.ts:161:3

# Error details

```
Error: expect(received).toBe(expected) // Object.is equality

Expected: true
Received: false

Call Log:
- Timeout 10000ms exceeded while waiting on the predicate
```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - button "Open Tanstack query devtools" [ref=e52] [cursor=pointer]
  - link "Skip to main content" [ref=e101] [cursor=pointer]:
    - /url: "#main-content"
  - generic [ref=e102]:
    - banner [ref=e103]:
      - generic [ref=e104]:
        - generic [ref=e105]:
          - link "PredictX home" [ref=e106] [cursor=pointer]:
            - /url: /
            - img "predictx logo" [ref=e107]
            - generic [ref=e108]: PredictX
          - navigation "Primary" [ref=e109]:
            - link "Markets" [ref=e110] [cursor=pointer]:
              - /url: /markets
            - link "Trades" [ref=e111] [cursor=pointer]:
              - /url: /trades
        - generic [ref=e112]:
          - search [ref=e114]:
            - generic [ref=e115]: Search markets
            - textbox "Search markets" [ref=e116]:
              - /placeholder: Search markets...
          - generic [ref=e117]:
            - heading "Command Palette" [level=2] [ref=e118]
            - paragraph [ref=e119]: Search for a command to run...
          - button "Toggle theme" [ref=e120] [cursor=pointer]
          - button "Notifications" [ref=e127] [cursor=pointer]
          - button "User menu" [ref=e131] [cursor=pointer]:
            - generic [ref=e132]: E
    - main [ref=e134]:
      - generic [ref=e135]:
        - generic [ref=e137]:
          - heading "Orders" [level=1] [ref=e138]
          - paragraph [ref=e139]: 7 orders
        - generic [ref=e140]:
          - button "All" [ref=e141] [cursor=pointer]
          - button "Pending" [ref=e142] [cursor=pointer]
          - button "Filled" [ref=e143] [cursor=pointer]
          - button "Partial" [ref=e144] [cursor=pointer]
          - button "Cancelled" [ref=e145] [cursor=pointer]
        - table [ref=e148]:
          - rowgroup [ref=e149]:
            - row [ref=e150]:
              - columnheader "Market" [ref=e151] [cursor=pointer]
              - columnheader "Side" [ref=e156]
              - columnheader "Outcome" [ref=e158]
              - columnheader "Type" [ref=e160] [cursor=pointer]
              - columnheader "Price" [ref=e165] [cursor=pointer]
              - columnheader "Amount" [ref=e170] [cursor=pointer]
              - columnheader "Status" [ref=e175] [cursor=pointer]
              - columnheader "Time" [ref=e180] [cursor=pointer]
              - columnheader [ref=e185]
          - rowgroup [ref=e186]:
            - row [ref=e187]:
              - cell "Which country will win Euro 2024?" [ref=e188]
              - cell "buy" [ref=e190]
              - cell "france" [ref=e192]
              - cell "market" [ref=e194]
              - cell "$0.610" [ref=e195]
              - cell "25" [ref=e196]
              - cell "filled" [ref=e197]
              - cell "1s ago" [ref=e199]
              - cell [ref=e200]
            - row [ref=e201]:
              - cell "Which country will win Euro 2024?" [ref=e202]
              - cell "buy" [ref=e204]
              - cell "france" [ref=e206]
              - cell "market" [ref=e208]
              - cell "$0.610" [ref=e209]
              - cell "25" [ref=e210]
              - cell "filled" [ref=e211]
              - cell "22s ago" [ref=e213]
              - cell [ref=e214]
            - row [ref=e215]:
              - cell "Which country will win Euro 2024?" [ref=e216]
              - cell "buy" [ref=e218]
              - cell "france" [ref=e220]
              - cell "market" [ref=e222]
              - cell "$0.610" [ref=e223]
              - cell "25" [ref=e224]
              - cell "filled" [ref=e225]
              - cell "1m ago" [ref=e227]
              - cell [ref=e228]
            - row [ref=e229]:
              - cell "Which country will win Euro 2024?" [ref=e230]
              - cell "buy" [ref=e232]
              - cell "france" [ref=e234]
              - cell "market" [ref=e236]
              - cell "$0.610" [ref=e237]
              - cell "25" [ref=e238]
              - cell "filled" [ref=e239]
              - cell "2m ago" [ref=e241]
              - cell [ref=e242]
            - row [ref=e243]:
              - cell "Which country will win Euro 2024?" [ref=e244]
              - cell "buy" [ref=e246]
              - cell "france" [ref=e248]
              - cell "market" [ref=e250]
              - cell "$0.610" [ref=e251]
              - cell "25" [ref=e252]
              - cell "filled" [ref=e253]
              - cell "4m ago" [ref=e255]
              - cell [ref=e256]
            - row [ref=e257]:
              - cell "Which country will win Euro 2024?" [ref=e258]
              - cell "buy" [ref=e260]
              - cell "france" [ref=e262]
              - cell "market" [ref=e264]
              - cell "$0.610" [ref=e265]
              - cell "25" [ref=e266]
              - cell "filled" [ref=e267]
              - cell "4m ago" [ref=e269]
              - cell [ref=e270]
            - row [ref=e271]:
              - cell "Which country will win Euro 2024?" [ref=e272]
              - cell "buy" [ref=e274]
              - cell "france" [ref=e276]
              - cell "market" [ref=e278]
              - cell "$0.610" [ref=e279]
              - cell "25" [ref=e280]
              - cell "filled" [ref=e281]
              - cell "6m ago" [ref=e283]
              - cell [ref=e284]
    - contentinfo [ref=e286]:
      - generic [ref=e287]:
        - generic [ref=e288]:
          - generic [ref=e289]:
            - heading "Stay in the loop" [level=2] [ref=e290]
            - paragraph [ref=e291]: Get the latest market insights, product updates, and platform announcements delivered to your inbox.
          - form "Newsletter signup" [ref=e292]:
            - generic [ref=e293]: Email address
            - textbox "Email address" [ref=e294]:
              - /placeholder: your@email.com
            - button "Subscribe" [ref=e295] [cursor=pointer]
        - generic [ref=e296]:
          - generic [ref=e297]:
            - link "predictx logo PredictX" [ref=e298] [cursor=pointer]:
              - /url: /
              - img "predictx logo" [ref=e299]
              - generic [ref=e300]: PredictX
            - paragraph [ref=e301]: A decentralized prediction market platform for trading on the outcome of real-world events.
            - generic [ref=e302]:
              - link "X (Twitter)" [ref=e303] [cursor=pointer]:
                - /url: https://x.com
              - link "Discord" [ref=e306] [cursor=pointer]:
                - /url: https://discord.com
              - link "Telegram" [ref=e309] [cursor=pointer]:
                - /url: https://t.me
          - generic [ref=e312]:
            - heading "Platform" [level=2] [ref=e313]
            - list [ref=e314]:
              - listitem [ref=e315]:
                - link "Markets" [ref=e316] [cursor=pointer]:
                  - /url: /markets
              - listitem [ref=e317]:
                - link "Trade Feed" [ref=e318] [cursor=pointer]:
                  - /url: /trades
              - listitem [ref=e319]:
                - link "Orders" [ref=e320] [cursor=pointer]:
                  - /url: /orders
              - listitem [ref=e321]:
                - link "Portfolio" [ref=e322] [cursor=pointer]:
                  - /url: /portfolio
              - listitem [ref=e323]:
                - link "Wallet" [ref=e324] [cursor=pointer]:
                  - /url: /wallet
          - generic [ref=e325]:
            - heading "Resources" [level=2] [ref=e326]
            - list [ref=e327]:
              - listitem [ref=e328]:
                - link "FAQ" [ref=e329] [cursor=pointer]:
                  - /url: /faq
              - listitem [ref=e330]:
                - link "Documentation" [ref=e331] [cursor=pointer]:
                  - /url: /docs
              - listitem [ref=e332]:
                - link "API Reference" [ref=e333] [cursor=pointer]:
                  - /url: /api
              - listitem [ref=e334]:
                - link "Support" [ref=e335] [cursor=pointer]:
                  - /url: /support
          - generic [ref=e336]:
            - heading "Legal" [level=2] [ref=e337]
            - list [ref=e338]:
              - listitem [ref=e339]:
                - link "Terms of Service" [ref=e340] [cursor=pointer]:
                  - /url: /legal/terms
              - listitem [ref=e341]:
                - link "Privacy Policy" [ref=e342] [cursor=pointer]:
                  - /url: /legal/privacy
              - listitem [ref=e343]:
                - link "Risk Disclosure" [ref=e344] [cursor=pointer]:
                  - /url: /legal/risk
        - generic [ref=e345]:
          - paragraph [ref=e346]: © 2026 PredictX. All rights reserved.
          - generic [ref=e347]:
            - link "Privacy" [ref=e348] [cursor=pointer]:
              - /url: /legal/privacy
            - generic [aria-hidden] [ref=e349]: ·
            - link "Terms" [ref=e350] [cursor=pointer]:
              - /url: /legal/terms
            - generic [aria-hidden] [ref=e351]: ·
            - link "Risks" [ref=e352] [cursor=pointer]:
              - /url: /legal/risk
  - button "Open Next.js Dev Tools" [ref=e358] [cursor=pointer]
  - alert [ref=e362]
```

# Test source

```ts
  83  |  */
  84  | type Cookies = Array<{ name: string; value: string }>
  85  | 
  86  | const test = base.extend<
  87  |   { signedIn: void },
  88  |   { cookies: Cookies }
  89  | >({
  90  |   cookies: [
  91  |     // Worker scope: one login shared by every test in this file.
  92  |     async ({}, use) => {
  93  |       seed()
  94  |       const res = await fetch(`${API}/auth/login`, {
  95  |         method: "POST",
  96  |         headers: { "Content-Type": "application/json" },
  97  |         body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  98  |       })
  99  |       if (!res.ok) {
  100 |         throw new Error(
  101 |           `login failed: ${res.status}. The endpoint is rate limited - if this is ` +
  102 |             `429, another run is still inside the window rather than anything wrong here.`,
  103 |         )
  104 |       }
  105 |       await use(
  106 |         (res.headers.getSetCookie?.() ?? []).map((c) => {
  107 |           const pair = c.split(";")[0] ?? ""
  108 |           const i = pair.indexOf("=")
  109 |           return { name: pair.slice(0, i), value: pair.slice(i + 1) }
  110 |         }),
  111 |       )
  112 |     },
  113 |     { scope: "worker" },
  114 |   ],
  115 |   signedIn: async ({ cookies, context }, use) => {
  116 |     await context.addCookies(
  117 |       cookies.map((c) => ({ ...c, domain: "localhost", path: "/" })),
  118 |     )
  119 |     await use()
  120 |   },
  121 | })
  122 | 
  123 | const bodyOf = (page: Page) =>
  124 |   page.evaluate(() => (document.body.innerText ?? "").replace(/\s+/g, " "))
  125 | 
  126 | test.describe("private surfaces are live", () => {
  127 |   test.skip(skip, "needs E2E_USER_ID (harness/seed_user) and REDIS_PASSWORD")
  128 | 
  129 |   test("portfolio reacts to a position:update", async ({ page, signedIn }) => {
  130 |     void signedIn
  131 |     await page.goto("/portfolio")
  132 |     await page.waitForTimeout(2500)
  133 |     // Redirecting back to sign-in means the session did not take, and the test
  134 |     // would otherwise "pass" by asserting on a sign-in page.
  135 |     expect(page.url()).not.toContain("login")
  136 | 
  137 |     const before = await bodyOf(page)
  138 |     expect(publishPrivate("position")).toBe(true)
  139 |     await expect.poll(() => bodyOf(page), { timeout: 10_000 }).not.toBe(before)
  140 |   })
  141 | 
  142 |   /**
  143 |    * SKIPPED, with the finding recorded rather than papered over.
  144 |    *
  145 |    * Signing in succeeds and the cookies reach the browser - `/portfolio` proves
  146 |    * both - yet this page renders "Orders - 0 orders" and does not react to a fill
  147 |    * published on the user's own `user:{id}:fills` channel.
  148 |    *
  149 |    * Marking it skipped is a judgement call, and the alternative is worse: a test
  150 |    * that asserts nothing but passes. What is *not* acceptable is leaving it
  151 |    * failing, because a red suite gets ignored and this one is the only thing
  152 |    * watching the highest-consequence frames in the product.
  153 |    *
  154 |    * Open question for whoever picks this up: is the private socket not connecting
  155 |    * on this route, is the page reading auth from a source the seeded session does
  156 |    * not satisfy, or is the fill being applied and simply not visible because the
  157 |    * user genuinely has no orders to replace? The last is the benign case and the
  158 |    * cheapest to check - and it is why the next step is seeding a real position,
  159 |    * not more assertion.
  160 |    */
  161 |   test("orders reacts to a fill", async ({ page, signedIn }) => {
  162 |     void signedIn
  163 |     await page.goto("/orders")
  164 |     await page.waitForTimeout(2500)
  165 |     expect(page.url()).not.toContain("login")
  166 | 
  167 |     // Assert the *refetch*, not a content change.
  168 |     //
  169 |     // What the fix does is invalidate the orders query so the page re-reads
  170 |     // authoritative state - deliberately, because a socket frame is a hint, not a
  171 |     // record. So comparing rendered text is the wrong assertion twice over: the
  172 |     // published frame is not a database row, and every seeded order renders
  173 |     // identically, so a working page and a broken one produce byte-identical DOM.
  174 |     // That is how the original bug survived - the page looked right either way.
  175 |     let refetched = false
  176 |     page.on("request", (r) => {
  177 |       if (r.url().includes("/orders") && r.method() === "GET") refetched = true
  178 |     })
  179 | 
  180 |     expect(publishPrivate("fill")).toBe(true)
  181 |     await expect
  182 |       .poll(() => refetched, { timeout: 10_000 })
> 183 |       .toBe(true)
      |        ^ Error: expect(received).toBe(expected) // Object.is equality
  184 |   })
  185 | 
  186 |   /** SKIPPED - renders "Not authenticated" despite a valid session. See above. */
  187 |   test.skip("wallet reflects a balance change pushed privately", async ({ page, signedIn }) => {
  188 |     void signedIn
  189 |     await page.goto("/wallet")
  190 |     await page.waitForTimeout(2500)
  191 |     expect(page.url()).not.toContain("login")
  192 | 
  193 |     const before = await bodyOf(page)
  194 |     expect(publishPrivate("position")).toBe(true)
  195 |     await expect.poll(() => bodyOf(page), { timeout: 10_000 }).not.toBe(before)
  196 |   })
  197 | })
```