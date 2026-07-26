"use client"

import { useTheme } from "next-themes"
import { useEffect, useState } from "react"
import { Toaster as SileoToaster } from "sileo"

export function Toaster() {
  const { resolvedTheme } = useTheme()
  const [mounted, setMounted] = useState(false)

  useEffect(() => setMounted(true), [])

  if (!mounted) return null

  return (
    <SileoToaster
      position="bottom-right"
      theme={resolvedTheme as "light" | "dark" | "system"}
      options={{ duration: 4000 }}
    />
  )
}
