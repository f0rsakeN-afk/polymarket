import { MarketDetailClient } from "./MarketDetailClient"

export async function generateMetadata({ params }: { params: { slug: string } }) {
  return {
    title: "Market | PredictX",
    description: "Trade on this prediction market on PredictX.",
  }
}

export default function MarketPage() {
  return <MarketDetailClient />
}
