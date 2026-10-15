import type { Metadata } from "next"

import "./globals.css"
import { Providers } from "@/components/providers"
import { ThemeProvider } from "@/components/theme-provider"

export const metadata: Metadata = {
  title: {
    default: "PredictX Admin",
    template: "%s • PredictX Admin",
  },
  // An operator surface has no business in a search index.
  robots: { index: false, follow: false },
  // Belt and braces with the CSP's `frame-ancestors 'none'`: no browser or
  // crawler should ever be told this exists.
  referrer: "no-referrer",
}

export default function AdminRootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning className="antialiased font-sans">
      <body>
        {/* Dark by default, matching apps/web. An operator reading a ledger for
            hours is the case where a light background is genuinely unpleasant,
            and two apps on one origin disagreeing about theme reads as a bug in
            whichever one you did not expect. */}
        <ThemeProvider>
          <Providers>{children}</Providers>
        </ThemeProvider>
      </body>
    </html>
  )
}