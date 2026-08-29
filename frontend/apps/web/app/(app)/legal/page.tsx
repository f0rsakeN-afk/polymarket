import Link from "next/link"

export const metadata = {
  title: "Legal",
  description:
    "PredictX legal information including terms of service, privacy policy, and risk disclosure.",
}

const docs = [
  {
    href: "/legal/terms",
    label: "Terms of Service",
    description:
      "Account registration, trading rules, prohibited conduct, intellectual property, and dispute resolution.",
    updated: "July 2026",
  },
  {
    href: "/legal/privacy",
    label: "Privacy Policy",
    description:
      "How we collect, use, and protect your personal data — including cookies, analytics, and your rights.",
    updated: "July 2026",
  },
  {
    href: "/legal/risk",
    label: "Risk Disclosure",
    description:
      "Understand the financial, market, regulatory, and technical risks of prediction market trading.",
    updated: "July 2026",
  },
]

export default function LegalPage() {
  return (
    <div className="container mx-auto max-w-7xl px-4 py-8">
      <div className="mb-12">
        <h1 className="text-2xl font-bold tracking-tight">Legal</h1>
        <p className="mt-3 max-w-md text-sm leading-relaxed text-muted-foreground">
          PredictX is a decentralized prediction market platform. Please read
          and understand these documents before using the platform.
        </p>
      </div>

      <div className="divide-y border-y">
        {docs.map(({ href, label, description, updated }) => (
          <Link
            key={href}
            href={href}
            className="group flex items-center justify-between gap-8 py-5 hover:no-underline"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium transition-colors group-hover:text-primary">
                {label}
              </p>
              <p className="mt-1 pr-4 text-xs leading-relaxed text-muted-foreground">
                {description}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-6">
              <span className="hidden text-xs text-muted-foreground sm:block">
                {updated}
              </span>
              <svg
                className="size-4 text-muted-foreground transition-all group-hover:translate-x-0.5 group-hover:text-primary"
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
              >
                <path
                  d="M3 8h10M9 4l4 4-4 4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
          </Link>
        ))}
      </div>

      <p className="mt-10 text-xs leading-relaxed text-muted-foreground">
        By using PredictX, you agree to be bound by our{" "}
        <Link href="/legal/terms" className="underline hover:text-foreground">
          Terms of Service
        </Link>
        ,{" "}
        <Link href="/legal/privacy" className="underline hover:text-foreground">
          Privacy Policy
        </Link>
        , and{" "}
        <Link href="/legal/risk" className="underline hover:text-foreground">
          Risk Disclosure
        </Link>
        . If you do not agree, do not use the platform.
      </p>
    </div>
  )
}
