"use client"

import Link from "next/link"

interface LinkGroup {
  title: string
  links: { href: string; label: string }[]
}

const linkGroups: LinkGroup[] = [
  {
    title: "Platform",
    links: [
      { href: "/markets", label: "Markets" },
      { href: "/trades", label: "Trade Feed" },
      { href: "/orders", label: "Orders" },
      { href: "/portfolio", label: "Portfolio" },
      { href: "/wallet", label: "Wallet" },
    ],
  },
  {
    title: "Resources",
    links: [
      { href: "/faq", label: "FAQ" },
      { href: "/docs", label: "Documentation" },
      { href: "/api", label: "API Reference" },
      { href: "/support", label: "Support" },
    ],
  },
  {
    title: "Legal",
    links: [
      { href: "/legal/terms", label: "Terms of Service" },
      { href: "/legal/privacy", label: "Privacy Policy" },
      { href: "/legal/risk", label: "Risk Disclosure" },
    ],
  },
]

const socialLinks = [
  { href: "https://x.com", label: "X (Twitter)", path: "M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" },
  { href: "https://discord.com", label: "Discord", path: "M20.317 4.37a19.79 19.79 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03z" },
  { href: "https://t.me", label: "Telegram", path: "M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z" },
]

function PolygonIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" className="shrink-0">
      <path d="M12 2L22 8V18L12 24L2 18V8L12 2Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" fill="none" />
      <path d="M12 2V24M2 8L22 8M2 18L22 18" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  )
}

export default function Footer() {
  return (
    <footer role="contentinfo" className="border-t border-border bg-card">
      <div className="container mx-auto max-w-7xl px-4">
        {/* Newsletter */}
        <div className="flex flex-col gap-6 border-b border-border py-10 sm:flex-row sm:items-center sm:justify-between">
          <div className="max-w-sm">
            <h3 className="text-sm font-semibold tracking-tight">Stay in the loop</h3>
            <p className="mt-1.5 text-xs text-muted-foreground leading-relaxed">
              Get the latest market insights, product updates, and platform announcements delivered to your inbox.
            </p>
          </div>
          <form
            className="flex w-full max-w-sm gap-2"
            onSubmit={(e) => e.preventDefault()}
            aria-label="Newsletter signup"
          >
            <label htmlFor="footer-email" className="sr-only">Email address</label>
            <input
              id="footer-email"
              type="email"
              placeholder="your@email.com"
              className="h-9 flex-1 rounded-lg border border-border bg-background px-3 text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring transition-shadow"
            />
            <button
              type="submit"
              className="h-9 rounded-lg bg-primary px-4 text-xs font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring transition-colors shrink-0"
            >
              Subscribe
            </button>
          </form>
        </div>

        {/* Links */}
        <div className="grid grid-cols-2 gap-8 py-10 sm:grid-cols-4">
          {/* Brand column */}
          <div className="col-span-2 sm:col-span-1">
            <Link href="/" className="flex items-center gap-2 font-bold tracking-wide mb-3">
              <PolygonIcon />
              <span>PredictX</span>
            </Link>
            <p className="text-xs text-muted-foreground leading-relaxed max-w-xs">
              A decentralized prediction market platform for trading on the outcome of real-world events.
            </p>
            <div className="flex items-center gap-2.5 mt-4">
              {socialLinks.map(({ href, label, path }) => (
                <a
                  key={label}
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={label}
                  className="flex items-center justify-center size-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <svg className="size-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                    <path d={path} />
                  </svg>
                </a>
              ))}
            </div>
          </div>

          {/* Link columns */}
          {linkGroups.map(({ title, links }) => (
            <div key={title}>
              <h4 className="mb-3 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
                {title}
              </h4>
              <ul className="space-y-2.5">
                {links.map(({ href, label }) => (
                  <li key={href}>
                    <Link
                      href={href}
                      className="text-xs text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
                    >
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* Bottom bar */}
        <div className="flex flex-col items-center justify-between gap-4 border-t border-border py-6 sm:flex-row">
          <p className="text-[11px] text-muted-foreground">
            &copy; {new Date().getFullYear()} PredictX. All rights reserved.
          </p>
          <div className="flex items-center gap-4">
            <Link href="/legal/privacy" className="text-[11px] text-muted-foreground hover:text-foreground transition-colors">
              Privacy
            </Link>
            <span className="text-[11px] text-muted-foreground/30" aria-hidden="true">&middot;</span>
            <Link href="/legal/terms" className="text-[11px] text-muted-foreground hover:text-foreground transition-colors">
              Terms
            </Link>
            <span className="text-[11px] text-muted-foreground/30" aria-hidden="true">&middot;</span>
            <Link href="/legal/risk" className="text-[11px] text-muted-foreground hover:text-foreground transition-colors">
              Risks
            </Link>
          </div>
        </div>
      </div>
    </footer>
  )
}
