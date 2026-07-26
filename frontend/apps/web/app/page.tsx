import { Suspense, lazy } from "react"
import { Spinner } from "@workspace/ui/components/spinner"

const HomePageContent = lazy(() => import("@/components/home/home-page-content"))

export const dynamic = "force-dynamic"

export default function HomePage() {
  return (
    // <Suspense fallback={
    //   <div className="flex h-64 items-center justify-center">
    //     <Spinner className="size-5" />
    //   </div>
    // }>
      <HomePageContent />
    // </Suspense>
  )
}
