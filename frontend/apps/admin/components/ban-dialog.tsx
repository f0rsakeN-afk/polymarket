"use client"

/**
 * Banning a user, and asking why.
 *
 * ## Why the reason is a field and not an optional note
 *
 * A ban cancels resting orders, releases reserved funds and revokes every
 * session. It is irreversible from the user's side and, before this existed,
 * completely unexplained: the user was told "Account is inactive" and the next
 * admin could not tell a justified ban from a mistake either.
 *
 * So the reason is required, and it is **shown to the user**. That second part is
 * the design decision worth defending — a reason the operator records and nobody
 * reads is an internal note, and an internal note is one nobody will bother
 * writing carefully.
 *
 * ## What the dialog states before it asks
 *
 * The consequence list is the part that stops a ban being a reflex. An operator
 * who knows this cancels orders and cuts off access may still ban immediately
 * during a fraud — that is the point — but they will not do it *surprised*.
 */

import { useId, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Ban, TriangleAlert } from "lucide-react"
import { sileo } from "sileo"

import { adminApi } from "@workspace/api-client/admin"
import { apiErrorMessage } from "@workspace/api-client/client"
import { queryKeys } from "@/lib/queryKeys"
import { banReasonSchema } from "@/schemas/privileged"
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
  user: { id: string; email: string; username: string } | null
  onOpenChange: (open: boolean) => void
}

/**
 * `key` this at the call site with the user's id — see {@link BanUserDialog}.
 * Changing the key remounts the component, which is what gives a fresh form:
 * resetting state in an effect instead would render the previous reason's value
 * for one frame, and a leftover reason one click from the wrong account is
 * exactly the failure this dialog has to not have.
 */
export function BanUserDialog({ user, onOpenChange }: Props) {
  const qc = useQueryClient()
  const reasonId = useId()
  const noteId = useId()

  const [reason, setReason] = useState("")
  const [note, setNote] = useState("")
  const [touched, setTouched] = useState(false)
  // `reason`/`note`/`touched` start empty and are only ever reset by remounting.

  const reasonError = touched ? banReasonSchema.safeParse(reason) : null

  const ban = useMutation({
    mutationFn: () =>
      adminApi.ban(user!.id, {
        reason: reason.trim(),
        ...(note.trim() ? { note: note.trim() } : {}),
      }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: queryKeys.adminRoot() })
      const released = res.data?.cancelled_order_ids?.length ?? 0
      sileo.success({
        title: `${user?.email} banned`,
        description: released
          ? `${released} resting order${released === 1 ? "" : "s"} cancelled and the funds released.`
          : "No resting orders to release.",
      })
      onOpenChange(false)
    },
    onError: (err) => {
      sileo.error({ title: "Ban failed", description: apiErrorMessage(err, "Try again.") })
    },
  })

  const canSubmit = banReasonSchema.safeParse(reason).success && !ban.isPending

  return (
    <Dialog
      open={Boolean(user)}
      onOpenChange={(open) => {
        if (!open) onOpenChange(false)
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Ban {user?.email}</DialogTitle>
          <DialogDescription>
            This deactivates the account immediately. It is reversible — but the
            reason below is shown to them, and they cannot appeal what they are
            not told.
          </DialogDescription>
        </DialogHeader>

        {/* Stated before it is asked for, not after. An operator who knows the
            consequence can still ban on the spot during a fraud; one who is
            surprised might not do it at all, which is how a wrong ban happens. */}
        <ul className="space-y-1.5 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-xs text-muted-foreground">
          <li className="flex gap-2">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-destructive" aria-hidden />
            Every resting order is cancelled and the reserved USDC released.
          </li>
          <li className="flex gap-2">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-destructive" aria-hidden />
            Every session and refresh token is revoked — they are signed out now.
          </li>
          <li className="flex gap-2">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-destructive" aria-hidden />
            The balance is untouched and returns on unban. Nothing is confiscated.
          </li>
        </ul>

        <form
          onSubmit={(event) => {
            event.preventDefault()
            setTouched(true)
            if (!canSubmit) return
            ban.mutate()
          }}
        >
          <div className="space-y-4">
            <Field
              data-invalid={reasonError && !reasonError.success ? true : undefined}
            >
              <FieldLabel htmlFor={reasonId}>Why are you banning them?</FieldLabel>
              <Input
                id={reasonId}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                onBlur={() => setTouched(true)}
                placeholder="e.g. three failed chargebacks on cards from the same device"
                aria-invalid={reasonError && !reasonError.success ? true : undefined}
                aria-describedby={reasonError && !reasonError.success ? `${reasonId}-error` : undefined}
                disabled={ban.isPending}
                maxLength={500}
              />
              {reasonError && !reasonError.success ? (
                <FieldError id={`${reasonId}-error`} role="alert">
                  {reasonError.error.issues[0]?.message}
                </FieldError>
              ) : (
                <FieldDescription>
                  Required. The user sees this at their next sign-in.
                </FieldDescription>
              )}
              {/* The counter appears only once it matters. A permanent "12/500"
                  on an empty field is noise that trains people to ignore numbers. */}
              {reason.length > 400 ? (
                <FieldDescription className="tabular-nums">
                  {reason.length}/500
                </FieldDescription>
              ) : null}
            </Field>

            <Field>
              <FieldLabel htmlFor={noteId}>Note (optional)</FieldLabel>
              <Textarea
                id={noteId}
                rows={3}
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder="Evidence, references, or what to do if they appeal."
                disabled={ban.isPending}
                maxLength={2000}
              />
              <FieldDescription>
                Longer context, kept in the audit trail. The reason above is the
                one the user sees.
              </FieldDescription>
            </Field>
          </div>

          <DialogFooter className="mt-5">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={ban.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" variant="destructive" disabled={!canSubmit}>
              <Ban className="size-3.5" aria-hidden />
              {ban.isPending ? "Banning…" : "Ban account"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Lifting a ban.
 *
 * The note is optional here, unlike the ban reason: reversing a decision is a
 * restorative action, and the audit already shows the reversal by the unban
 * itself. Asking for a reason to *undo* something would be asking twice.
 */
export function UnbanUserDialog({
  user,
  onOpenChange,
}: {
  user: { id: string; email: string; banReason: string | null } | null
  onOpenChange: (open: boolean) => void
}) {
  const qc = useQueryClient()
  const noteId = useId()
  const [note, setNote] = useState("")
  // Fresh on each open, for the same reason as the ban dialog: a note left over
  // from a previous reversal reads as though it were about this account.
  const unban = useMutation({
    mutationFn: () => adminApi.unban(user!.id, note.trim() ? { note: note.trim() } : undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.adminRoot() })
      sileo.success({ title: `${user?.email} unbanned`, description: "The account can sign in again." })
      onOpenChange(false)
    },
    onError: (err) => {
      sileo.error({ title: "Unban failed", description: apiErrorMessage(err, "Try again.") })
    },
  })

  return (
    <Dialog
      open={Boolean(user)}
      onOpenChange={(open) => {
        if (!open) onOpenChange(false)
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Unban {user?.email}?</DialogTitle>
          <DialogDescription>
            They can sign in again immediately, and the balance — which a ban
            never touched — is exactly as it was.
          </DialogDescription>
        </DialogHeader>

        {/* The reason being lifted is part of the decision. An admin reversing a
            ban without knowing what it was for is approving something they have
            not read. */}
        {user?.banReason ? (
          <div className="rounded-md border px-3 py-2 text-xs">
            <p className="font-medium">Banned for</p>
            <p className="mt-0.5 text-muted-foreground">{user.banReason}</p>
          </div>
        ) : null}

        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (unban.isPending) return
            unban.mutate()
          }}
        >
          <Field>
            <FieldLabel htmlFor={noteId}>Why is this being reversed?</FieldLabel>
            <Textarea
              id={noteId}
              rows={2}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Appeal upheld, identity confirmed."
              disabled={unban.isPending}
              maxLength={2000}
            />
            <FieldDescription>
              Optional. Recorded in the audit trail alongside the reason being
              lifted.
            </FieldDescription>
          </Field>

          <DialogFooter className="mt-5">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={unban.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={unban.isPending}>
              {unban.isPending ? "Lifting…" : "Unban account"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}