import { LegalLayout } from "@/components/shared/legal-layout"

export const metadata = {
  title: "Privacy Policy",
  description: "Privacy policy for PredictX prediction markets.",
}

const sections = [
  { id: "collection", label: "Information We Collect" },
  { id: "usage", label: "How We Use Your Information" },
  { id: "sharing", label: "Data Sharing" },
  { id: "retention", label: "Data Retention" },
  { id: "cookies", label: "Cookies" },
  { id: "rights", label: "Your Rights" },
  { id: "security", label: "Data Security" },
  { id: "transfers", label: "International Data Transfers" },
  { id: "third-party", label: "Third-Party Services" },
  { id: "childrens-privacy", label: "Children's Privacy" },
  { id: "changes", label: "Changes to This Policy" },
  { id: "contact", label: "Contact" },
]

export default function PrivacyPage() {
  return (
    <LegalLayout
      title="Privacy Policy"
      lastUpdated="July 2026"
      sections={sections}
    >
      <div className="space-y-10 text-sm leading-relaxed text-foreground/90">
        <section id="collection">
          <h2 className="mb-3 text-base font-semibold">
            1. Information We Collect
          </h2>
          <p>We collect information you provide directly:</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>Account information: email address, username, and password.</li>
            <li>
              Identity verification data if required for compliance (KYC).
            </li>
            <li>
              Transaction data: trades, deposits, withdrawals, and wallet
              balances.
            </li>
            <li>Communications: messages sent through our support channels.</li>
          </ul>
          <p className="mt-2">We also automatically collect:</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>
              Usage data: pages visited, features used, time spent on the
              platform.
            </li>
            <li>
              Device data: browser type, operating system, IP address, device
              identifiers.
            </li>
            <li>Cookies and similar tracking technologies (see Section 5).</li>
          </ul>
        </section>

        <section id="usage">
          <h2 className="mb-3 text-base font-semibold">
            2. How We Use Your Information
          </h2>
          <ul className="list-disc space-y-1 pl-5">
            <li>To operate, maintain, and improve the platform.</li>
            <li>To process transactions and maintain account records.</li>
            <li>
              To comply with legal and regulatory obligations (including
              anti-money laundering).
            </li>
            <li>
              To communicate with you about your account, updates, and support
              inquiries.
            </li>
            <li>To detect and prevent fraud, abuse, and security incidents.</li>
            <li>To analyze usage patterns and improve user experience.</li>
          </ul>
        </section>

        <section id="sharing">
          <h2 className="mb-3 text-base font-semibold">3. Data Sharing</h2>
          <p>We may share your information with:</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>
              Service providers who assist in platform operations (hosting,
              analytics, payment processing).
            </li>
            <li>Regulatory authorities as required by applicable law.</li>
            <li>
              Legal advisors and auditors in connection with legal proceedings.
            </li>
          </ul>
          <p className="mt-2">
            We do not sell your personal information to third parties.
          </p>
        </section>

        <section id="retention">
          <h2 className="mb-3 text-base font-semibold">4. Data Retention</h2>
          <p>
            We retain your personal data for as long as your account is active
            and for a reasonable period thereafter to comply with legal
            obligations, resolve disputes, and enforce agreements. Transaction
            records are retained in accordance with applicable financial
            regulations.
          </p>
        </section>

        <section id="cookies">
          <h2 className="mb-3 text-base font-semibold">5. Cookies</h2>
          <p>We use the following types of cookies:</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>
              <strong>Essential cookies:</strong> Required for platform
              functionality, including authentication and session management.
            </li>
            <li>
              <strong>Analytics cookies:</strong> To understand how users
              interact with the platform.
            </li>
            <li>
              <strong>Preference cookies:</strong> To remember your settings and
              preferences.
            </li>
          </ul>
          <p className="mt-2">
            You can control cookies through your browser settings. Disabling
            essential cookies may prevent the platform from functioning
            properly.
          </p>
        </section>

        <section id="rights">
          <h2 className="mb-3 text-base font-semibold">6. Your Rights</h2>
          <p>Depending on your jurisdiction, you may have the right to:</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>Access the personal data we hold about you.</li>
            <li>Rectify inaccurate or incomplete data.</li>
            <li>
              Delete your personal data (subject to legal retention
              requirements).
            </li>
            <li>Restrict or object to processing of your data.</li>
            <li>Data portability to another service provider.</li>
            <li>Withdraw consent where processing is based on consent.</li>
          </ul>
          <p className="mt-2">
            To exercise these rights, contact{" "}
            <a
              href="mailto:privacy@predictx.io"
              className="text-primary hover:underline"
            >
              privacy@predictx.io
            </a>
            .
          </p>
        </section>

        <section id="security">
          <h2 className="mb-3 text-base font-semibold">7. Data Security</h2>
          <p>
            We implement industry-standard technical and organizational measures
            to protect your data, including encryption at rest and in transit,
            access controls, and regular security audits. However, no method of
            transmission or storage is 100% secure.
          </p>
        </section>

        <section id="transfers">
          <h2 className="mb-3 text-base font-semibold">
            8. International Data Transfers
          </h2>
          <p>
            Your data may be processed in jurisdictions other than your own. We
            ensure appropriate safeguards are in place, including Standard
            Contractual Clauses or equivalent mechanisms, for cross-border data
            transfers.
          </p>
        </section>

        <section id="third-party">
          <h2 className="mb-3 text-base font-semibold">
            9. Third-Party Services
          </h2>
          <p>
            The platform may contain links to third-party websites or services.
            We are not responsible for their privacy practices. We encourage you
            to review their privacy policies before providing any personal data.
          </p>
        </section>

        <section id="children">
          <h2 className="mb-3 text-base font-semibold">
            10. Children&rsquo;s Privacy
          </h2>
          <p>
            The platform is not intended for individuals under 18. We do not
            knowingly collect personal data from children. If we become aware
            that a child has provided us with personal data, we will delete it.
          </p>
        </section>

        <section id="changes">
          <h2 className="mb-3 text-base font-semibold">
            11. Changes to This Policy
          </h2>
          <p>
            We may update this Privacy Policy from time to time. Material
            changes will be notified via email or platform notice. Continued use
            after changes constitutes acceptance.
          </p>
        </section>

        <section id="contact">
          <h2 className="mb-3 text-base font-semibold">12. Contact</h2>
          <p>
            For privacy-related inquiries, contact{" "}
            <a
              href="mailto:privacy@predictx.io"
              className="text-primary hover:underline"
            >
              privacy@predictx.io
            </a>
            .
          </p>
        </section>
      </div>
    </LegalLayout>
  )
}
