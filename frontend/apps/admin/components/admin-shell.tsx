"use client"

/**
 * The shell: the gate, the rail, and the page area.
 *
 * ## The gate stays client-side, and `proxy.ts` does not replace it
 *
 * Worth restating because "the proxy handles it, delete the gate" is the obvious
 * next step and it would be wrong. The proxy decides from a cookie it can read;
 * this decides from a live `/auth/me`. They fail differently — a `Set-Cookie`
 * replay that did not land, a `matcher` that missed a prefix, an admin flag
 * revoked mid-session — and each of those failures leaves the operator looking at
 * an admin UI. The second opinion costs nothing when it is right.
 *
 * ## Two states, not one
 *
 * A signed-out operator and a signed-in non-admin are different problems with
 * different fixes, and showing them the same screen makes one of them
 * unactionable. Told "admin access required" when they are merely not signed in,
 * an operator's only move is to ask someone for access they did not need.
 *
 * The distinction is `user` rather than `user?.is_admin`, because the gate cannot
 * tell "not an admin" from "not signed in" by looking at a failed check alone —
 * both arrive as an absent `is_admin`.
 *
 * ## Responsiveness
 *
 * Below `md` the rail is an overlay with its own trigger in a sticky bar; from
 * `md` it is a collapsible rail beside the content. The trigger is the
 * `SidebarTrigger` from the shared component rather than a hand-rolled button, so
 * its `aria-expanded`/`aria-controls` stay correct without anyone maintaining
 * them.
 */

import Link from "next/link"
import { useEffect, useState } from "react"
import { ShieldAlert } from "lucide-react"

import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@workspace/ui/components/sidebar"
import { buttonVariants } from "@workspace/ui/components/button"
import { Spinner } from "@workspace/ui/components/spinner"
import { cn } from "@workspace/ui/lib/utils"

import { storefrontUrl } from "@/lib/site-url"
import { useCurrentUser } from "@/hooks/use-auth"
import { AdminSidebar, ThemeToggle } from "@/components/admin-sidebar"

export function AdminShell({ children }: { children: React.ReactNode }) {
  const { data: user, isLoading, isError, error } = useCurrentUser()
  const [open, onOpenChange] = useSidebarState()

  if (isLoading) {
    return (
      <div className="flex min-h-dvh items-center justify-center" role="status">
        <Spinner className="size-5" />
        <span className="sr-only">Checking admin access…</span>
      </div>
    )
  }

  // A transport failure is not "not an admin". Saying so would tell an operator
  // their account was revoked when the API was simply unreachable — and the fix
  // (retry) is not what they would go and do.
  if (isError && !isUnauthorizedError(error)) {
    return <GateError />;
  }

  if (!user?.is_admin) return <NoAccess signedIn={Boolean(user)} />;

  return (
    // Controlled, so the operator's choice survives a reload.
    //
    // `SidebarProvider` writes `sidebar_state` on every toggle but only ever
    // *reads* `defaultOpen`, which is a constant — so left alone the rail snaps
    // back open on every full page load, and an operator who collapsed it to read
    // a wide audit row gets it back in their face on refresh. Reading the cookie
    // in an effect rather than during render keeps the server and client markup
    // identical; deciding it during render is a hydration mismatch on every load.
    <SidebarProvider open={open} onOpenChange={onOpenChange}>
      {/* First focusable thing on the page, and the reason the rail is usable
          with a keyboard. Tab once and you are past eight links and two group
          headings to reach the content. It is invisible until focused, which is
          the only time it is wanted. */}
      <a
        href="#admin-main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:shadow-lg focus:ring-2 focus:ring-ring"
      >
        Skip to main content
      </a>

      <AdminSidebar user={user} />

      <SidebarInset className="min-w-0">
        {/* Visible below `md`, where the rail is an overlay and there would
            otherwise be no way to open it. `sticky` so it stays reachable after
            scrolling a long queue — the one thing an operator needs mid-scroll is
            a way back to navigation. */}
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b bg-background/95 px-4 backdrop-blur md:hidden">
          <SidebarTrigger
            aria-label="Open navigation"
            className="-ml-1"
          />
          <span className="truncate text-sm font-semibold">PredictX Admin</span>
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </header>

        <div
          id="admin-main"
          tabIndex={-1}
          className="flex-1 px-4 py-5 outline-none sm:px-6 lg:px-8"
        >
          {/* `min-w-0` matters more than it looks: a wide table inside a flex
              child without it forces the whole page to scroll sideways instead
              of just the table's own container. `mx-auto` + a max width keeps a
              40-column audit row readable on a 27-inch monitor instead of
              stretching to the bezel. */}
          <div className="mx-auto w-full min-w-0 max-w-[1600px]">{children}</div>
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}

/**
 * Read the operator's rail preference back out of the cookie the provider writes.
 *
 * `SidebarProvider` owns writing it; this only has to agree on the initial value.
 * Starts expanded on both server and client so the first render matches, then
 * corrects itself in an effect — the alternative is a hydration mismatch on every
 * single page load for anyone who has ever collapsed the rail.
 */
const SIDEBAR_COOKIE = "sidebar_state";

function useSidebarState(): [boolean, (next: boolean) => void] {
  const [open, setOpen] = useState(true)

  useEffect(() => {
    const stored = document.cookie
      .split("; ")
      .find((c) => c.startsWith(`${SIDEBAR_COOKIE}=`))
      ?.split("=")[1];
    if (stored === "false") setOpen(false);
  }, []);

  return [open, setOpen];
}

function isUnauthorizedError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    (error as { status: number }).status === 401
  );
}

function NoAccess({ signedIn }: { signedIn: boolean }) {
  return (
    <div className="flex min-h-dvh items-center justify-center px-4">
      <div className="max-w-md space-y-4 text-center">
        <ShieldAlert className="mx-auto size-8 text-destructive" aria-hidden />
        <h1 className="text-lg font-semibold">
          {signedIn ? "Admin access required" : "Sign in to continue"}
        </h1>
        <p className="text-sm text-muted-foreground">
          {signedIn
            ? "This account does not have admin access, so there is nothing to show here."
            : "You are not signed in. Admin access is granted per account."}
        </p>

        <div className="flex flex-col gap-2">
          <Link
            href="/login"
            className={cn(
              buttonVariants({ variant: signedIn ? "outline" : "default" }),
              "w-full"
            )}
          >
            {signedIn ? "Sign in as someone else" : "Sign in"}
          </Link>
          {/* Only when a storefront is actually configured. The old fallback was
              `?? "/"`, which on this origin is this app's own root — so the link
              sent operators back through the proxy to the login page, and
              `siteUrl` in the config package falls back to the *API* origin, so
              the other spelling sent them to a JSON response. */}
          {storefrontUrl() ? (
            <a
              href={storefrontUrl() as string}
              className={cn(buttonVariants({ variant: "ghost" }), "w-full")}
            >
              Go to the site
            </a>
          ) : null}
        </div>

        <p className="text-xs text-muted-foreground">
          {signedIn
            ? "If that is unexpected, ask an existing admin to check your role — the attempt is recorded in the audit trail."
            : "Signing in here does not sign you in anywhere else."}
        </p>
      </div>
    </div>
  );
}

/**
 * The API is unreachable.
 *
 * Separate from "not an admin" on purpose. Conflating them tells an operator
 * their permissions changed when the network did — and they go looking for a
 * policy problem instead of retrying.
 */
function GateError() {
  return (
    <div className="flex min-h-dvh items-center justify-center px-4">
      <div className="max-w-md space-y-4 text-center">
        <ShieldAlert className="mx-auto size-8 text-amber-600" aria-hidden />
        <h1 className="text-lg font-semibold">Could not verify your access</h1>
        <p className="text-sm text-muted-foreground">
          The API did not respond. This is not a permissions problem — your access
          has not been evaluated either way.
        </p>
        {/* `buttonVariants` on a real `Link`, not `Button render={<Link/>}`.

            Base UI's `Button` assumes a `<button>`: pointed at an anchor it either
            logs a mismatch error or stamps `role="button"` onto it, and a link
            that announces itself as a button stops being findable in a screen
            reader's list of links and stops inviting open-in-new-tab. Styling the
            anchor directly gives identical appearance with correct semantics. */}
        <Link
          href="/"
          className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-full")}
        >
          Try again
        </Link>
      </div>
    </div>
  );
}