"use client"

/**
 * The step-up flow, as state.
 *
 * Separated from the prompt itself so that every privileged action gets the same
 * behaviour without each one re-deriving it. The bug this prevents is specific
 * and has already happened once in this codebase's shape: a client that always
 * sends both `password` and `code`, or that treats `STEP_UP_2FA_REQUIRED` as a
 * failure, produces an admin tool where ruling on a dispute fails for a reason
 * that has nothing to do with the dispute.
 *
 * The three server codes mean three different things and are treated differently:
 *
 * - `STEP_UP_2FA_REQUIRED` — the password was accepted and a code is now needed.
 *   **Not a failure.** It is the next step; it reveals the field and keeps the
 *   password. Rendering it as an error would make a correct password look
 *   refused.
 * - `STEP_UP_2FA_INVALID` — the code was wrong. Keep the password, clear the code.
 * - `STEP_UP_PASSWORD_INVALID` — the password was wrong. Clear it; the operator
 *   must retype it.
 *
 * Anything else is a real failure and is shown as-is.
 */

import { useCallback, useState } from "react"

import { apiErrorCode, apiErrorMessage } from "@workspace/api-client/client"

import type { StepUpCredentials, StepUpPromptProps } from "@/components/step-up-prompt"

export interface StepUpIntent {
  title: string
  description: React.ReactNode
  /** Stated before the credentials are asked for, not after. */
  consequence?: React.ReactNode
  confirmLabel?: string
  /** Performs the privileged call with the collected credentials. */
  run: (credentials: StepUpCredentials) => Promise<unknown>
}

interface StepUpState {
  intent: StepUpIntent | null
  requiresCode: boolean
  error: string | null
  errorCode: string | undefined
  pending: boolean
}

export function useStepUp() {
  const [state, setState] = useState<StepUpState>({
    intent: null,
    requiresCode: false,
    error: null,
    errorCode: undefined,
    pending: false,
  })

  const cancel = useCallback(() => {
    setState({
      intent: null,
      requiresCode: false,
      error: null,
      errorCode: undefined,
      pending: false,
    })
  }, [])

  /**
   * Open the prompt for an action.
   *
   * `requiresCode` starts `false` every time rather than carrying over, because
   * it is a fact about the *server's* answer to a previous attempt - and a new
   * action deserves a fresh assessment. Carrying it forward would mean an admin
   * with 2FA got asked for a code by every subsequent action forever.
   */
  const begin = useCallback((intent: StepUpIntent) => {
    setState({
      intent,
      requiresCode: false,
      error: null,
      errorCode: undefined,
      pending: false,
    })
  }, [])

  const submit = useCallback(async (credentials: StepUpCredentials) => {
    const intent = state.intent
    if (!intent || state.pending) return

    setState((s) => ({ ...s, pending: true, error: null, errorCode: undefined }))
    try {
      await intent.run(credentials)
      // Only reached when the privileged call actually succeeded, so the
      // credentials are discarded rather than left sitting in a dialog that
      // happens to still be mounted.
      setState({
        intent: null,
        requiresCode: false,
        error: null,
        errorCode: undefined,
        pending: false,
      })
    } catch (err) {
      const code = apiErrorCode(err)

      if (code === "STEP_UP_2FA_REQUIRED") {
        // The password was right. Reveal the next step, keep the password, and
        // leave `error` null so nothing red appears for a correct step.
        setState((s) => ({
          ...s,
          pending: false,
          requiresCode: true,
          error: null,
          errorCode: undefined,
        }))
        return
      }

      setState((s) => ({
        ...s,
        pending: false,
        error: apiErrorMessage(
          err,
          code === "STEP_UP_2FA_INVALID"
            ? "That code was not accepted. Check your authenticator and try again."
            : code === "STEP_UP_PASSWORD_INVALID"
              ? "That password was not accepted."
              : "The action could not be completed."
        ),
        errorCode: code,
      }))
    }
  }, [state.intent, state.pending])

  /**
   * Spread onto `<StepUpPrompt {...} />`.
   *
   * The prompt owns the credential inputs, so it also owns clearing them: it
   * needs to distinguish "the code was wrong, keep the password" from "the
   * password was wrong, clear it", and that decision belongs next to the inputs
   * rather than in a hook that cannot see them.
   */
  const promptProps: StepUpPromptProps = {
    open: state.intent !== null,
    onOpenChange: (open) => {
      if (!open) cancel()
    },
    title: state.intent?.title ?? "",
    description: state.intent?.description ?? "",
    consequence: state.intent?.consequence,
    confirmLabel: state.intent?.confirmLabel,
    error: state.error,
    errorCode: state.errorCode,
    requiresCode: state.requiresCode,
    pending: state.pending,
    onSubmit: (credentials) => {
      void submit(credentials)
    },
  }

  return { begin, cancel, promptProps, requiresCode: state.requiresCode }
}