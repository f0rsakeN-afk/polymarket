"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { redirect } from "next/navigation"
import { ShieldAlert, Users, Scale, ScrollText } from "lucide-react"

import { useCurrentUser } from "@/hooks/use-auth"
import { Spinner } from "@workspace/ui/components/spinner"
import { cn } from "@workspace/ui/lib/utils"

const SECTIONS = [
  { href: "/admin/users", icon: Users, label: "Users" },
  { href: "/admin/markets", icon: Scale, label: "Moderation" },
  { href: "/admin/audit", icon: ScrollText, label: "Audit trail" },
]

/**
 * Admin shell.
 *
 * ## The gate is a redirect, not a hidden nav
 *
 * Non-admins are sent to `/` rather than shown an empty page. That matters
 * because the API enforces admin itself - this is not the security boundary, it
 * is not showing someone a navigation they cannot use. A 403 with the nav still
 * rendered reads as "the app is broken for admins", which is a support ticket
 * and a bad first impression of an operator tool.
 *
 * ## Deliberately not a route group
 *
 * `/admin` sits outside the `(app)` group so it does not inherit the consumer
 * header, footer and mobile navigation. An operator running disputes is not a
 * user browsing markets, and giving them the storefront chrome would waste the
 * screen on everything they are not doing.
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
    redirect("/")
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
        </div>
      </header>
      <main className="container mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        {children}
      </main>
    </div>
  )
}