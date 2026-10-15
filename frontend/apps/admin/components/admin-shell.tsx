"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Gavel, Landmark, LogOut, Monitor, Moon, Scale, ScrollText, ShieldAlert, Users } from "lucide-react"
import { sileo } from "sileo"

import { useTheme } from "next-themes"

import { useCurrentUser } from "@/hooks/use-auth"
import { api } from "@workspace/api-client/client"
import { Spinner } from "@workspace/ui/components/spinner"
import { Button, buttonVariants } from "@workspace/ui/components/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@workspace/ui/components/dropdown-menu"
import { cn } from "@workspace/ui/lib/utils"

const SECTIONS = [
  { href: "/users", icon: Users, label: "Users" },
  { href: "/disputes", icon: Gavel, label: "Disputes" },
  { href: "/markets", icon: Scale, label: "Moderation" },
  { href: "/treasury", icon: Landmark, label: "Treasury" },
  { href: "/audit", icon: ScrollText, label: "Audit trail" },
]

/**
 * The gate, the chrome, and the way out.
 *
 * ## Not a redirect when there is nowhere to go
 *
 * A non-admin is sent to `NEXT_PUBLIC_SITE_URL` when it is set, and shown an
 * explicit "no access" state when it is not. The obvious alternative - redirect to
 * `/` - is an **infinite loop**: this app *has* an index, and its index sends a
 * non-admin to `/` as well, so `/users` → `/` → `/` → … until the browser gives
 * up. My first version did exactly that, on the stated reasoning that "there is
 * no index here to fall back to", which was simply wrong about the app's own
 * routing.
 *
 * Failing closed with a sentence beats failing open into a spin, and a redirect
 * whose destination depends on configuration is a redirect whose behaviour
 * depends on something the operator cannot see.
 */
function NoAccess() {
  return (
    <div className="flex min-h-dvh items-center justify-center px-4">
      <div className="max-w-md space-y-4 text-center">
        <ShieldAlert className="mx-auto size-8 text-destructive" />
        <h1 className="text-lg font-semibold">Admin access required</h1>
        <p className="text-sm text-muted-foreground">
          This account does not have admin access, so there is nothing to show
          here.
        </p>
        <p className="text-xs text-muted-foreground">
          If that is unexpected, ask an existing admin to check your role — the
          attempt is recorded in the audit trail.
        </p>
        <Button variant="outline" size="sm" className="w-full">
          <a href={process.env.NEXT_PUBLIC_SITE_URL ?? "/"}>Go to the site</a>
        </Button>
      </div>
    </div>
  )
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme()
  const next = resolvedTheme === "dark" ? "light" : "dark"
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
    >
      <Monitor className="size-3.5 dark:hidden" aria-hidden />
      <Moon className="hidden size-3.5 dark:block" aria-hidden />
    </Button>
  )
}

/**
 * The shell: gate, nav, identity, and an exit.
 *
 * Sign-out is here rather than buried because an operator tool is used on shared
 * and borrowed machines, and "who was in this session" has to be answerable by
 * the person sitting at the keyboard. The web app can afford to leave logout in a
 * user menu three clicks deep; this surface should not.
 */
export function AdminShell({ children }: { children: React.ReactNode }) {
  const { data: user, isLoading } = useCurrentUser()
  const pathname = usePathname()
  const qc = useQueryClient()

  const signOut = useMutation({
    mutationFn: () => api.post("/api/v1/auth/logout"),
    // The local session ends whether or not the server confirms it, so this is
    // `finally`, not `then` - a logout that fails server-side must still clear
    // this machine.
    onSettled: () => {
      qc.clear()
      sileo.success({ title: "Signed out" })
      window.location.href = process.env.NEXT_PUBLIC_SITE_URL ?? "/"
    },
  })

  if (isLoading) {
    return (
      <div className="flex min-h-dvh items-center justify-center" role="status">
        <Spinner className="size-5" />
        <span className="sr-only">Checking admin access…</span>
      </div>
    )
  }

  if (!user?.is_admin) return <NoAccess />

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#admin-main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:ring-2 focus:ring-ring"
      >
        Skip to main content
      </a>

      <header className="sticky top-0 z-30 border-b bg-card/95 backdrop-blur">
        <div className="container mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
          <Link href="/" className="flex items-center gap-2">
            <ShieldAlert className="size-4 text-destructive" />
            <span className="text-sm font-semibold">Admin</span>
          </Link>

          <nav className="flex items-center gap-1" aria-label="Admin sections">
            {SECTIONS.map(({ href, icon: Icon, label }) => {
              const active = pathname === href || pathname?.startsWith(`${href}/`)
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
                    active
                      ? "bg-accent font-medium text-foreground"
                      : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                  )}
                >
                  <Icon className="size-3.5" aria-hidden />
                  {label}
                </Link>
              )
            })}
          </nav>

          <div className="ml-auto flex items-center gap-1">
            <ThemeToggle />
            {/* Base UI's trigger renders its own button and takes no `asChild`,
                unlike the Radix API this component's naming suggests. */}
            <DropdownMenu>
              <DropdownMenuTrigger
                className="rounded-md px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                aria-label="Account menu"
              >
                {user.email}
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <div className="px-2 py-1.5">
                  <p className="text-sm font-medium">{user.username}</p>
                  <p className="text-xs text-muted-foreground">admin</p>
                </div>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onSelect={() => signOut.mutate()}
                  disabled={signOut.isPending}
                >
                  <LogOut className="size-3.5" />
                  {signOut.isPending ? "Signing out…" : "Sign out"}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>

      <main id="admin-main" tabIndex={-1} className="container mx-auto w-full max-w-7xl flex-1 px-4 py-6 outline-none">
        {children}
      </main>
    </div>
  )
}