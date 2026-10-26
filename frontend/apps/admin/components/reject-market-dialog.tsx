"use client"

/**
 * Declining a market submission, and asking why.
 *
 * ## Why this reason is required, and why it is shown to the author
 *
 * A rejected market is invisible to the catalogue but still readable by the
 * person who wrote it. So the reason recorded here is the only channel through
 * which the author learns anything — and a submission declined with no
 * explanation is a submission that cannot be fixed, because nobody can tell
 * whether the problem was the wording, the category, or the resolution criteria.
 *
 * Before this existed the client filled the field in itself with
 * `"Declined by a moderator"`. That is worse than an empty reason: it looks like
 * a reason, so nobody notices it is not one, and the author is left with a
 * sentence that answers none of the questions they actually have.
 *
 * ## Approval deliberately does not get a dialog
 *
 * Approving is a routine, visible act — the market is published, the author sees
 * it go live, and the state change is self-explanatory. Demanding a written
 * justification for it trains operators to type whatever the field wants rather
 * than thinking about what is true. Only the irreversible, unexplained-from-the-
 * outside decisions ask for a reason.
 */

import { useId, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { XCircle } from "lucide-react"
import { sileo } from "sileo"

import { adminApi } from "@workspace/api-client/admin"
import { apiErrorMessage } from "@workspace/api-client/client"
import { queryKeys } from "@/lib/queryKeys"
import { rejectionReasonSchema } from "@/schemas/privileged"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Textarea } from "@workspace/ui/components/textarea"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@workspace/ui/components/field"

interface Props {
  market: { id: string; slug: string; question: string } | null
  onOpenChange: (open: boolean) => void
}

/**
 * `key` this at the call site with the market id. Changing the key remounts the
 * component, which is what gives a fresh form: resetting state in an effect
 * would instead render the previous market's reason for a frame, and a stale
 * reason one click from the wrong submission is precisely the mistake this
 * dialog exists to prevent.
 */
export function RejectMarketDialog({ market, onOpenChange }: Props) {
  const qc = useQueryClient()
  const reasonId = useId()
  const noteId = useId()

  const [reason, setReason] = useState("")
  const [note, setNote] = useState("")
  const [touched, setTouched] = useState(false)

  const reasonError = touched ? rejectionReasonSchema.safeParse(reason) : null
  const canSubmit = rejectionReasonSchema.safeParse(reason).success

  const reject = useMutation({
    mutationFn: () =>
      adminApi.rejectMarket(market!.id, {
        reason: reason.trim(),
        ...(note.trim() ? { note: note.trim() } : {}),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.adminRoot() })
      sileo.success({
        title: "Submission declined",
        description: "The author can read your reason on their market.",
      })
      onOpenChange(false)
    },
    onError: (err) => {
      sileo.error({
        title: "Could not decline",
        description: apiErrorMessage(err, "Try again."),
      })
    },
  })

  return (
    <Dialog
      open={Boolean(market)}
      onOpenChange={(open) => {
        if (!open) onOpenChange(false)
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Decline this submission?</DialogTitle>
          <DialogDescription>
            {market?.question}
          </DialogDescription>
        </DialogHeader>

        {/* Stated before it is asked for. An operator who knows the market stays
            with its author but off the catalogue can still decline on the spot;
            one who is surprised might decline something they had approved. */}
        <ul className="space-y-1.5 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-xs text-muted-foreground">
          <li className="flex gap-2">
            <XCircle className="mt-0.5 size-3.5 shrink-0 text-destructive" aria-hidden />
            It is removed from the public catalogue immediately.
          </li>
          <li className="flex gap-2">
            <XCircle className="mt-0.5 size-3.5 shrink-0 text-destructive" aria-hidden />
            The author keeps read access, and the reason below is all they are
            told — so write it for someone who has to act on it.
          </li>
        </ul>

        <form
          onSubmit={(event) => {
            event.preventDefault()
            setTouched(true)
            if (!canSubmit || reject.isPending) return
            reject.mutate()
          }}
        >
          <div className="space-y-4">
            <Field
              data-invalid={reasonError && !reasonError.success ? true : undefined}
            >
              <FieldLabel htmlFor={reasonId}>
                Why is this submission being declined?
              </FieldLabel>
              <Input
                id={reasonId}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                onBlur={() => setTouched(true)}
                placeholder="e.g. the resolution criteria name no date or source, so it can never settle"
                aria-invalid={reasonError && !reasonError.success ? true : undefined}
                aria-describedby={
                  reasonError && !reasonError.success ? `${reasonId}-error` : undefined
                }
                disabled={reject.isPending}
                maxLength={1000}
              />
              {reasonError && !reasonError.success ? (
                <FieldError id={`${reasonId}-error`} role="alert">
                  {reasonError.error.issues[0]?.message}
                </FieldError>
              ) : (
                <FieldDescription>
                  Required, and shown to the author. Be specific about what to
                  change &mdash; the word <em>declined</em> on its own tells them
                  nothing.
                </FieldDescription>
              )}
              {reason.length > 800 ? (
                <FieldDescription className="tabular-nums">
                  {reason.length}/1000
                </FieldDescription>
              ) : null}
            </Field>

            <Field>
              <FieldLabel htmlFor={noteId}>Note (optional)</FieldLabel>
              <Textarea
                id={noteId}
                rows={2}
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder="Internal context, references, who to ask."
                disabled={reject.isPending}
                maxLength={2000}
              />
              <FieldDescription>
                Kept in the audit trail. The author sees the reason above, not
                this.
              </FieldDescription>
            </Field>
          </div>

          <DialogFooter className="mt-5">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={reject.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="destructive"
              disabled={!canSubmit || reject.isPending}
            >
              <XCircle className="size-3.5" aria-hidden />
              {reject.isPending ? "Declining…" : "Decline submission"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}