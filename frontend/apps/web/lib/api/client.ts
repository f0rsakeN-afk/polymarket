/**
 * Re-exported from `@workspace/api-client`.
 *
 * The transport now lives in a package because two apps need it and a copy in
 * each is a copy that drifts: the session-refresh machinery, the pending-request
 * deduplication and the `ApiError` shape are exactly the code that has to be
 * identical in the consumer site and the operator tool, and the moment they
 * differ a session behaves differently in one and not the other.
 *
 * This file exists so the ~40 existing `@/lib/api/client` imports keep working
 * unchanged. New code in `apps/web` may import the package directly.
 */
export * from "@workspace/api-client/client"

import { configureAuthRouting } from "@workspace/api-client/client"

/**
 * This app's route policy, declared once.
 *
 * The package's default is an empty public list — it cannot know what this app's
 * routes are called, and guessing is what put the storefront's route names inside
 * a module the admin app also imports. `/markets` here and `/markets` in the
 * moderation queue are different pages; a shared hardcoded list silently made the
 * admin one exempt from the session-expired redirect.
 *
 * Declared as a module side effect because every request in this app goes through
 * `@/lib/api/client`, and this file is the single funnel it comes through. A
 * `useEffect` or a provider would leave the first request of a page load with the
 * wrong policy, and that first request is usually the one that discovers the
 * session is gone.
 */
configureAuthRouting({
  publicPaths: ["/", "/markets", "/trades", "/faq", "/docs", "/legal", "/support"],
  loginPath: "/login",
})