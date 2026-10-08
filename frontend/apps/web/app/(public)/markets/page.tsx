import { MarketsPageClient } from "./MarketsPageClient"

export const metadata = {
  title: "Markets",
  description: "Browse prediction markets on PredictX. Trade on politics, crypto, sports, finance, and real-world outcomes.",
}

export default function MarketsPage() {
  return <MarketsPageClient />
}
