"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { SearchIcon } from "lucide-react"

interface SearchInputProps {
  className?: string
}

export function SearchInput({ className }: SearchInputProps) {
  const router = useRouter()
  const [value, setValue] = useState("")
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isUserTypingRef = useRef(false)

  const updateURL = useCallback(
    (q: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(() => {
        if (q.trim()) {
          router.replace(`/?q=${encodeURIComponent(q.trim())}`)
        } else {
          router.replace("/")
        }
      }, 300)
    },
    [router]
  )

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    isUserTypingRef.current = true
    const v = e.target.value
    setValue(v)
    updateURL(v)
  }, [updateURL])

  // Sync with URL when back/forward is pressed — runs on every navigation
  useEffect(() => {
    if (!isUserTypingRef.current) {
      // Extract q from the URL directly
      const url = new URL(window.location.href)
      const q = url.searchParams.get("q") ?? ""
      setValue(q)
    }
    isUserTypingRef.current = false
  }, []) // Only on mount — back/forward is handled via popstate events

  // Listen for popstate (back/forward browser buttons)
  useEffect(() => {
    const handlePopstate = () => {
      isUserTypingRef.current = false
      const url = new URL(window.location.href)
      const q = url.searchParams.get("q") ?? ""
      setValue(q)
    }
    window.addEventListener("popstate", handlePopstate)
    return () => window.removeEventListener("popstate", handlePopstate)
  }, [])

  return (
    <div className={`relative ${className ?? ""}`}>
      <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground pointer-events-none" />
      <input
        type="text"
        value={value}
        onChange={handleChange}
        placeholder="Search markets..."
        className="w-full h-8 pl-9 pr-4 rounded-md border border-border bg-background text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
      />
    </div>
  )
}
