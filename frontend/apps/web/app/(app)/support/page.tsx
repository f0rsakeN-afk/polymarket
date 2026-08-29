import Link from "next/link"

export const metadata = {
  title: "Support",
  description:
    "Get help with your PredictX account, trading, and platform questions.",
}

export default function SupportPage() {
  return (
    <div className="container mx-auto max-w-7xl px-4 py-8">
      <div className="mb-12">
        <h1 className="text-2xl font-bold tracking-tight">Support</h1>
        <p className="mt-3 max-w-md text-sm leading-relaxed text-muted-foreground">
          Get help with your PredictX account, trading, and platform questions.
        </p>
      </div>

      <div className="divide-y border-y">
        <div className="flex items-center justify-between gap-8 py-5">
          <div>
            <p className="text-sm font-medium">Email</p>
            <p className="mt-1 text-xs text-muted-foreground">
              <a
                href="mailto:support@predictx.io"
                className="text-primary hover:underline"
              >
                support@predictx.io
              </a>
            </p>
          </div>
        </div>

        <a
          href="https://discord.com"
          target="_blank"
          rel="noopener noreferrer"
          className="group flex items-center justify-between gap-8 py-5 hover:no-underline"
        >
          <div>
            <p className="text-sm font-medium transition-colors group-hover:text-primary">
              Discord
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Join our Discord server for community support and discussion.
            </p>
          </div>
          <svg
            className="size-4 shrink-0 text-muted-foreground transition-all group-hover:translate-x-0.5 group-hover:text-primary"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <path
              d="M11 2a2 2 0 1 1 0 4H7M9 11l4-4M9 11H3m6 4h2a2 2 0 0 0 2-2V5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </a>

        <Link
          href="/faq"
          className="group flex items-center justify-between gap-8 py-5 hover:no-underline"
        >
          <div>
            <p className="text-sm font-medium transition-colors group-hover:text-primary">
              FAQ
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Common questions about PredictX — trading, market resolution,
              fees, and more.
            </p>
          </div>
          <svg
            className="size-4 shrink-0 text-muted-foreground transition-all group-hover:translate-x-0.5 group-hover:text-primary"
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
        </Link>
      </div>
    </div>
  )
}
