import { DisplayPageClient } from "./DisplayPageClient"

export const metadata = {
  robots: { index: false, follow: false },
}

export default function DisplayPage() {
  return <DisplayPageClient />
}