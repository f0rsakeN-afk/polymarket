import { Geist_Mono, Inter } from "next/font/google"
import type { Metadata } from "next"

import "@workspace/ui/globals.css"
import "sileo/styles.css"
import { ThemeProvider } from "@/components/theme-provider"
import { Providers } from "@/components/providers"
import { Toaster } from "@/components/toaster"
import { cn } from "@workspace/ui/lib/utils"

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" })

const fontMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
})

const baseUrl = process.env.NEXT_PUBLIC_API_URL?.replace("/api/v1", "") ?? "https://predictx.io"

export const metadata: Metadata = {
  metadataBase: new URL(baseUrl),
  title: {
    default: "PredictX — Decentralized Prediction Markets",
    template: "%s | PredictX",
  },
  description:
    "Trade on real-world outcomes with PredictX — a decentralized prediction market platform. Create positions on politics, sports, crypto, finance, and more.",
  keywords: [
    "prediction market",
    "decentralized exchange",
    "crypto trading",
    "polymarket alternative",
    "outcome betting",
    "real world assets",
    "trading platform",
  ],
  authors: [{ name: "PredictX" }],
  creator: "PredictX",
  publisher: "PredictX",
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
  openGraph: {
    type: "website",
    locale: "en_US",
    url: baseUrl,
    siteName: "PredictX",
    title: "PredictX — Decentralized Prediction Markets",
    description:
      "Trade on real-world outcomes. Create positions on politics, sports, crypto, finance, and more.",
    images: [{ url: "/api/og", width: 1200, height: 630, alt: "PredictX" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "PredictX — Decentralized Prediction Markets",
    description: "Trade on real-world outcomes. Create positions on politics, sports, crypto, finance, and more.",
    images: ["/api/og"],
    creator: "@PredictX",
  },
  alternates: {
    canonical: baseUrl,
    languages: { "en-US": baseUrl },
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={cn("antialiased", fontMono.variable, "font-sans", inter.variable)}
    >
      <body>
        <ThemeProvider>
          <Providers>
            <Toaster />
            <a
              href="#main-content"
              className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:ring-2 focus:ring-ring"
            >
              Skip to main content
            </a>
            {children}
          </Providers>
        </ThemeProvider>
      </body>
    </html>
  )
}
