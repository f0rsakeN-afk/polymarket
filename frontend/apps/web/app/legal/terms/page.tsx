import Link from "next/link"

export default function TermsPage() {
  return (
    <div className="container mx-auto max-w-3xl px-4 py-12">
      <Link href="/legal" className="text-xs text-muted-foreground hover:text-foreground mb-4 inline-block">
        &larr; Back to Legal
      </Link>

      <h1 className="text-2xl font-bold mb-6">Terms of Service</h1>
      <p className="text-xs text-muted-foreground mb-8">Last updated: July 26, 2026</p>

      <div className="space-y-6 text-sm leading-relaxed text-foreground/90">
        <section>
          <h2 className="text-base font-semibold mb-2">1. Acceptance of Terms</h2>
          <p>
            By accessing or using Polymarket, you agree to be bound by these Terms of Service (&ldquo;Terms&rdquo;). If you do not agree, you may not use the platform.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-2">2. Eligibility</h2>
          <p>You represent and warrant that:</p>
          <ul className="list-disc pl-5 mt-2 space-y-1">
            <li>You are at least 18 years of age or the age of majority in your jurisdiction.</li>
            <li>You are not a resident of a restricted jurisdiction as determined by Polymarket.</li>
            <li>Your use of the platform complies with all applicable laws and regulations.</li>
            <li>You have not been previously suspended or removed from the platform.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-2">3. Account Registration</h2>
          <p>
            You are responsible for maintaining the confidentiality of your account credentials and for all activity under your account. You agree to notify us immediately of any unauthorized use.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-2">4. Trading Rules</h2>
          <ul className="list-disc pl-5 space-y-1">
            <li>All trades are final once executed on the blockchain or platform order book.</li>
            <li>Market outcomes are determined by the resolution criteria specified at market creation.</li>
            <li>Polymarket reserves the right to cancel or void markets in cases of manifest error, manipulation, or technical failure.</li>
            <li>Users may not engage in wash trading, front-running, or any form of market manipulation.</li>
            <li>Limit orders are placed at your specified price and may be partially filled.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-2">5. Fees</h2>
          <p>
            Polymarket charges a protocol fee on each trade as disclosed on the platform. Fees are subject to change with reasonable notice. You are responsible for any applicable taxes.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-2">6. Market Resolution</h2>
          <p>
            Markets are resolved by authorized administrators based on the resolution criteria. Resolution decisions are final and binding. In the event of a dispute, Polymarket&rsquo;s internal review process shall be the sole remedy.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-2">7. Prohibited Conduct</h2>
          <p>You agree not to:</p>
          <ul className="list-disc pl-5 mt-2 space-y-1">
            <li>Use the platform for any illegal purpose or in violation of any law.</li>
            <li>Attempt to manipulate market prices or outcomes.</li>
            <li>Interfere with the proper functioning of the platform, including introducing malware or conducting denial-of-service attacks.</li>
            <li>Use automated scripts or bots without express written permission.</li>
            <li>Provide false or misleading information during account registration or KYC.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-2">8. Intellectual Property</h2>
          <p>
            All content on the platform, including but not limited to text, graphics, logos, and software, is the property of Polymarket or its licensors and is protected by intellectual property laws.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-2">9. Limitation of Liability</h2>
          <p>
            Polymarket and its affiliates shall not be liable for any indirect, incidental, special, consequential, or punitive damages arising from your use of the platform. The platform is provided &ldquo;as is&rdquo; without warranties of any kind, either express or implied.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-2">10. Termination</h2>
          <p>
            We reserve the right to suspend or terminate your account at any time for violation of these Terms or for any other reason. Upon termination, your right to use the platform immediately ceases.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-2">11. Dispute Resolution</h2>
          <p>
            Any disputes arising under these Terms shall be resolved through binding arbitration in accordance with the rules of the American Arbitration Association. You waive any right to participate in a class action or class-wide arbitration.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-2">12. Changes to Terms</h2>
          <p>
            We may modify these Terms at any time. Material changes will be notified via email or platform notice. Continued use after changes constitutes acceptance of the new Terms.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-2">13. Contact</h2>
          <p>
            For questions about these Terms, please contact legal@polymarket.example.com.
          </p>
        </section>
      </div>
    </div>
  )
}
