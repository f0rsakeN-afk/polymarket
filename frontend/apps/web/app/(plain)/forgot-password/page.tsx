import { Suspense } from "react"
import { ForgotPasswordClient } from "../../../components/auth/ForgotPasswordClient"

export default function ForgotPasswordPage() {
  return (
    <Suspense fallback={<div className="flex h-32 items-center justify-center" role="status" aria-label="Loading"><span className="size-4 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-foreground" /></div>}>
      <ForgotPasswordClient />
    </Suspense>
  )
}
