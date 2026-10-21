"use client"

/**
 * The admin information architecture, in one place.
 *
 * ## Why this is a typed model and not JSX in the sidebar
 *
 * Three things want to know what the navigation is, and none of them is the
 * sidebar: this file, the command palette that jumps to a section, and the tests
 * that assert every route in the app is reachable. Encoding it as an array means
 * adding a page without a nav entry is a failing test rather than a page nobody
 * can find.
 *
 * ## Why the groups
 *
 * A flat list of six links is a list, not a structure — it makes the operator
 * infer which actions are related and which are one-per-day. The groups answer
 * the question an operator actually arrives with:
 *
 * - **Overview** — where am I.
 * - **Operate** — the queue of things waiting on me to decide.
 * - **Investigate** — look at one account or one thing in depth.
 * - **Accountability** — what has been done, and by whom.
 * - **Account** — this session and this factor. Separate because it is about
 *   *me* rather than about the system, and because an operator who needs to
 *   rotate a session should not have to hunt for it among moderation links.
 */

import {
  Gavel,
  Landmark,
  ScrollText,
  Scale,
  ShieldCheck,
  UserCog,
  Users,
  type LucideIcon,
} from "lucide-react"

export interface AdminNavItem {
  href: string
  label: string
  icon: LucideIcon
  /** A noun, so a screen reader says "Disputes, 3 awaiting" and not "Disputes, 3". */
  description: string
}

export interface AdminNavGroup {
  /** Announced by the sidebar group label; short, because it is read out. */
  label: string
  items: AdminNavItem[]
}

export const ADMIN_NAV: AdminNavGroup[] = [
  {
    label: "Overview",
    items: [
      {
        href: "/",
        label: "Dashboard",
        icon: ShieldCheck,
        description: "What is waiting, and what failed",
      },
    ],
  },
  {
    label: "Operate",
    items: [
      {
        href: "/disputes",
        label: "Disputes",
        icon: Gavel,
        description: "Claims awaiting a ruling",
      },
      {
        href: "/markets",
        label: "Moderation",
        icon: Scale,
        description: "Markets awaiting review",
      },
      {
        href: "/treasury",
        label: "Treasury",
        icon: Landmark,
        description: "Fees collected and distributed",
      },
    ],
  },
  {
    label: "Investigate",
    items: [
      {
        href: "/users",
        label: "Users",
        icon: Users,
        description: "Accounts, wallets and activity",
      },
      {
        href: "/users/security",
        label: "Security",
        icon: UserCog,
        description: "Sessions and two-factor",
      },
    ],
  },
  {
    label: "Accountability",
    items: [
      {
        href: "/audit",
        label: "Audit trail",
        icon: ScrollText,
        description: "Privileged actions and auth events",
      },
    ],
  },
]

/** Every route the sidebar links to, flattened. Used by the reachability test. */
export const ADMIN_ROUTES = ADMIN_NAV.flatMap((group) => group.items.map((i) => i.href))

/**
 * Is `pathname` inside `href`?
 *
 * Exact match for `/`, prefix match for everything else. The prefix test also
 * requires a `/` boundary so `/usersX` is not "inside" `/users` — without it,
 * a route added later inherits another route's highlight, which is the kind of
 * bug that looks fine until you rename something.
 */
export function isActiveRoute(pathname: string | null, href: string): boolean {
  if (!pathname) return false
  if (href === "/") return pathname === "/"
  return pathname === href || pathname.startsWith(`${href}/`)
}