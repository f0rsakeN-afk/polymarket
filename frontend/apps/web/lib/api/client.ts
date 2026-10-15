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