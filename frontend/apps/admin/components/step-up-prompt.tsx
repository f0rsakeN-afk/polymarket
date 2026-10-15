"use client"

/**
 * Step-up: proving the operator is present, for an action an admin *session* is
 * not authority to take.
 *
 * ## Why the 2FA field is not shown up front
 *
 * `/auth/me` does not say whether the signed-in admin has 2FA enabled, and it
 * should not: telling a caller "this account has 2FA" is a disclosure about the
 * account that an unauthenticated-adjacent surface has no business making. So the
 * prompt cannot know, and guessing has two ways to be wrong.
 *
 * Guessing *low* asks a 2FA admin for a password that will be refused, and then
 * asks again - a round trip that reads as the app failing. Guessing *high* asks a
 * password-only admin for a code they do not have, and leaves them staring at a
 * six-box field with nothing to type in it.
 *
 * So the field is driven by the server's answer instead: submit the password, and
 * when the response says 2FA is required, reveal the code field and keep the
 * password they already typed. `STEP_UP_2FA_REQUIRED` is a specific instruction,
 * not a failure - it is treated as a normal step in the flow rather than an error,
 * which is why it never renders in the error region.
 *
 * The mirror of this on the server is deliberate: `code` is required by the *server*
 * when the account has 2FA, so a client that simply omitted it could not downgrade
 * the action to password-only. A UI that guesses cannot weaken that, and must not
 * be able to.
 */

import { useEffect, useId, useMemo, useRef, useState } from "react"
import { TriangleAlert } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@workspace/ui/components/field"
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@workspace/ui/components/input-otp"

import { stepUpSchemaFor } from "@/schemas/privileged"
import { Spinner } from "@workspace/ui/components/spinner"

export interface StepUpCredentials {
  password: string
  code?: string
}

export interface StepUpPromptProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** What is about to happen, in the operator's own words. */
  title: string
  description: React.ReactNode
  /** The consequence of going ahead, stated before the credentials are asked for. */
  consequence?: React.ReactNode
  /** Server-reported message from the last attempt, if it failed. */
  error?: string | null
  /**
   * The machine-readable code behind `error`.
   *
   * Present so this component can clear *the field that was wrong* rather than
   * both: a mistyped code should not also wipe a password the server just
   * accepted, and a wrong password must not leave the previous one sitting in a
   * field for the next attempt to submit.
   */
  errorCode?: string
  /** Set once the server has said this account has 2FA. */
  requiresCode: boolean
  pending: boolean
  confirmLabel?: string
  onSubmit: (credentials: StepUpCredentials) => void
}

export function StepUpPrompt({
  open,
  onOpenChange,
  title,
  description,
  consequence,
  error,
  errorCode,
  requiresCode,
  pending,
  confirmLabel = "Confirm",
  onSubmit,
}: StepUpPromptProps) {
  const [password, setPassword] = useState("")
  const [code, setCode] = useState("")
  const codeId = useId()
  const codeRef = useRef<HTMLDivElement>(null)

  /**
   * Credential lifetime, adjusted during render rather than in an effect.
   *
   * Three rules, all driven by a prop rather than by anything the operator did:
   * closing wipes both fields, a rejected password wipes the password, a rejected
   * code wipes the code. Clearing only the rejected field is the point - the
   * server *accepted* the password when it asked for a code, so making the
   * operator retype it is friction that teaches people to paste faster.
   *
   * This is React's documented "adjust state when a prop changes" pattern: the
   * alternative is an effect, which renders once with the stale value, then again
   * with the cleared one. Here React discards the in-progress render and restarts,
   * so the operator never sees a frame containing a credential that has been
   * rejected. It also sidesteps a stale-value frame in the other direction - an
   * effect that clears on close leaves the password in state for one render after
   * the dialog has gone.
   */
  const [seen, setSeen] = useState({ open, errorCode })
  if (seen.open !== open || seen.errorCode !== errorCode) {
    if (!open) {
      setPassword("")
      setCode("")
    } else if (errorCode === "STEP_UP_PASSWORD_INVALID") {
      setPassword("")
    } else if (errorCode === "STEP_UP_2FA_INVALID") {
      setCode("")
    }
    setSeen({ open, errorCode })
  }

  // Focus is a genuine side effect on the DOM, not a state adjustment, so it
  // belongs in an effect. When the server reveals that a code is needed, put the
  // caret in it: the operator has already proved who they are with the password,
  // and making them reach for a field they were never shown is the kind of
  // friction that gets people clicking through instead of reading.
  useEffect(() => {
    if (open && requiresCode) codeRef.current?.focus()
  }, [open, requiresCode])

  /**
   * Validation comes from `stepUpSchemaFor`, not from `password.length > 0` restated
   * here. Two rule sets is how a prompt ends up accepting a five-digit code that the
   * field looks six boxes wide - the field and the rule disagree, and the submit
   * button is the only thing standing between them and a confusing 422.
   */
  const parsed = useMemo(
    () => stepUpSchemaFor(requiresCode).safeParse({ password, code: code || undefined }),
    [requiresCode, password, code]
  )
  const canSubmit = parsed.success

  /** Only surface a field's problem once it is the field being worked on. */
  const fieldError = (field: "password" | "code"): string | null => {
    if (parsed.success) return null
    const issue = parsed.error.issues.find((i) => i.path[0] === field)
    if (!issue) return null
    if (field === "password" && password.length === 0) return null
    if (field === "code" && code.length === 0) return null
    return issue.message
  }

  const passwordProblem = fieldError("password")
  const codeProblem = fieldError("code")

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" showCloseButton={!pending}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        {consequence ? (
          <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
            {consequence}
          </div>
        ) : null}

        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (!canSubmit || pending) return
            onSubmit({ password, ...(requiresCode ? { code } : {}) })
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="step-up-password">Your password</FieldLabel>
              <Input
                id="step-up-password"
                type="password"
                autoComplete="current-password"
                autoFocus
                value={password}
                disabled={pending}
                aria-invalid={error || passwordProblem ? true : undefined}
                onChange={(event) => setPassword(event.target.value)}
              />
              {passwordProblem ? <FieldError role="alert">{passwordProblem}</FieldError> : null}
            </Field>

            {/* Mounted only once the server has said it is needed. See the note
                at the top of this file for why it is not rendered up front. */}
            {requiresCode ? (
              <Field data-slot="step-up-code" ref={codeRef} tabIndex={-1}>
                <FieldLabel htmlFor={codeId}>Two-factor code</FieldLabel>
                <InputOTP
                  id={codeId}
                  aria-label="Two-factor authentication code"
                  maxLength={6}
                  value={code}
                  disabled={pending}
                  autoFocus={false}
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
              <FieldError
                // `role="alert"` so the failure is announced: this is the result
                // of the operator pressing the key, and a silent refusal on a
                // privileged action reads as a broken button.
                role="alert"
              >
                <span className="flex items-start gap-1.5">
                  <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  <span>{error}</span>
                </span>
              </FieldError>
            ) : null}

            <FieldDescription>
              This is recorded against your account in the audit trail.
            </FieldDescription>
          </FieldGroup>

          <DialogFooter className="mt-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={pending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit || pending}>
              {pending ? (
                <>
                  <Spinner className="size-3.5" />
                  Checking…
                </>
              ) : (
                confirmLabel
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}