"use client"

/**
 * Admin sign-in.
 *
 * ## Why this exists
 *
 * The admin app shares the API's auth cookies, so a signed-in operator needs
 * nothing here. But "already signed in somewhere else" is not a sign-in flow: open
 * this app on a fresh machine, or after a session expired, and the shell shows
 * "Admin access required" with no way forward. Sharing a session is a reasonable
 * design; having no way to *establish* one from here is not, and the person who
 * most needs the admin tool is often the one not currently signed in to the
 * storefront.
 *
 * ## The 2FA field is revealed, not shown up front
 *
 * `/auth/me` deliberately does not disclose whether an account has 2FA, so this
 * form cannot know. It asks for the password, and when the server answers
 * `LOGIN_2FA_REQUIRED` it reveals the code field and keeps what was typed.
 *
 * That answer is a machine-readable code precisely so this form does not have to
 * match on "2FA code required" - an English string that could be reworded, and
 * whose rewording would then silently show a non-2FA admin a code field after a
 * mistyped password.
 */

import { useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { sileo } from "sileo"
import { ShieldAlert } from "lucide-react"

import { api, apiErrorCode, apiErrorMessage } from "@workspace/api-client/client"
import { adminLoginSchema } from "@workspace/schemas/auth"
import { Button, buttonVariants } from "@workspace/ui/components/button"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Input } from "@workspace/ui/components/input"
import { Field, FieldError, FieldGroup, FieldLabel } from "@workspace/ui/components/field"
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@workspace/ui/components/input-otp"
import { Spinner } from "@workspace/ui/components/spinner"
import { cn } from "@workspace/ui/lib/utils"

/**
 * `reason` and `next` arrive as props from the server component rather than from
 * `useSearchParams()`, which would force this page out of static prerendering.
 */
export function AdminLoginClient({
  reason,
  next: rawNext,
}: {
  reason?: string
  next?: string
}) {
  const router = useRouter()
  const qc = useQueryClient()

  // What the proxy decided, so this page can say it out loud rather than showing
  // a form to someone who cannot use it.
  const notAdmin = reason === "not-admin"
  // Same-origin paths only. `//evil.example` is protocol-relative, so it is an
  // absolute URL to a host we do not control — the proxy checks for this too, but
  // a redirect target is worth validating at both ends.
  const next =
    rawNext && rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/"

  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [code, setCode] = useState("")
  const [requiresCode, setRequiresCode] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const login = useMutation({
    mutationFn: async () => {
      if (requiresCode && code.length !== 6) throw new Error("Enter your 6-digit code")
      return api.post<{ data?: { is_admin?: boolean } }>("/api/v1/auth/login", {
        email,
        password,
        ...(requiresCode ? { totp_code: code } : {}),
      })
    },
    onSuccess: async () => {
      // The cache is keyed on "who is signed in", and this just changed. Clearing
      // rather than invalidating: every cached entry was fetched under the old
      // (anonymous or previous-user) session, and `invalidateQueries` would refetch
      // them one by one - letting the operator see the previous operator's data in
      // the gap.
      qc.clear()
      sileo.success({ title: "Signed in" })
      router.replace(next)
      router.refresh()
    },
    onError: (err) => {
      const code_ = apiErrorCode(err)
      if (code_ === "LOGIN_2FA_REQUIRED") {
        // Not a failure: the password was accepted and the account has 2FA.
        // Keep the password so only the code has to be typed.
        setRequiresCode(true)
        setError(null)
        return
      }
      if (code_ === "LOGIN_2FA_INVALID") setCode("")
      setError(
        apiErrorMessage(err, "Could not sign in. Check the email and password and try again.")
      )
    },
  })

  /**
   * The rules come from `@workspace/schemas`, not from length checks restated here.
   *
   * `adminLoginSchema` is parameterised by `requiresCode` so there is one rule set
   * rather than two: a hand-written `code.length === 6` sitting next to a zod
   * email check is how a form ends up enforcing the password one way and the code
   * another.
   */
  const parsed = useMemo(
    () =>
      adminLoginSchema.safeParse({
        email,
        password,
        ...(requiresCode ? { totp_code: code } : {}),
      }),
    [email, password, code, requiresCode]
  )
  const canSubmit = parsed.success
  const fieldError = (field: "email" | "password" | "totp_code"): string | null => {
    if (parsed.success) return null
    return parsed.error.issues.find((i) => i.path[0] === field)?.message ?? null
  }

  const emailProblem = fieldError("email")
  const passwordProblem = fieldError("password")
  const codeProblem = fieldError("totp_code")

  return (
    <div className="flex min-h-dvh items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardContent className="px-6 py-7">
          {notAdmin ? (
            /* The proxy sends a signed-in non-admin here with `?reason=not-admin`.
               Showing the sign-in form instead would invite a second attempt that
               cannot help — they are not going to become an admin by signing in
               again — and it is the same shape as "you are signed out", which is
               exactly the confusion worth removing. */
            <div className="space-y-3 text-center">
              <ShieldAlert className="mx-auto size-7 text-destructive" />
              <h1 className="text-lg font-semibold">Admin access required</h1>
              <p className="text-sm text-muted-foreground">
                This account is signed in, but it does not have admin access, so there is
                nothing to sign in to here.
              </p>
              <a
                href={process.env.NEXT_PUBLIC_SITE_URL ?? "/"}
                className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-full")}
              >
                Go to the site
              </a>
              <p className="text-xs text-muted-foreground">
                If that is unexpected, ask an existing admin to check your role.
              </p>
            </div>
          ) : (
            <>
              <h1 className="text-lg font-semibold">Sign in to Admin</h1>
              <p className="mt-1 text-xs text-muted-foreground">
                Admin accounts only. Signing in elsewhere does not carry over.
              </p>

              <form
                className="mt-5"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (!canSubmit || login.isPending) return
                  setError(null)
                  login.mutate()
                }}
              >
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="admin-login-email">Email</FieldLabel>
                <Input
                  id="admin-login-email"
                  type="email"
                  autoComplete="username"
                  autoFocus
                  value={email}
                  disabled={login.isPending}
                  aria-invalid={emailProblem ? true : undefined}
                  onChange={(event) => setEmail(event.target.value)}
                />
                {emailProblem ? <FieldError role="alert">{emailProblem}</FieldError> : null}
              </Field>

              <Field>
                <FieldLabel htmlFor="admin-login-password">Password</FieldLabel>
                <Input
                  id="admin-login-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  disabled={login.isPending}
                  aria-invalid={error || passwordProblem ? true : undefined}
                  onChange={(event) => setPassword(event.target.value)}
                />
                {passwordProblem ? <FieldError role="alert">{passwordProblem}</FieldError> : null}
              </Field>

              {requiresCode ? (
                <Field>
                  <FieldLabel htmlFor="admin-login-code">Two-factor code</FieldLabel>
                  <InputOTP
                    id="admin-login-code"
                    aria-label="Two-factor authentication code"
                    maxLength={6}
                    value={code}
                    disabled={login.isPending}
                    onChange={setCode}
                    render={({ slots }) => (
                      <InputOTPGroup>
                        {(slots ?? []).map((slot, index) => (
                          <InputOTPSlot
                            key={index}
                            index={index}
                            char={slot.char}
                            isActive={slot.isActive}
                            hasFakeCaret={slot.hasFakeCaret}
                            className="h-10 w-9 text-center text-base font-semibold"
                          />
                        ))}
                      </InputOTPGroup>
                    )}
                  />
                {codeProblem ? <FieldError role="alert">{codeProblem}</FieldError> : null}
              </Field>
              ) : null}

              {error ? (
                <FieldError role="alert">{error}</FieldError>
              ) : null}
            </FieldGroup>

            <Button type="submit" className="mt-5 w-full" disabled={!canSubmit || login.isPending}>
              {login.isPending ? (
                <>
                  <Spinner className="size-3.5" />
                  Signing in…
                </>
              ) : (
                "Sign in"
              )}
            </Button>
              </form>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}