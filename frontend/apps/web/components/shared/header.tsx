"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  useCallback,
  useState,
  useSyncExternalStore,
  memo,
} from "react"
import { cn } from "@workspace/ui/lib/utils"
import {
  Sheet,
  SheetContent,
  SheetTrigger,
  SheetTitle,
  SheetHeader,
  SheetDescription,
  SheetFooter,
} from "@workspace/ui/components/sheet"
import {
  MenuIcon,
  SunIcon,
  MoonIcon,
  HomeIcon,
  TrendingUpIcon,
  ActivityIcon,
  HelpCircleIcon,
} from "lucide-react"
import { useTheme } from "next-themes"
import { UserMenu } from "@/components/auth/user-menu"
import { NotificationBell } from "@/components/notifications/notification-bell"
import { SearchInput } from "@/components/shared/search-input"
import { AppCommandMenu } from "@/components/shared/app-command-menu"

const navLinks: { href: string; label: string; icon: React.ReactNode }[] = [
  { href: "/markets", label: "Markets", icon: <TrendingUpIcon className="size-4" aria-hidden="true" /> },
  { href: "/trades", label: "Trades", icon: <ActivityIcon className="size-4" aria-hidden="true" /> },
]

// ── Theme Toggle ────────────────────────────────────────────────────────────────

const ThemeToggle = memo(function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme()
  const mounted = useSyncExternalStore(() => () => {}, () => true, () => false)

  const handleToggle = useCallback(() => {
    setTheme(resolvedTheme === "dark" ? "light" : "dark")
  }, [resolvedTheme, setTheme])

  // Reserves the button's footprint pre-hydration so the header doesn't shift
  // when the real control mounts.
  if (!mounted) return <div className="size-9 shrink-0" aria-hidden="true" />

  return (
    <button
      onClick={handleToggle}
      // size-9 keeps this in line with the other 36px icon controls. It was
      // size-8, which is a 32px target - under the 44px guideline.
      className="inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
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
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="shrink-0" aria-hidden="true">
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
        // border-b on the element itself, not an absolutely-positioned span with
        // hardcoded `left-3 right-3`. The old underline was correct only because
        // the horizontal padding happened to be 0.75rem; changing the padding
        // would have left it visibly offset. A border tracks the box for free.
        "-mb-px border-b-2 px-3 py-1.5 text-xs font-medium transition-colors duration-200",
        isActive
          ? "border-primary text-primary"
          : "border-transparent text-muted-foreground hover:text-foreground"
      )}
    >
      {label}
    </Link>
  )
})

// ── Mobile Nav Link ─────────────────────────────────────────────────────────────

/**
 * Drawer row. Deliberately not the desktop NavLink: that one is an underline
 * tab sized for a horizontal bar, which reads as broken once stacked vertically.
 * This is a full-width row with an icon, a filled active state, and a real
 * 44px-tall target.
 */
const MobileNavLink = memo(function MobileNavLink({
  href,
  label,
  icon,
  isActive,
  onNavigate,
}: {
  href: string;
  label: string;
  icon: React.ReactNode;
  isActive: boolean;
  onNavigate: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={isActive ? "page" : undefined}
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
        isActive
          ? "bg-primary/10 text-primary"
          : "text-foreground hover:bg-muted active:bg-muted"
      )}
    >
      <span className="shrink-0 text-muted-foreground">{icon}</span>
      {label}
    </Link>
  );
});

// ── Header ─────────────────────────────────────────────────────────────────────

export default function Header() {
  const pathname = usePathname()
  // The route the drawer was opened on. "Open" means the route has not changed
  // since that snapshot, so navigating always closes it. Derived rather than a
  // boolean in state: an effect that closed it on pathname change was flagged by
  // react-hooks/set-state-in-effect, and keeping a second copy of "am I open" is
  // what let the sheet stay mounted over a new route in the first place.
  const [menuPathname, setMenuPathname] = useState<string | null>(null)

  const isActive = useCallback(
    (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href)),
    [pathname]
  )

  const openMenu = useCallback(() => setMenuPathname(pathname), [pathname])
  const closeMenu = useCallback(() => setMenuPathname(null), [])
  const menuOpen = menuPathname !== null && menuPathname === pathname

  return (
    // `isolate` gives the header its own stacking context, so a z-50 dialog or
      // dropdown opened from it can never paint *behind* the bar. `backdrop-blur`
      // alone leaves the header translucent, which is why the fill is raised to
      // /85 (and to /70 once blur is unsupported, where translucency would
      // otherwise leave the content behind it unreadable).
      <header
        data-testid="app-header"
        className="sticky top-0 z-40 isolate border-b border-border bg-background/85 backdrop-blur-md supports-[not(backdrop-filter:blur(0))]:bg-background"
      >
      <div className="container mx-auto flex h-14 max-w-7xl items-center px-4">
        {/* Brand. Shrinks its label away on the narrowest phones so the wordmark
            never truncates mid-word or forces the controls off-screen. */}
        {/*
          Three visual groups, left to right: brand, nav, then controls.

          The nav sits directly beside the brand and the search moved into the
          right cluster. It used to be brand | search | nav | icons, which left
          the search floating in dead space and pressed the nav flush against
          the icon cluster so "Trades" read as part of the same group as the
          theme toggle. Brand + nav together is the conventional SaaS grouping
          (Linear, Vercel, Stripe).

          `gap-1` + `ml-1` on the nav is what creates the separation between the
          left group and the right one; without an explicit gap the two groups
          merge visually at any width where the search field is short.
        */}
        <div className="flex shrink-0 items-center gap-2">
          <Link
            href="/"
            className="flex shrink-0 items-center gap-2 font-bold tracking-wide"
            aria-label="PredictX home"
          >
            <PolygonIcon />
            <span className="hidden min-[380px]:inline">PredictX</span>
          </Link>

          {/* Desktop nav. Sits inline with the brand, so the underline touches
              the bar's bottom edge like a proper tab. */}
          <nav aria-label="Primary" className="hidden items-center gap-1 md:flex">
            {navLinks.map(({ href, label }) => (
              <NavLink key={href} href={href} label={label} isActive={isActive(href)} />
            ))}
          </nav>
        </div>

        {/* Controls, pushed right. */}
        <div className="ml-auto flex shrink-0 items-center gap-0.5 sm:gap-1">
          {/* Search joins the control cluster. Hidden below md, where the bar has
              neither the room nor the keyboard; the drawer covers those sizes. */}
          <div className="relative mr-1 hidden w-44 shrink-0 lg:block xl:w-64">
            <SearchInput />
          </div>

          <AppCommandMenu />
          <ThemeToggle />
          <NotificationBell />
          <UserMenu />

          {/* Mobile menu */}
          <Sheet open={menuOpen} onOpenChange={(open) => (open ? openMenu() : closeMenu())}>
            <SheetTrigger
              aria-label="Open menu"
              // 36px + rounded hit area: the 20px icon alone was well under the
              // 44px touch-target guideline on a phone.
              className="-mr-1 inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground md:hidden"
            >
              <MenuIcon className="size-5" aria-hidden="true" />
            </SheetTrigger>
            <SheetContent
              side="right"
              // The primitive defaults to text-xs/relaxed on the whole panel,
              // which is too small for primary navigation. Reset to the base
              // size so the links read as tappable rows, not captions.
              className="w-[min(20rem,85vw)] gap-0 p-0 text-sm"
            >
              <SheetHeader className="shrink-0 gap-0 border-b border-border p-0">
                {/* Visible title rather than sr-only: an unlabelled drawer is a
                    disorientation bug on mobile, where there is no persistent
                    chrome to orient by. */}
                <div className="flex items-center gap-2.5 px-5 py-4">
                  <PolygonIcon />
                  <SheetTitle className="font-bold tracking-wide">PredictX</SheetTitle>
                </div>
                <SheetDescription className="sr-only">
                  Primary navigation
                </SheetDescription>
              </SheetHeader>

              <nav
                aria-label="Mobile"
                className="flex flex-1 flex-col gap-1 overflow-y-auto p-3"
              >
                <MobileNavLink
                  href="/"
                  label="Home"
                  icon={<HomeIcon className="size-4" aria-hidden="true" />}
                  isActive={pathname === "/"}
                  onNavigate={closeMenu}
                />
                {navLinks.map(({ href, label, icon }) => (
                  <MobileNavLink
                    key={href}
                    href={href}
                    label={label}
                    icon={icon}
                    isActive={isActive(href)}
                    onNavigate={closeMenu}
                  />
                ))}
              </nav>

              <SheetFooter className="shrink-0 border-t border-border p-3">
                <Link
                  href="/faq"
                  onClick={closeMenu}
                  className="flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  <HelpCircleIcon className="size-4" aria-hidden="true" />
                  Help &amp; FAQ
                </Link>
              </SheetFooter>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </header>
  )
}
