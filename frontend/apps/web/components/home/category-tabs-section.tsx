"use client"

import { useSearchParams } from "next/navigation"
import CategoryTabs from "@/components/home/category-tabs"

export default function CategoryTabsSection() {
  const searchParams = useSearchParams()
  const tag = searchParams.get("tag") ?? "All"
  return <CategoryTabs tag={tag} />
}
