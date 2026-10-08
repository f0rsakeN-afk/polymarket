import type { Metadata } from "next"
import { Suspense } from "react"
import { SignupForm } from "@/components/auth/signup-form"

export const metadata: Metadata = {
  title: "Create Account",
  description:
    "Create your PredictX account and start trading on prediction markets.",
}

export default function SignupPage() {
  return (
    <Suspense>
      <SignupForm />
    </Suspense>
  )
}
