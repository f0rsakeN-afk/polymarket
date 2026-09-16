import { Suspense } from "react"
import { ResetPasswordClient } from "../../../components/auth/ResetPasswordClient"

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<div className="flex h-32 items-center justify-center" role="status" aria-label="Loading"><span className="size-4 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-foreground" /></div>}>
      <ResetPasswordClient />
    </Suspense>
  )
}
