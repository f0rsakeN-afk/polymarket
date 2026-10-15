import type { Metadata } from "next"

import "./globals.css"
import { Providers } from "@/components/providers"

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
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}