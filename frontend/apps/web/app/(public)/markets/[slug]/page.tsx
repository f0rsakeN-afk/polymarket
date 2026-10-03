import { MarketDetailClient } from "./MarketDetailClient"

export async function generateMetadata() {
  return {
    title: "Market | Polymarket",
    description: "Trade on this prediction market on Polymarket.",
  }
}

export default function MarketPage() {
  return <MarketDetailClient />
}
