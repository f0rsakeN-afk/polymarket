"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useCallback, useSyncExternalStore, memo } from "react"
import { cn } from "@workspace/ui/lib/utils"
import { Sheet, SheetContent, SheetTrigger } from "@workspace/ui/components/sheet"
import { MenuIcon, SunIcon, MoonIcon } from "lucide-react"
import { useTheme } from "next-themes"
import { UserMenu } from "@/components/auth/user-menu"
import { NotificationBell } from "@/components/notifications/notification-bell"
import { SearchInput } from "@/components/shared/search-input"

const navLinks: { href: string; label: string }[] = [
  // { href: "/", label: "Markets" },
  // { href: "/trades", label: "Trade Feed" },
  // { href: "/orders", label: "Orders" },
  // { href: "/portfolio", label: "Portfolio" },
]

// ── Theme Toggle ────────────────────────────────────────────────────────────────

const ThemeToggle = memo(function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme()
  const mounted = useSyncExternalStore(() => () => {}, () => true, () => false)

  const handleToggle = useCallback(() => {
    setTheme(resolvedTheme === "dark" ? "light" : "dark")
  }, [resolvedTheme, setTheme])

  if (!mounted) return <div className="size-8" />

  return (
    <button
      onClick={handleToggle}
      className="flex items-center justify-center size-8 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
      title="Toggle theme"
      aria-label="Toggle theme"
    >
      {resolvedTheme === "dark" ? <SunIcon className="size-4" /> : <MoonIcon className="size-4" />}
    </button>
  )
})

// ── Polygon Logo ───────────────────────────────────────────────────────────────

const PolygonIcon = memo(function PolygonIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="shrink-0">
      <path
        d="M10 1L18.5 6.5V15.5L10 21L1.5 15.5V6.5L10 1Z"
        stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" fill="none"
      />
      <path
        d="M10 1V21M1.5 6.5L18.5 6.5M1.5 15.5L18.5 15.5"
        stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"
      />
    </svg>
  )
})

// ── Nav Link ───────────────────────────────────────────────────────────────────

const NavLink = memo(function NavLink({ href, label, isActive }: { href: string; label: string; isActive: boolean }) {
  return (
    <Link
      href={href}
      aria-current={isActive ? "page" : undefined}
      className={cn(
        "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
        isActive ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      {label}
    </Link>
  )
})

// ── Header ─────────────────────────────────────────────────────────────────────

export default function Header() {
  const pathname = usePathname()

  const isActive = useCallback(
    (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href)),
    [pathname]
  )

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur">
      <div className="container mx-auto flex h-14 max-w-7xl items-center px-4">
        {/* Left: Logo + Search */}
        <div className="flex items-center gap-4 flex-1 min-w-0">
          <Link href="/" className="flex items-center gap-2 font-bold tracking-wide shrink-0">
            <PolygonIcon />
            <span>PredictX</span>
          </Link>
          <div className="relative w-full max-w-xs">
            <SearchInput />
          </div>
        </div>

        {/* Right: Theme + Bell + User */}
        <div className="flex items-center gap-2 shrink-0">
          <ThemeToggle />
          <NotificationBell />
          <UserMenu />

          {/* Mobile menu */}
          <Sheet>
            <SheetTrigger className="sm:hidden inline-flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors">
              <MenuIcon className="size-5" />
            </SheetTrigger>
            <SheetContent side="right" className="w-64 p-0">
              <nav className="flex flex-col p-6 gap-1">
                {navLinks.map(({ href, label }) => (
                  <NavLink key={href} href={href} label={label} isActive={isActive(href)} />
                ))}
              </nav>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </header>
  )
}
