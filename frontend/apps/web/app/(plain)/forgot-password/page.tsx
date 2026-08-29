import { Suspense } from "react"
import { ForgotPasswordClient } from "../../../components/auth/ForgotPasswordClient"

export default function ForgotPasswordPage() {
  return (
    <Suspense>
      <ForgotPasswordClient />
    </Suspense>
  )
}
