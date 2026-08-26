import { lazy } from "react";
import type { Metadata } from "next";

const HomePageContent = lazy(() => import("@/components/home/home-page-content"));

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "PredictX — Decentralized Prediction Markets",
  description:
    "Discover and trade on prediction markets. Create positions on politics, sports, crypto, finance, and real-world outcomes on PredictX.",
  openGraph: {
    title: "PredictX — Decentralized Prediction Markets",
    description:
      "Discover and trade on prediction markets. Create positions on politics, sports, crypto, finance, and real-world outcomes.",
  },
};

export default function HomePage() {
  return <HomePageContent />;
}
