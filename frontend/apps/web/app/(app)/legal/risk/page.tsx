import { LegalLayout } from "@/components/shared/legal-layout"

export const metadata = {
  title: "Risk Disclosure",
  description: "Risk disclosure for PredictX prediction markets.",
}

const sections = [
  { id: "warning", label: "Important Notice" },
  { id: "financial", label: "Financial Risk" },
  { id: "market-integrity", label: "Market Integrity Risks" },
  { id: "regulatory", label: "Regulatory Risk" },
  { id: "technical", label: "Technical Risk" },
  { id: "advice", label: "No Investment Advice" },
  { id: "suitability", label: "Suitability" },
  { id: "insurance", label: "No Insurance" },
  { id: "acknowledgment", label: "Acknowledgment" },
]

export default function RiskPage() {
  return (
    <LegalLayout
      title="Risk Disclosure"
      lastUpdated="July 2026"
      sections={sections}
    >
      <div className="space-y-10 text-sm leading-relaxed text-foreground/90">
        <div
          id="warning"
          className="not-prose rounded-xl border border-amber-500/30 bg-amber-500/5 p-4"
        >
          <p className="mb-1 text-xs font-semibold text-amber-600">Important</p>
          <p className="text-xs leading-relaxed text-amber-700 dark:text-amber-400">
            Trading on prediction markets involves substantial risk. You should
            carefully consider whether such trading is appropriate for you based
            on your financial situation, risk tolerance, and experience. You may
            lose some or all of the funds you deposit.
          </p>
        </div>

        <section id="financial">
          <h2 className="mb-3 text-base font-semibold">1. Financial Risk</h2>
          <ul className="list-disc space-y-1 pl-5">
            <li>
              <strong>Total loss:</strong> You may lose the entire amount you
              spend purchasing shares in a market if your chosen outcome does
              not occur.
            </li>
            <li>
              <strong>Market risk:</strong> Share prices fluctuate based on
              supply and demand. The price you pay may not reflect the eventual
              outcome.
            </li>
            <li>
              <strong>Liquidity risk:</strong> Some markets may have limited
              liquidity, making it difficult to buy or sell shares at desired
              prices.
            </li>
            <li>
              <strong>Slippage:</strong> Large orders may be filled at prices
              different from the quoted price, particularly in illiquid markets.
            </li>
            <li>
              <strong>Counterparty risk:</strong> Although trades are settled
              on-platform, there is no guarantee of solvency or performance.
            </li>
          </ul>
        </section>

        <section id="market-integrity">
          <h2 className="mb-3 text-base font-semibold">
            2. Market Integrity Risks
          </h2>
          <ul className="list-disc space-y-1 pl-5">
            <li>
              <strong>Manipulation:</strong> Markets may be subject to attempted
              manipulation, including wash trading, spoofing, or coordinated
              trading schemes.
            </li>
            <li>
              <strong>Misinformation:</strong> Market prices may be influenced
              by false or misleading information about the underlying event.
            </li>
            <li>
              <strong>Oracle risk:</strong> Market resolution depends on
              accurate data sources. Inaccurate or unavailable data may affect
              payouts.
            </li>
            <li>
              <strong>Administrative error:</strong> Markets may be resolved
              incorrectly due to human error or technical failure.
            </li>
          </ul>
        </section>

        <section id="regulatory">
          <h2 className="mb-3 text-base font-semibold">3. Regulatory Risk</h2>
          <ul className="list-disc space-y-1 pl-5">
            <li>
              Prediction markets may be subject to unclear or evolving
              regulations in your jurisdiction.
            </li>
            <li>
              Access to the platform may be restricted or terminated in certain
              jurisdictions.
            </li>
            <li>
              Tax treatment of prediction market gains or losses varies by
              jurisdiction and may be unfavorable.
            </li>
            <li>
              Regulatory actions could result in the suspension of trading,
              freezing of funds, or platform shutdown.
            </li>
          </ul>
        </section>

        <section id="technical">
          <h2 className="mb-3 text-base font-semibold">4. Technical Risk</h2>
          <ul className="list-disc space-y-1 pl-5">
            <li>
              <strong>Smart contract risk:</strong> If applicable, bugs or
              vulnerabilities in smart contracts could result in loss of funds.
            </li>
            <li>
              <strong>Platform downtime:</strong> Trading may be unavailable
              during maintenance, outages, or cyber attacks.
            </li>
            <li>
              <strong>Data loss:</strong> Despite backups, there is a risk of
              account or transaction data loss.
            </li>
            <li>
              <strong>Cybersecurity:</strong> The platform may be targeted by
              hackers, potentially compromising user data or funds.
            </li>
          </ul>
        </section>

        <section id="advice">
          <h2 className="mb-3 text-base font-semibold">
            5. No Investment Advice
          </h2>
          <p>
            PredictX does not provide investment, legal, or tax advice. Market
            prices do not constitute recommendations or endorsements. All
            trading decisions are yours alone. You should consult qualified
            professionals before engaging in prediction market trading.
          </p>
        </section>

        <section id="suitability">
          <h2 className="mb-3 text-base font-semibold">6. Suitability</h2>
          <p>Prediction market trading is suitable only for individuals who:</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>
              Understand and can tolerate the risk of total financial loss.
            </li>
            <li>
              Have sufficient financial resources to absorb potential losses
              without affecting their standard of living.
            </li>
            <li>
              Have experience with financial markets and trading platforms.
            </li>
            <li>
              Are not using borrowed funds or funds needed for essential
              expenses.
            </li>
          </ul>
        </section>

        <section id="insurance">
          <h2 className="mb-3 text-base font-semibold">7. No Insurance</h2>
          <p>
            Funds held on the platform are not insured by the FDIC, SIPC, or any
            other government or private insurance scheme. You have no recourse
            against any government agency in the event of a loss.
          </p>
        </section>

        <section id="acknowledgment">
          <h2 className="mb-3 text-base font-semibold">8. Acknowledgment</h2>
          <p>
            By using PredictX, you acknowledge that you have read, understood,
            and accepted these risks. You agree that PredictX and its
            affiliates, officers, and employees are not liable for any losses
            you may incur.
          </p>
        </section>
      </div>
    </LegalLayout>
  )
}
