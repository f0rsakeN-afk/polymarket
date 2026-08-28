"use client"

import { useState, useCallback } from "react"
import { cn } from "@workspace/ui/lib/utils"

const faqs = [
  {
    category: "Account",
    questions: [
      {
        q: "How do I create an account?",
        a: "Connect your wallet to the platform. Your account is automatically created on your first connection using your wallet address.",
      },
      {
        q: "Is KYC required?",
        a: "Not for basic trading. KYC may be required for higher deposit or trading limits depending on your jurisdiction.",
      },
      {
        q: "How do I reset my password?",
        a: "Since PredictX uses wallet-based authentication, there is no traditional password. Simply reconnect your wallet to access your account.",
      },
      {
        q: "How do I delete my account?",
        a: "Contact support at support@predictx.io. Note that regulatory requirements may mandate retention of certain data.",
      },
    ],
  },
  {
    category: "Trading",
    questions: [
      {
        q: "How do I start trading?",
        a: "Deposit funds into your wallet, then browse the Markets page. Select a market, choose an outcome, specify your stake, and place the trade.",
      },
      {
        q: "What's the difference between limit and market orders?",
        a: "A limit order lets you set a maximum buy price or minimum sell price — it executes only when the market reaches your price. A market order executes immediately at the best available price.",
      },
      {
        q: "Can I cancel an order?",
        a: "Pending limit orders can be cancelled at any time before execution. Market orders that have been filled cannot be reversed.",
      },
      {
        q: "Why wasn't my order filled?",
        a: "Limit orders may not fill if the market price never reaches your specified price. Market orders fill at the best available price, which may differ from the last traded price in illiquid markets.",
      },
      {
        q: "What is slippage?",
        a: "Slippage is the difference between the expected price of a trade and the actual price at which it executes. It is more common in markets with low liquidity.",
      },
    ],
  },
  {
    category: "Markets",
    questions: [
      {
        q: "How are markets created?",
        a: "Markets are created by PredictX or authorized market makers. Each market has defined resolution criteria and an expiration date.",
      },
      {
        q: "How are markets resolved?",
        a: "Markets are resolved by administrators based on the resolution criteria specified at market creation. Resolution decisions are final and binding.",
      },
      {
        q: "What happens if a market is cancelled?",
        a: "If a market is cancelled, all open orders are voided and any funds reserved for those orders are released back to your account.",
      },
      {
        q: "Can I trade after a market resolves?",
        a: "No. Trading closes when a market resolves. Resolved markets show the final outcome and are no longer tradable.",
      },
      {
        q: "What is the trading volume shown on a market?",
        a: "Trading volume represents the total amount traded in that market since it was created, denominated in the platform's base currency.",
      },
    ],
  },
  {
    category: "Fees & Payments",
    questions: [
      {
        q: "What fees do you charge?",
        a: "A protocol fee is applied to each trade as displayed before confirmation. There are no deposit or withdrawal fees from PredictX. Network gas fees apply for on-chain transactions.",
      },
      {
        q: "Are there withdrawal fees?",
        a: "PredictX does not charge withdrawal fees. However, network gas fees apply for blockchain withdrawals.",
      },
      {
        q: "How do deposits work?",
        a: "Deposit funds by transferring crypto to your account wallet address. Deposits are credited after network confirmation.",
      },
      {
        q: "Why is my balance showing zero after a trade?",
        a: "Funds used to place an order are temporarily held as collateral. They are released back to your balance if the order is cancelled or filled.",
      },
    ],
  },
  {
    category: "Security",
    questions: [
      {
        q: "Is PredictX safe to use?",
        a: "PredictX uses industry-standard security practices including encryption, cold storage for funds, and regular security audits. However, always use strong wallet security practices on your end.",
      },
      {
        q: "How do I enable two-factor authentication?",
        a: "Go to Settings → 2FA and follow the setup instructions. We support authenticator apps.",
      },
      {
        q: "What should I do if I suspect unauthorized activity?",
        a: "Contact support immediately at support@predictx.io and consider transferring remaining funds to a new wallet.",
      },
    ],
  },
  {
    category: "General",
    questions: [
      {
        q: "What is a prediction market?",
        a: "A prediction market is a platform where participants trade contracts based on the outcome of real-world events. Prices reflect the collective probability assessment of all traders.",
      },
      {
        q: "What makes PredictX different from other exchanges?",
        a: "PredictX focuses specifically on prediction markets with real-world event resolution, offering a curated set of markets rather than general financial instruments.",
      },
      {
        q: "Does PredictX provide investment advice?",
        a: "No. PredictX does not provide investment, legal, or tax advice. All trading decisions are your own. Please consult qualified professionals for financial advice.",
      },
      {
        q: "Where can I find API documentation?",
        a: "API documentation is available at docs.predictx.io. For technical integration support, contact api@predictx.io.",
      },
      {
        q: "How do I contact support?",
        a: "You can reach us by email at support@predictx.io or via Discord. We aim to respond within 24 hours on business days.",
      },
    ],
  },
]

function FAQItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false)
  const toggle = useCallback(() => setOpen(o => !o), [])

  return (
    <div className="border-b border-border last:border-0">
      <button
        onClick={toggle}
        className="flex w-full items-center justify-between gap-4 px-4 py-4 text-left"
      >
        <span className="text-sm font-medium text-foreground/90">{q}</span>
        <svg
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform duration-200",
            open && "rotate-180"
          )}
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <div
        className={cn(
          "overflow-hidden transition-all duration-200 px-4",
          open ? "max-h-96 pb-4" : "max-h-0"
        )}
      >
        <p className="text-sm text-muted-foreground leading-relaxed">{a}</p>
      </div>
    </div>
  )
}

export default function FAQPage() {
  return (
    <div className="container mx-auto max-w-7xl px-4 py-8">
      <div className="mb-12">
        <h1 className="text-2xl font-bold tracking-tight">Frequently Asked Questions</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Common questions about PredictX prediction markets, trading, and platform features.
        </p>
      </div>

      <div className="space-y-12">
        {faqs.map(({ category, questions }) => (
          <section key={category}>
            <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-4">
              {category}
            </h2>
            <div className="rounded-lg border border-border bg-card divide-y divide-border">
              {questions.map(({ q, a }) => (
                <FAQItem key={q} q={q} a={a} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
