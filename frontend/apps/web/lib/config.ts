/**
 * Re-exported from `@workspace/api-client`.
 *
 * The origin normalisation lives in the package because `apps/admin` needs the
 * identical value - a misconfigured `NEXT_PUBLIC_API_URL` has to be corrected the
 * same way in both apps, or the operator tool ends up talking to a different
 * origin than the storefront it was built to administer.
 *
 * This file keeps the ~11 existing `@/lib/config` imports (and the two test
 * mocks of it) working unchanged.
 */
export * from "@workspace/api-client/config"