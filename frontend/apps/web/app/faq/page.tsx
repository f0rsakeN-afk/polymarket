export default function FAQPage() {
  return (
    <div className="container mx-auto max-w-3xl px-4 py-12">
      <h1 className="text-2xl font-bold mb-6">Frequently Asked Questions</h1>
      <div className="space-y-6 text-sm leading-relaxed text-foreground/90">
        <article>
          <h2 className="text-base font-semibold mb-1">What is Polymarket?</h2>
          <p className="text-muted-foreground">Polymarket is a prediction market platform where users can trade on the outcomes of real-world events.</p>
        </article>
        <article>
          <h2 className="text-base font-semibold mb-1">How do I start trading?</h2>
          <p className="text-muted-foreground">Create an account, deposit funds into your wallet, and browse available markets to place trades.</p>
        </article>
        <article>
          <h2 className="text-base font-semibold mb-1">How are markets resolved?</h2>
          <p className="text-muted-foreground">Markets are resolved by administrators based on the resolution criteria defined at market creation. Resolution is final.</p>
        </article>
        <article>
          <h2 className="text-base font-semibold mb-1">What fees do you charge?</h2>
          <p className="text-muted-foreground">A protocol fee is applied to each trade as displayed at the time of trading. There are no deposit or withdrawal fees from Polymarket.</p>
        </article>
        <article>
          <h2 className="text-base font-semibold mb-1">Can I cancel an order?</h2>
          <p className="text-muted-foreground">Pending limit orders can be cancelled. Market orders that have been filled cannot be reversed.</p>
        </article>
      </div>
    </div>
  )
}
