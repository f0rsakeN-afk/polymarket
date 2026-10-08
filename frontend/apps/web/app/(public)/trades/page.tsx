import { TradesPageClient } from "./TradesPageClient"

export const metadata = {
  title: "Trade Feed",
  description: "Recent trades across all PredictX prediction markets. See what positions other traders are taking.",
}

export default function TradesPage() {
  return <TradesPageClient />
}
