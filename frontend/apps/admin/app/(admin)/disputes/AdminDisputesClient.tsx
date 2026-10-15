"use client"

/**
 * The dispute queue, and the ruling.
 *
 * ## Why this page is mostly about the decision, not the form
 *
 * An upheld ruling resolves a market and queues settlement. It is the most
 * consequential privileged action in the product, and the one an admin session
 * is least entitled to perform unchallenged - hence step-up. But step-up alone
 * answers the wrong question: it proves *who* is acting, not *why*. So this page
 * puts the consequence, the evidence and the criterion in front of the operator,
 * and asks for a written reason on a dismissal.
 *
 * A dismissal closes someone's dispute with no payout. Silence is a legitimate
 * outcome for it; an *unrecorded* one is not, because the next question is
 * always "on what grounds", and the trail cannot answer that if the note was
 * optional in spirit even when optional in the schema.
 */

import { useState } from "react"
import Link from "next/link"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Gavel, Scale, ShieldCheck } from "lucide-react"
import { sileo } from "sileo"

import { adminApi } from "@workspace/api-client/admin"
import { queryKeys } from "@/lib/queryKeys"
import { Button, buttonVariants } from "@workspace/ui/components/button"
import { Badge } from "@workspace/ui/components/badge"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@workspace/ui/components/empty"
import { Skeleton } from "@workspace/ui/components/skeleton"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@workspace/ui/components/alert-dialog"
import { Textarea } from "@workspace/ui/components/textarea"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@workspace/ui/components/field"

import { validateRuling } from "@/schemas/privileged"

import { StepUpPrompt } from "@/components/step-up-prompt"
import { useStepUp } from "@/hooks/use-step-up"

const FILTERS = [
  { value: "open", label: "Awaiting a ruling" },
  { value: "upheld", label: "Upheld" },
  { value: "dismissed", label: "Dismissed" },
  { value: "all", label: "All" },
]

type Ruling = "upheld" | "dismissed"

interface PendingRuling {
  disputeId: string
  question: string
  ruling: Ruling
  note: string
}

function relative(iso: string) {
  const then = new Date(iso).getTime()
  const days = Math.floor((Date.now() - then) / 86_400_000)
  if (days <= 0) return "today"
  if (days === 1) return "1 day waiting"
  return `${days} days waiting`
}

export function AdminDisputesClient() {
  const qc = useQueryClient()
  const [status, setStatus] = useState("open")
  const [pending, setPending] = useState<PendingRuling | null>(null)
  const stepUp = useStepUp()

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.adminDisputes(status, 1),
    queryFn: () => adminApi.disputes({ status, page: 1 }).then((r) => r.data),
    retry: false,
  })

  const rows = data ?? []

  // Only meaningful while the confirmation dialog is open, and only for a
  // dismissal. An uphold resolves a market; a dismissal closes someone's dispute
  // with no payout and, without a stated reason, no explanation either.
  const noteProblem =
    pending?.ruling === "dismissed" ? validateRuling(pending.ruling, pending.note) : null
  const total = (data as { total?: number } | undefined)?.total ?? 0

  /**
   * The privileged call. Throwing on failure is deliberate: `useStepUp` needs the
   * rejection to classify the error, and a mutation that swallowed it would leave
   * the prompt showing "done" for an action the server refused.
   */
  const adjudicate = useMutation({
    mutationFn: async ({ disputeId, ruling, note, password, code }: PendingRuling & {
      password: string
      code?: string
    }) =>
      adminApi.adjudicate(disputeId, {
        ruling,
        ...(note.trim() ? { admin_note: note.trim() } : {}),
        password,
        ...(code ? { code } : {}),
      }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: queryKeys.adminRoot() })
      qc.invalidateQueries({ queryKey: queryKeys.treasury() })
      sileo.success({
        title: res.data?.ruling === "upheld" ? "Dispute upheld" : "Dispute dismissed",
        description:
          res.data?.ruling === "upheld"
            ? "The market is resolved and settlement is queued."
            : "The dispute is closed with no payout.",
      })
    },
  })

  const beginStepUp = (ruling: PendingRuling) => {
    setPending(null)
    stepUp.begin({
      title: ruling.ruling === "upheld" ? "Uphold this dispute" : "Dismiss this dispute",
      description: ruling.question,
      consequence:
        ruling.ruling === "upheld" ? (
          <>
            This resolves the market to the proposed outcome and <strong>queues settlement</strong>.
            It cannot be undone from here.
          </>
        ) : (
          <>
            This closes the dispute with <strong>no payout</strong>. The proposer is not told why
            unless your note says.
          </>
        ),
      confirmLabel: ruling.ruling === "upheld" ? "Rule upheld" : "Dismiss dispute",
      run: async (creds) => {
        await adjudicate.mutateAsync({ ...ruling, ...creds })
      },
    })
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Disputes</h1>
          <p className="text-sm text-muted-foreground">
            Oldest first. An upheld ruling resolves the market and pays out.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter disputes">
          {FILTERS.map((f) => (
            <Button
              key={f.value}
              size="sm"
              variant={status === f.value ? "secondary" : "ghost"}
              aria-pressed={status === f.value}
              onClick={() => setStatus(f.value)}
            >
              {f.label}
            </Button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-2" role="status" aria-label="Loading disputes">
          <span className="sr-only">Loading disputes…</span>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : isError ? (
        // An empty queue and a broken query look identical on screen. For a
        // moderation queue that is the worst possible confusion - "nothing is
        // waiting" is a statement about the product, and it must never be the
        // rendering of a failed request.
        <Card>
          <CardContent className="flex flex-col items-center gap-3 px-5 py-8 text-center">
            <p className="text-sm font-medium">The dispute queue could not be loaded</p>
            <p className="max-w-md text-xs text-muted-foreground">
              This is a failed request, not an empty queue.
            </p>
            <Button size="sm" variant="outline" onClick={() => refetch()}>
              Try again
            </Button>
          </CardContent>
        </Card>
      ) : rows.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <Scale className="size-6 text-muted-foreground" />
            <EmptyTitle>
              {status === "open" ? "Nothing is waiting" : "No disputes here"}
            </EmptyTitle>
            <EmptyDescription>
              {status === "open"
                ? "No open disputes. Anything raised appears here oldest-first."
                : `No disputes with the status “${status}”.`}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <ul className="space-y-3">
          {rows.map((row) => (
            <li key={row.id}>
              <Card>
                <CardContent className="space-y-3 px-5 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                      <Link
                        href={`/markets?market=${row.market_id}`}
                        className={cnLink(buttonVariants({ variant: "link" }))}
                      >
                        {row.market_question}
                      </Link>
                      <p className="text-xs text-muted-foreground">
                        Raised by {row.proposer_username ?? "a user"} ·{" "}
                        {relative(row.created_at)}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <Badge variant={row.status === "open" ? "secondary" : "outline"}>
                        {row.status}
                      </Badge>
                      {row.status === "open" ? (
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              setPending({ disputeId: row.id, question: row.market_question, ruling: "dismissed", note: "" })
                            }
                          >
                            Dismiss
                          </Button>
                          <Button
                            size="sm"
                            onClick={() =>
                              setPending({ disputeId: row.id, question: row.market_question, ruling: "upheld", note: "" })
                            }
                          >
                            <Gavel className="size-3.5" aria-hidden />
                            Uphold
                          </Button>
                        </>
                      ) : null}
                    </div>
                  </div>

                  {row.evidence ? (
                    <div className="rounded-md bg-muted/40 px-3 py-2">
                      <p className="text-xs font-medium text-muted-foreground">Evidence given</p>
                      <p className="mt-1 text-sm">{row.evidence}</p>
                      {row.evidence_url ? (
                        <a
                          href={row.evidence_url}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="mt-1 inline-block break-all text-xs text-primary hover:underline"
                        >
                          {row.evidence_url}
                        </a>
                      ) : null}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      No evidence was given with this dispute.
                    </p>
                  )}
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}

      {total > rows.length ? (
        <p className="text-xs text-muted-foreground">
          Showing {rows.length} of {total}.
        </p>
      ) : null}

      {/* Step 1 of two: what are you about to do, and why. */}
      <AlertDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) setPending(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pending?.ruling === "upheld" ? "Uphold this dispute?" : "Dismiss this dispute?"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pending?.ruling === "upheld"
                ? "The market resolves to the proposed outcome and settlement is queued."
                : "The dispute closes with no payout."}
            </AlertDialogDescription>
          </AlertDialogHeader>

          {pending?.ruling === "dismissed" ? (
            <Field data-invalid={noteProblem ? true : undefined}>
              <FieldLabel htmlFor="ruling-note">Reason</FieldLabel>
              <Textarea
                id="ruling-note"
                rows={3}
                aria-invalid={noteProblem ? true : undefined}
                value={pending.note}
                placeholder="Why is the proposed outcome not supported by the evidence?"
                onChange={(event) =>
                  setPending({ ...pending, note: event.target.value })
                }
              />
              {/* The rule lives with the ruling, not here - see `validateRuling`.
                  A dismissal is the only ruling that pays nobody, so it is the
                  only one where "no reason" leaves someone unable to find out
                  what happened to their money. */}
              {noteProblem ? (
                <FieldError role="alert">{noteProblem}</FieldError>
              ) : (
                <FieldDescription>
                  Stored with the ruling. A dismissal with no stated grounds is one
                  nobody can explain afterwards.
                </FieldDescription>
              )}
            </Field>
          ) : (
            <p className="flex items-start gap-2 text-xs text-muted-foreground">
              <ShieldCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {pending?.question}
            </p>
          )}

          <AlertDialogFooter>
            <AlertDialogCancel>Back</AlertDialogCancel>
            <AlertDialogAction
              // Disabled rather than validated on submit, so the operator is told
              // why, next to the field they need to fill in.
              disabled={noteProblem !== null}
              onClick={() => pending && beginStepUp(pending)}
            >
              Continue
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Step 2 of two: prove you are the operator, right now. */}
      <StepUpPrompt {...stepUp.promptProps} />
    </div>
  )
}

/** Local so the admin bundle does not pull in `cn` for a single call site. */
function cnLink(base: string) {
  return `${base} h-auto justify-start whitespace-normal p-0 text-left text-sm font-medium`
}