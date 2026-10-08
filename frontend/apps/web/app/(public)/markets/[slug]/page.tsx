import { MarketDetailClient } from "./MarketDetailClient"

export async function generateMetadata() {
  return {
    title: "Market | PredictX",
    description: "Trade on this prediction market on PredictX.",
  }
}

export default function MarketPage() {
  return <MarketDetailClient />
}
