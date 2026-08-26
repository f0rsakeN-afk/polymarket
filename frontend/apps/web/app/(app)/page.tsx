"use client"

import { lazy, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import CategoryTabs from "@/components/home/category-tabs"

const HomePageContent = lazy(() => import("@/components/home/home-page-content"))

export const dynamic = "force-dynamic"

function CategoryTabsSection() {
  const searchParams = useSearchParams()
  const tag = searchParams.get("tag") ?? "All"
  return <CategoryTabs tag={tag} />
}

export default function HomePage() {
  return (
    <>
      <div className="bg-background/80 backdrop-blur sticky top-14 z-30">
        <div className="container mx-auto max-w-7xl px-4 py-2">
          <Suspense fallback={<div className="h-9" />}>
            <CategoryTabsSection />
          </Suspense>
        </div>
      </div>
      <Suspense fallback={null}>
        <HomePageContent />
      </Suspense>
    </>
  )
}
