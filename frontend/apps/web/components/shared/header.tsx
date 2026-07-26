"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useCallback, useEffect, useState, memo } from "react"
import { cn } from "@workspace/ui/lib/utils"
import { Sheet, SheetContent, SheetTrigger } from "@workspace/ui/components/sheet"
import { MenuIcon, SunIcon, MoonIcon } from "lucide-react"
import { useTheme } from "next-themes"

const navLinks = [
  { href: "/", label: "Markets" },
  { href: "/trades", label: "Trade Feed" },
  { href: "/orders", label: "Orders" },
  { href: "/portfolio", label: "Portfolio" },
]

// ── Theme Toggle ───────────────────────────────────────────────────────────────

const ThemeToggle = memo(function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)

  useEffect(() => { setMounted(true) }, [])

  const handleToggle = useCallback(() => {
    setTheme(resolvedTheme === "dark" ? "light" : "dark")
  }, [resolvedTheme, setTheme])

  if (!mounted) {
    return <div className="size-8" />
  }

  return (
    <button
      onClick={handleToggle}
      className="flex items-center justify-center size-8 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
      title="Toggle theme"
      aria-label="Toggle theme"
    >
      {resolvedTheme === "dark"
        ? <SunIcon className="size-4" />
        : <MoonIcon className="size-4" />
      }
    </button>
  )
})

// ── Polygon Logo ──────────────────────────────────────────────────────────────

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

// ── Nav Link ──────────────────────────────────────────────────────────────────

const NavLink = memo(function NavLink({
  href, label, isActive,
}: {
  href: string
  label: string
  isActive: boolean
}) {
  return (
    <Link
      href={href}
      className={cn(
        "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
        isActive
          ? "bg-primary/10 text-primary"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      {label}
    </Link>
  )
})

// ── Header ───────────────────────────────────────────────────────────────────

function Header() {
  const pathname = usePathname()

  const isActive = useCallback((href: string) => {
    return href === "/" ? pathname === "/" : pathname.startsWith(href)
  }, [pathname])

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur">
      <div className="container mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2 font-bold tracking-wide">
          <PolygonIcon />
          <span>POLYMARKET</span>
        </Link>

        {/* Nav */}
        <nav className="hidden items-center gap-1 sm:flex">
          {navLinks.map(({ href, label }) => (
            <NavLink
              key={href}
              href={href}
              label={label}
              isActive={isActive(href)}
            />
          ))}
        </nav>

        {/* Right */}
        <div className="flex items-center gap-2">
          <ThemeToggle />

          <Link
            href="/portfolio"
            className="hidden rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted sm:block"
          >
            Portfolio
          </Link>
          <Link
            href="/wallet"
            className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Connect Wallet
          </Link>

          {/* Mobile menu */}
          <Sheet>
            <SheetTrigger className="sm:hidden" render={
              <button className="text-muted-foreground hover:text-foreground transition-colors">
                <MenuIcon className="size-5" />
              </button>
            } />
            <SheetContent side="right" className="w-64 p-0">
              <nav className="flex flex-col p-6 gap-1">
                {navLinks.map(({ href, label }) => (
                  <NavLink
                    key={href}
                    href={href}
                    label={label}
                    isActive={isActive(href)}
                  />
                ))}
                <div className="mt-4 pt-4 border-t border-border">
                  <Link
                    href="/wallet"
                    className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 text-center block"
                  >
                    Connect Wallet
                  </Link>
                </div>
              </nav>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </header>
  )
}

export default Header
