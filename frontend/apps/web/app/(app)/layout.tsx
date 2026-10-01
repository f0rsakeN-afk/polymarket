import type { Metadata } from "next"
import Header from "@/components/shared/header"
import Footer from "@/components/shared/footer"
import { config } from "@/lib/config"

const baseUrl = config.siteUrl

export const metadata: Metadata = {
  alternates: {
    canonical: baseUrl,
  },
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <Header />
      <main id="main-content" className="flex-1 outline-none" tabIndex={-1}>
        {children}
      </main>
      <Footer />
    </div>
  )
}
