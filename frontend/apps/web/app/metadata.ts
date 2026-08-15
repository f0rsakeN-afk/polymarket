import { Metadata } from "next";

const baseUrl = process.env.NEXT_PUBLIC_API_URL?.replace("/api/v1", "") ?? "https://predictx.io";

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
      "Trade on real-world outcomes. Create positions on politics, sports, crypto, finance, and more with a decentralized prediction market.",
    images: [
      {
        url: "/api/og",
        width: 1200,
        height: 630,
        alt: "PredictX — Decentralized Prediction Markets",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "PredictX — Decentralized Prediction Markets",
    description:
      "Trade on real-world outcomes. Create positions on politics, sports, crypto, finance, and more.",
    images: ["/api/og"],
    creator: "@PredictX",
  },
  alternates: {
    canonical: baseUrl,
    languages: {
      "en-US": baseUrl,
    },
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
    apple: "/apple-touch-icon.png",
  },
  manifest: "/site.webmanifest",
};
