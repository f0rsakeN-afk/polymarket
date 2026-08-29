export const metadata = {
  title: "Documentation",
  description:
    "PredictX developer documentation and API reference. Integrate with our trading API and building on top of the platform.",
}

const resources = [
  {
    href: "https://docs.predictx.io",
    label: "API Reference",
    description:
      "Full API reference for the PredictX trading engine. Endpoints, authentication, rate limits, and request/response schemas.",
    external: true,
  },
  {
    href: "/faq",
    label: "Frequently Asked Questions",
    description:
      "Common questions about PredictX — trading, market resolution, fees, account management, and more.",
  },
  {
    href: "/support",
    label: "Support",
    description:
      "Need help? Reach us via email, Discord, or our community channels.",
  },
]

export default function DocsPage() {
  return (
    <div className="container mx-auto max-w-7xl px-4 py-8">
      <div className="mb-12">
        <h1 className="text-2xl font-bold tracking-tight">Documentation</h1>
        <p className="mt-3 max-w-md text-sm leading-relaxed text-muted-foreground">
          Integrate with the PredictX API and build on top of the platform.
        </p>
      </div>

      <div className="divide-y border-y">
        {resources.map(({ href, label, description, external }) => (
          <a
            key={href}
            href={href}
            target={external ? "_blank" : undefined}
            rel={external ? "noopener noreferrer" : undefined}
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
            <svg
              className="size-4 shrink-0 text-muted-foreground transition-all group-hover:translate-x-0.5 group-hover:text-primary"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              {external ? (
                <path
                  d="M11 2a2 2 0 1 1 0 4H7M9 11l4-4M9 11H3m6 4h2a2 2 0 0 0 2-2V5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              ) : (
                <path
                  d="M3 8h10M9 4l4 4-4 4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              )}
            </svg>
          </a>
        ))}
      </div>

      <p className="mt-10 text-xs leading-relaxed text-muted-foreground">
        For technical integrations and partnership inquiries, contact{" "}
        <a
          href="mailto:api@predictx.io"
          className="underline hover:text-foreground"
        >
          api@predictx.io
        </a>
        .
      </p>
    </div>
  )
}
