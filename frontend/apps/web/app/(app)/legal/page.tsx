import Link from "next/link"

export const metadata = {
  title: "Legal",
  description: "PredictX legal information including terms of service, privacy policy, and risk disclosure.",
}

export default function LegalPage() {
  return (
    <div className="container mx-auto max-w-3xl px-4 py-12">
      <h1 className="text-2xl font-bold mb-2">Legal</h1>
      <p className="text-sm text-muted-foreground mb-8">
        Important information about using PredictX.
      </p>

      <div className="space-y-4">
        <Link
          href="/legal/terms"
          className="block rounded-xl border border-border bg-card p-5 hover:bg-muted/50 transition-colors"
        >
          <h2 className="text-sm font-semibold mb-1">Terms of Service</h2>
          <p className="text-xs text-muted-foreground">
            The terms governing your use of the Polymarket platform, including account registration, trading rules, and dispute resolution.
          </p>
        </Link>

        <Link
          href="/legal/privacy"
          className="block rounded-xl border border-border bg-card p-5 hover:bg-muted/50 transition-colors"
        >
          <h2 className="text-sm font-semibold mb-1">Privacy Policy</h2>
          <p className="text-xs text-muted-foreground">
            How we collect, use, and protect your personal data, including cookies, analytics, and your privacy rights.
          </p>
        </Link>

        <Link
          href="/legal/risk"
          className="block rounded-xl border border-border bg-card p-5 hover:bg-muted/50 transition-colors"
        >
          <h2 className="text-sm font-semibold mb-1">Risk Disclosure</h2>
          <p className="text-xs text-muted-foreground">
            Important risks associated with prediction market trading, including financial loss, market manipulation, and regulatory uncertainty.
          </p>
        </Link>
      </div>
    </div>
  )
}
