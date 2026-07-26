export default function SupportPage() {
  return (
    <div className="container mx-auto max-w-3xl px-4 py-12">
      <h1 className="text-2xl font-bold mb-6">Support</h1>
      <div className="space-y-4 text-sm">
        <div className="rounded-xl border border-border bg-card p-5">
          <h2 className="font-semibold mb-1">Email</h2>
          <p className="text-muted-foreground text-xs">support@polymarket.example.com</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <h2 className="font-semibold mb-1">Discord</h2>
          <p className="text-muted-foreground text-xs">Join our Discord server for community support and discussion.</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <h2 className="font-semibold mb-1">FAQ</h2>
          <p className="text-muted-foreground text-xs">Check our <a href="/faq" className="text-primary hover:underline">FAQ page</a> for answers to common questions.</p>
        </div>
      </div>
    </div>
  )
}
