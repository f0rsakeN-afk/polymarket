"use client"

import Link from "next/link"
import { redirect, usePathname } from "next/navigation"
import { Scale, ScrollText, ShieldAlert, Users } from "lucide-react"

import { useCurrentUser } from "@/hooks/use-auth"
import { Spinner } from "@workspace/ui/components/spinner"
import { cn } from "@workspace/ui/lib/utils"

const SECTIONS = [
  { href: "/users", icon: Users, label: "Users" },
  { href: "/markets", icon: Scale, label: "Moderation" },
  { href: "/audit", icon: ScrollText, label: "Audit trail" },
]

/**
 * The admin shell: gate, then chrome.
 *
 * ## The gate is a redirect, not a hidden nav
 *
 * Non-admins are sent to the API origin rather than shown an empty page. That
 * matters because the API enforces admin itself - this is not the security
 * boundary, it is not showing someone a navigation they cannot use. A 403 with
 * the nav still rendered reads as "the app is broken for admins", which is a
 * support ticket and a bad first impression of an operator tool.
 *
 * ## Why this app has no header, footer or footer nav
 *
 * An operator running a dispute queue is not a user browsing markets, and
 * inheriting the storefront chrome would spend the screen on everything they are
 * not doing. That, along with a separate CSP that permits no websocket, is what
 * a separate deployable buys.
 */
export function AdminShell({ children }: { children: React.ReactNode }) {
  const { data: user, isLoading } = useCurrentUser()
  const pathname = usePathname()

  if (isLoading) {
    return (
      <div className="flex min-h-dvh items-center justify-center" role="status">
        <Spinner className="size-5" />
        <span className="sr-only">Checking admin access…</span>
      </div>
    )
  }

  if (!user?.is_admin) {
    // Outbound, not `/`: there is no index here to fall back to, and a redirect
    // to a 404 inside an operator tool is just a worse dead end.
    redirect(process.env.NEXT_PUBLIC_SITE_URL ?? "/")
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b bg-card">
        <div className="container mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
          <div className="flex items-center gap-2">
            <ShieldAlert className="size-4 text-destructive" />
            <span className="text-sm font-semibold">Admin</span>
          </div>
          <nav className="flex items-center gap-1" aria-label="Admin sections">
            {SECTIONS.map(({ href, icon: Icon, label }) => {
              const active = pathname?.startsWith(href)
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
                  <Icon className="size-3.5" />
                  {label}
                </Link>
              )
            })}
          </nav>
          <span className="ml-auto text-xs text-muted-foreground">
            {user.email}
          </span>
        </div>
      </header>
      <main className="container mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        {children}
      </main>
    </div>
  )
}