"use client"

import { Button } from "@workspace/ui/components/button"

/**
 * The route-level error boundary.
 *
 * `retry()` rather than `reset()`: `reset()` clears the error and re-renders the
 * children *without re-fetching*, so a "Try again" button wired to it re-renders
 * the same failed state and the button appears to do nothing. `retry()` re-fetches
 * and, if the fetch succeeds, swaps the error for the real page.
 *
 * The message is rendered as given, which is the right call here because Next
 * already replaces server-component error messages with a digest-bearing generic
 * string in production - only errors originating in client components keep their
 * text, and those are the ones safe to show an operator.
 */
export default function GlobalError({
  error,
  retry,
}: {
  error: Error & { digest?: string }
  retry: () => void
}) {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center px-4 py-16 text-center">
      <h2 className="text-lg font-semibold">Something went wrong</h2>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        {error.message || "An unexpected error occurred. Please try again."}
      </p>
      {error.digest ? (
        <p className="mt-2 font-mono text-xs text-muted-foreground">
          Reference: {error.digest}
        </p>
      ) : null}
      <Button variant="outline" size="sm" onClick={() => retry()} className="mt-6">
        Try again
      </Button>
    </div>
  )
}