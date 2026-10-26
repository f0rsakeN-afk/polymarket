"use client"

/**
 * The admin navigation rail.
 *
 * ## Responsiveness, and why it is one component
 *
 * One component with three states, not a desktop sidebar plus a mobile sheet that
 * happen to look alike. Two components means two sets of focus traps, two sets of
 * Escape handling, and two places for the active-item highlight to drift.
 *
 * - **Mobile (< `md`)** — `collapsible="offcanvas"`, so the rail is an overlay
 *   with focus moved into it and Escape to close. A rail that slides in *over*
 *   live content without trapping focus lets a keyboard user tab into content
 *   they cannot see, which is the defining failure of a mobile drawer.
 * - **Desktop** — a rail that collapses to icons. Collapsed items carry a
 *   tooltip, so the narrow rail is not a guessing game.
 *
 * ## Accessibility decisions worth naming
 *
 * - `aria-current="page"` on the active item. Colour is not an accessible signal,
 *   and "where am I" is the one thing the rail exists to answer.
 * - Icons are `aria-hidden`; the link's accessible name is its label text.
 * - The rail is a `<nav>` with an accessible name — once a page adds breadcrumbs
 *   there are two navigations on the page and the distinction matters.
 * - Group labels are real `<h2>`s, so a screen reader can jump between sections
 *   instead of reading every link linearly.
 */

import { useEffect } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { useTheme } from "next-themes"
import { LogOut, Monitor, Moon, ShieldAlert, UserCog } from "lucide-react"
import { sileo } from "sileo"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { api } from "@workspace/api-client/client"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarTrigger,
} from "@workspace/ui/components/sidebar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@workspace/ui/components/dropdown-menu"
import { Button } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

import { ADMIN_NAV, isActiveRoute } from "@/lib/nav"

/** Spelled at runtime so the hint and the handler cannot disagree. */
const MODIFIER = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl"
import type { MeResponse } from "@/hooks/use-auth"

export function AdminSidebar({ user }: { user: MeResponse }) {
  const pathname = usePathname()

  return (
    // `collapsible="icon"`, not `"offcanvas"`.
    //
    // The mobile branch of `Sidebar` is chosen by `useIsMobile`, not by this prop,
    // so mobile gets the overlay Sheet either way. The prop only decides what
    // happens at `md` and up — and `offcanvas` there means the rail slides fully
    // off-screen and the content does *not* reflow, which is a mobile drawer
    // wearing a desktop's clothes. `icon` collapses to the icon width instead, so
    // the page gets the space back and every collapsed item keeps a tooltip.
    <Sidebar collapsible="icon" className="border-r">
      <SidebarHeader className="border-b">
        <div className="flex items-center gap-2 px-1 py-1">
          <span className="grid size-7 shrink-0 place-items-center rounded-md bg-destructive/10">
            <ShieldAlert className="size-4 text-destructive" aria-hidden />
          </span>
          <span className="min-w-0 flex-1 truncate text-sm font-semibold">
            PredictX Admin
          </span>
          {/* The desktop toggle.
              Without it the rail is only collapsible by clicking the 4px strip on
              its edge — which is discoverable by nobody, and `tabIndex={-1}` on
              `SidebarRail` means a keyboard user cannot reach it at all.
              `md:hidden` because below `md` this header is not rendered and the
              sticky bar in the shell already carries a trigger. */}
          <SidebarTrigger
            className="hidden md:inline-flex"
            aria-label="Collapse navigation"
          />
        </div>
      </SidebarHeader>

      <SidebarContent>
        {ADMIN_NAV.map((group) => (
          <SidebarGroup key={group.label}>
            {/* `render`, not `asChild` — these are Base UI components. `asChild`
                is the Radix spelling and is silently ignored here, which is the
                trap the naming invites. */}
            <SidebarGroupLabel
              render={<h2 className="text-[0.6875rem] font-semibold uppercase tracking-wider" />}
            >
              {group.label}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => {
                  const active = isActiveRoute(pathname, item.href)
                  return (
                    <SidebarMenuItem key={item.href}>
                      <SidebarMenuButton
                        render={<Link href={item.href} />}
                        isActive={active}
                        aria-current={active ? "page" : undefined}
                        // Only useful once the rail is collapsed. A tooltip that
                        // is always present fights the visible label and makes a
                        // screen reader say it twice.
                        tooltip={item.label}
                        className={cn(
                          "h-9 gap-2.5",
                          active && "bg-accent font-medium text-accent-foreground"
                        )}
                      >
                        <item.icon className="size-4 shrink-0" aria-hidden />
                        <span className="truncate">{item.label}</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarFooter className="border-t">
        {/* The theme toggle lives here, not only in the sticky mobile bar.

            It used to exist solely inside a `md:hidden` header, which meant the
            primary way anyone uses this tool — a desktop operator with a wide
            audit row — had no way to switch theme at all. A control that is only
            reachable below a breakpoint is a control most people never find.

            `group-data-[collapsible=icon]:hidden` because the icon rail is one
            column wide and a stray toggle there reads as a broken button. The
            account row below still names the user when collapsed. */}
        <div className="hidden justify-end px-1 pb-1 group-data-[collapsible=icon]:hidden">
          <ThemeToggle />
        </div>
        <AccountMenu user={user} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}

function AccountMenu({ user }: { user: MeResponse }) {
  const qc = useQueryClient()

  const signOut = useMutation({
    mutationFn: () => api.post("/api/v1/auth/logout"),
    // `onSettled`, not `onSuccess`: the local session ends whether or not the
    // server confirmed it, and the cookies are cleared from the response either
    // way. A logout that fails server-side must still clear this machine.
    onSettled: () => {
      qc.clear()
      sileo.success({ title: "Signed out" })
      // A full navigation rather than a client-side route change: every cached
      // response in this bundle was authorised by the session that just ended,
      // and a soft navigation keeps them alive long enough to paint.
      window.location.href = "/login"
    },
  })

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        aria-label="Account menu"
      >
        <span
          className="grid size-7 shrink-0 place-items-center rounded-full bg-muted text-[0.6875rem] font-semibold uppercase"
          aria-hidden
        >
          {(user.username || user.email).slice(0, 2)}
        </span>
        <span className="grid min-w-0 flex-1 gap-0.5">
          <span className="truncate text-xs font-medium">{user.username}</span>
          <span className="truncate text-[0.6875rem] text-muted-foreground">
            {user.email}
          </span>
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" side="top" className="w-56">
        <div className="px-2 py-1.5">
          <p className="text-sm font-medium">{user.username}</p>
          <p className="truncate text-xs text-muted-foreground">{user.email}</p>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem render={<Link href="/users/security" />}>
          <UserCog className="size-3.5" aria-hidden />
          Sessions &amp; two-factor
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() => signOut.mutate()}
          disabled={signOut.isPending}
          className="text-destructive focus:text-destructive"
        >
          <LogOut className="size-3.5" aria-hidden />
          {signOut.isPending ? "Signing out…" : "Sign out"}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/**
 * Theme toggle.
 *
 * The label states the *action*, not the state. "Switch to light theme" tells a
 * screen reader user what pressing it will do; announcing the current theme
 * answers a question nobody asked and still leaves them guessing.
 *
 * `Ctrl/Cmd + Shift + D` mirrors what the sidebar already does for its own
 * toggle, so the two keyboard shortcuts in this app are consistent with each
 * other. Guarded against the modifier-only and key-repeat cases so holding the
 * combination down does not strobe the theme.
 */
export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme()
  const next = resolvedTheme === "dark" ? "light" : "dark"

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!event.shiftKey || !(event.metaKey || event.ctrlKey)) return
      // Both keys matter: Ctrl+D alone is a browser bookmark shortcut, and
      // Shift+D alone is ordinary typing.
      if (event.key.toLowerCase() !== "d") return
      if (event.repeat) return
      event.preventDefault()
      setTheme(next)
    }

    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [next, setTheme])

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme (${MODIFIER}+Shift+D)`}
    >
      <Monitor className="size-4 dark:hidden" aria-hidden />
      <Moon className="hidden size-4 dark:block" aria-hidden />
    </Button>
  )
}