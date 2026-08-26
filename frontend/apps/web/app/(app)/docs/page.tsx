export const metadata = {
  title: "Documentation",
  description: "Developer documentation and API reference for building on PredictX.",
}

export default function DocsPage() {
  return (
    <div className="container mx-auto max-w-3xl px-4 py-12">
      <h1 className="text-2xl font-bold mb-2">Documentation</h1>
      <p className="text-sm text-muted-foreground mb-8">Guides and references for using PredictX.</p>
      <div className="space-y-4">
        {[
          { title: "Getting Started", desc: "Create an account, deposit funds, and place your first trade." },
          { title: "How Trading Works", desc: "Understand AMM pricing, order books, limit orders, and fills." },
          { title: "Wallet & Funds", desc: "Manage deposits, withdrawals, and view transaction history." },
          { title: "Market Resolution", desc: "How markets are resolved and how to claim winnings." },
          { title: "Risk Management", desc: "Strategies for managing risk and setting slippage tolerances." },
        ].map(({ title, desc }) => (
          <div key={title} className="rounded-xl border border-border bg-card p-5">
            <h2 className="text-sm font-semibold mb-1">{title}</h2>
            <p className="text-xs text-muted-foreground">{desc}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
