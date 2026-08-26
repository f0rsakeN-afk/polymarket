import { LegalLayout } from "@/components/shared/legal-layout"

export const metadata = {
  title: "Terms of Service",
  description: "Terms of service for PredictX prediction markets.",
}

const sections = [
  { id: "acceptance", label: "Acceptance of Terms" },
  { id: "eligibility", label: "Eligibility" },
  { id: "account", label: "Account Registration" },
  { id: "trading", label: "Trading Rules" },
  { id: "fees", label: "Fees" },
  { id: "resolution", label: "Market Resolution" },
  { id: "prohibited", label: "Prohibited Conduct" },
  { id: "ip", label: "Intellectual Property" },
  { id: "liability", label: "Limitation of Liability" },
  { id: "termination", label: "Termination" },
  { id: "disputes", label: "Dispute Resolution" },
  { id: "changes", label: "Changes to Terms" },
  { id: "contact", label: "Contact" },
]

export default function TermsPage() {
  return (
    <LegalLayout title="Terms of Service" lastUpdated="July 2026" sections={sections}>
      <div className="space-y-10 text-sm leading-relaxed text-foreground/90">
        <section id="acceptance">
          <h2 className="text-base font-semibold mb-3">1. Acceptance of Terms</h2>
          <p>
            By accessing or using PredictX, you agree to be bound by these Terms of Service
            (&ldquo;Terms&rdquo;). If you do not agree, you may not use the platform.
          </p>
        </section>

        <section id="eligibility">
          <h2 className="text-base font-semibold mb-3">2. Eligibility</h2>
          <p>You represent and warrant that:</p>
          <ul className="list-disc pl-5 mt-2 space-y-1">
            <li>You are at least 18 years of age or the age of majority in your jurisdiction.</li>
            <li>You are not a resident of a restricted jurisdiction as determined by PredictX.</li>
            <li>Your use of the platform complies with all applicable laws and regulations.</li>
            <li>You have not been previously suspended or removed from the platform.</li>
          </ul>
        </section>

        <section id="account">
          <h2 className="text-base font-semibold mb-3">3. Account Registration</h2>
          <p>
            You are responsible for maintaining the confidentiality of your account credentials and for
            all activity under your account. You agree to notify us immediately of any unauthorized
            use.
          </p>
        </section>

        <section id="trading">
          <h2 className="text-base font-semibold mb-3">4. Trading Rules</h2>
          <ul className="list-disc pl-5 space-y-1">
            <li>All trades are final once executed on the blockchain or platform order book.</li>
            <li>
              Market outcomes are determined by the resolution criteria specified at market creation.
            </li>
            <li>
              PredictX reserves the right to cancel or void markets in cases of manifest error,
              manipulation, or technical failure.
            </li>
            <li>
              Users may not engage in wash trading, front-running, or any form of market manipulation.
            </li>
            <li>Limit orders are placed at your specified price and may be partially filled.</li>
          </ul>
        </section>

        <section id="fees">
          <h2 className="text-base font-semibold mb-3">5. Fees</h2>
          <p>
            PredictX charges a protocol fee on each trade as disclosed on the platform. Fees are
            subject to change with reasonable notice. You are responsible for any applicable taxes.
          </p>
        </section>

        <section id="resolution">
          <h2 className="text-base font-semibold mb-3">6. Market Resolution</h2>
          <p>
            Markets are resolved by authorized administrators based on the resolution criteria.
            Resolution decisions are final and binding. In the event of a dispute, PredictX&rsquo;s
            internal review process shall be the sole remedy.
          </p>
        </section>

        <section id="prohibited">
          <h2 className="text-base font-semibold mb-3">7. Prohibited Conduct</h2>
          <p>You agree not to:</p>
          <ul className="list-disc pl-5 mt-2 space-y-1">
            <li>Use the platform for any illegal purpose or in violation of any law.</li>
            <li>Attempt to manipulate market prices or outcomes.</li>
            <li>
              Interfere with the proper functioning of the platform, including introducing malware or
              conducting denial-of-service attacks.
            </li>
            <li>Use automated scripts or bots without express written permission.</li>
            <li>Provide false or misleading information during account registration or KYC.</li>
          </ul>
        </section>

        <section id="ip">
          <h2 className="text-base font-semibold mb-3">8. Intellectual Property</h2>
          <p>
            All content on the platform, including but not limited to text, graphics, logos, and
            software, is the property of PredictX or its licensors and is protected by intellectual
            property laws.
          </p>
        </section>

        <section id="liability">
          <h2 className="text-base font-semibold mb-3">9. Limitation of Liability</h2>
          <p>
            PredictX and its affiliates shall not be liable for any indirect, incidental, special,
            consequential, or punitive damages arising from your use of the platform. The platform
            is provided &ldquo;as is&rdquo; without warranties of any kind, either express or implied.
          </p>
        </section>

        <section id="termination">
          <h2 className="text-base font-semibold mb-3">10. Termination</h2>
          <p>
            We reserve the right to suspend or terminate your account at any time for violation of
            these Terms or for any other reason. Upon termination, your right to use the platform
            immediately ceases.
          </p>
        </section>

        <section id="disputes">
          <h2 className="text-base font-semibold mb-3">11. Dispute Resolution</h2>
          <p>
            Any disputes arising under these Terms shall be resolved through binding arbitration in
            accordance with the rules of the American Arbitration Association. You waive any right
            to participate in a class action or class-wide arbitration.
          </p>
        </section>

        <section id="changes">
          <h2 className="text-base font-semibold mb-3">12. Changes to Terms</h2>
          <p>
            We may modify these Terms at any time. Material changes will be notified via email or
            platform notice. Continued use after changes constitutes acceptance of the new Terms.
          </p>
        </section>

        <section id="contact">
          <h2 className="text-base font-semibold mb-3">13. Contact</h2>
          <p>For questions about these Terms, please contact{" "}
            <a href="mailto:legal@predictx.io" className="text-primary hover:underline">
              legal@predictx.io
            </a>
            .
          </p>
        </section>
      </div>
    </LegalLayout>
  )
}
