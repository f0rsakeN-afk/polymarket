import Link from "next/link"

export default function APIPage() {
  return (
    <div className="container mx-auto max-w-3xl px-4 py-12">
      <h1 className="text-2xl font-bold mb-2">API Reference</h1>
      <p className="text-sm text-muted-foreground mb-8">Programmatic access to Polymarket data and trading.</p>

      <div className="space-y-6 text-sm leading-relaxed">
        <section>
          <h2 className="text-base font-semibold mb-2">Authentication</h2>
          <p className="text-muted-foreground">All API requests require authentication via session cookie obtained through the web interface. API keys are not currently supported.</p>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-2">Endpoints</h2>
          <div className="space-y-2">
            {[
              { method: "GET", path: "/api/v1/markets", desc: "List all markets with pagination and filtering." },
              { method: "GET", path: "/api/v1/markets/{slug}", desc: "Get market details, outcomes, and prices." },
              { method: "GET", path: "/api/v1/markets/{slug}/orderbook", desc: "Get current order book for a market." },
              { method: "POST", path: "/api/v1/orders/", desc: "Place a market or limit order." },
              { method: "GET", path: "/api/v1/orders/", desc: "List your orders with filters." },
              { method: "GET", path: "/api/v1/positions/", desc: "List your current positions and P&L." },
              { method: "GET", path: "/api/v1/wallet/", desc: "Get wallet balance and details." },
            ].map(({ method, path, desc }) => (
              <div key={path} className="flex items-start gap-3 rounded-lg border border-border bg-card p-3">
                <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${
                  method === "GET" ? "bg-green-500/10 text-green-500" : "bg-blue-500/10 text-blue-500"
                }`}>
                  {method}
                </span>
                <div>
                  <code className="text-xs font-mono">{path}</code>
                  <p className="text-xs text-muted-foreground mt-0.5">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-2">Rate Limits</h2>
          <p className="text-muted-foreground">API requests are rate-limited. Excessive requests may result in temporary throttling.</p>
        </section>
      </div>
    </div>
  )
}
