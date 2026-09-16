import type { Metadata } from "next"
import { Suspense } from "react"
import { LoginForm } from "@/components/auth/login-form"

export const metadata: Metadata = {
  title: "Sign In",
  description: "Sign in to your PredictX account to trade on prediction markets.",
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="flex h-32 items-center justify-center" role="status" aria-label="Loading"><span className="size-4 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-foreground" /></div>}>
      <LoginForm />
    </Suspense>
  )
}
