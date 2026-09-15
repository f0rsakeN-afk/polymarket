"use client"

import { useMemo } from "react"
import { useRouter } from "next/navigation"
import { CommandPalette, type CommandItem } from "./command-palette"
import { LayoutDashboard, TrendingUp, Wallet, Settings, HelpCircle, FileText } from "lucide-react"

export function AppCommandMenu() {
  const router = useRouter()

  const items: CommandItem[] = useMemo(() => [
    { id: "home", label: "Home", description: "Go to homepage", category: "Navigation", icon: <LayoutDashboard className="size-4" />, keywords: ["home", "dashboard"], action: () => router.push("/") },
    { id: "markets", label: "Markets", description: "Browse prediction markets", category: "Navigation", icon: <TrendingUp className="size-4" />, keywords: ["markets", "trade"], action: () => router.push("/markets") },
    { id: "trades", label: "Trades", description: "View trade feed", category: "Navigation", icon: <TrendingUp className="size-4" />, keywords: ["trades"], action: () => router.push("/trades") },
    { id: "portfolio", label: "Portfolio", description: "View your portfolio", category: "Navigation", icon: <Wallet className="size-4" />, keywords: ["portfolio"], action: () => router.push("/portfolio") },
    { id: "settings", label: "Settings", description: "Account settings", category: "Navigation", icon: <Settings className="size-4" />, keywords: ["settings"], action: () => router.push("/settings") },
    { id: "faq", label: "FAQ", description: "Frequently asked questions", category: "Help", icon: <HelpCircle className="size-4" />, keywords: ["faq", "help"], action: () => router.push("/faq") },
    { id: "docs", label: "Docs", description: "API documentation", category: "Help", icon: <FileText className="size-4" />, keywords: ["docs"], action: () => router.push("/docs") },
  ], [router])

  return <CommandPalette items={items} placeholder="Search pages, markets..." emptyMessage="No results." />
}
