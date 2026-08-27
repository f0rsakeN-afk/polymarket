"use client"

import Link from "next/link"
import { useState, useEffect, useCallback } from "react"
import { cn } from "@workspace/ui/lib/utils"

interface Section {
  id: string
  label: string
}

interface LegalLayoutProps {
  title: string
  lastUpdated: string
  sections: Section[]
  children: React.ReactNode
}

export function LegalLayout({ title, lastUpdated, sections, children }: LegalLayoutProps) {
  const [active, setActive] = useState<string>("")
  const [mobileOpen, setMobileOpen] = useState(false)

  const handleScroll = useCallback(() => {
    const sectionEls = sections
      .map(({ id }) => document.getElementById(id))
      .filter(Boolean) as HTMLElement[]

    let closest: string | null = null
    let closestDist = Infinity
    for (const el of sectionEls) {
      const dist = Math.abs(el.getBoundingClientRect().top - 80)
      if (dist < closestDist) {
        closestDist = dist
        closest = el.id
      }
    }
    if (closest) setActive(closest)
  }, [sections])

  useEffect(() => {
    window.addEventListener("scroll", handleScroll, { passive: true })
    handleScroll()
    return () => window.removeEventListener("scroll", handleScroll)
  }, [handleScroll])

  const handleMobileToggle = useCallback(() => setMobileOpen((v) => !v), []);

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8">
      {/* Breadcrumb */}
      <div className="mb-8">
        <Link
          href="/legal"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <svg className="size-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M10 3L5 8l5 5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Legal
        </Link>
      </div>

      {/* Header */}
      <div className="mb-12 pb-8 border-b border-border">
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        <p className="mt-2 text-xs text-muted-foreground">Last updated: {lastUpdated}</p>
      </div>

      <div className="flex gap-16">
        {/* Desktop TOC */}
        <aside className="hidden lg:block w-48 shrink-0">
          <div className="sticky top-24">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-4">
              On this page
            </p>
            <nav className="space-y-1">
              {sections.map(({ id, label }) => (
                <a
                  key={id}
                  href={`#${id}`}
                  className={cn(
                    "block text-xs py-1 transition-colors leading-snug",
                    active === id
                      ? "text-foreground font-medium"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {label}
                </a>
              ))}
            </nav>
          </div>
        </aside>

        {/* Content */}
        <article className="flex-1 min-w-0 max-w-2xl">{children}</article>
      </div>

      {/* Mobile TOC */}
      <div className="lg:hidden mt-8">
        <button
          onClick={handleMobileToggle}
          className="flex items-center justify-between w-full py-3 px-4 rounded-lg border border-border bg-muted/30 text-xs font-medium"
        >
          <span>On this page</span>
          <svg
            className={cn("size-3.5 transition-transform", mobileOpen && "rotate-180")}
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        {mobileOpen && (
          <nav className="mt-2 divide-y border border-border rounded-lg bg-card overflow-hidden">
            {sections.map(({ id, label }) => (
              <a
                key={id}
                href={`#${id}`}
                className="block px-4 py-2.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors"
              >
                {label}
              </a>
            ))}
          </nav>
        )}
      </div>
    </div>
  )
}
