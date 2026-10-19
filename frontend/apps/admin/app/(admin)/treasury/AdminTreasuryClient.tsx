"use client"

/**
 * Treasury: what has been collected, what has been moved, and what is waiting.
 *
 * ## Why the button states the amount first
 *
 * Before this page existed the only way to find out what you were about to move
 * was to perform the move. That is backwards for the one endpoint in the product
 * that takes money out of every market at once, and it means the operator
 * approves an action whose size they have not seen.
 *
 * So the pending figure is computed and shown, and the confirmation names the
 * amount. The arithmetic is exact decimal string maths (`lib/decimal.ts`), not
 * floating point: the number on this screen is the number that will move, and
 * `0.3 - 0.1 = 0.19999999999999998` is not a number anyone can approve.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Coins, Landmark, TrendingUp } from "lucide-react"
import { sileo } from "sileo"

import { adminApi } from "@workspace/api-client/admin"
import { queryKeys } from "@/lib/queryKeys"
import { TreasuryHistory } from "@/components/treasury-history"
import { group, subtract } from "@/lib/decimal"
import { Button } from "@workspace/ui/components/button"
import { Badge } from "@workspace/ui/components/badge"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Spinner } from "@workspace/ui/components/spinner"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@workspace/ui/components/alert-dialog"

import { StepUpPrompt } from "@/components/step-up-prompt"
import { useStepUp } from "@/hooks/use-step-up"

function Figure({
  label,
  value,
  hint,
  emphasis,
}: {
  label: string
  value: string | undefined
  hint: string
  emphasis?: boolean
}) {
  return (
    <Card className={emphasis ? "border-amber-500/40" : undefined}>
      <CardContent className="px-5 py-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        {value === undefined ? (
          <div className="mt-2 flex h-8 items-center" role="status">
            <Spinner className="size-4" />
            <span className="sr-only">Loading {label}</span>
          </div>
        ) : (
          <p
            className={`mt-1 text-2xl font-bold tabular-nums ${
              emphasis && !value.startsWith("0") && !value.startsWith("-0")
                ? "text-amber-600"
                : ""
            }`}
          >
            {group(value)} <span className="text-sm font-normal text-muted-foreground">USDC</span>
          </p>
        )}
        <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  )
}

export function AdminTreasuryClient() {
  const qc = useQueryClient()

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.treasury(),
    queryFn: () => adminApi.treasury().then((r) => r.data),
    retry: false,
  })

  const distributed = useMutation({
    mutationFn: (credentials: { password: string; code?: string }) =>
      adminApi.distributeProtocolFees(credentials),
    onSuccess: (res) => {
      // Deliberately narrow. The markets list is not affected by a balance
      // change, and invalidating the whole admin root to refresh one figure
      // refetches every operator list for no reason.
      qc.invalidateQueries({ queryKey: queryKeys.treasury() })
      sileo.success({
        title: "Protocol fees distributed",
        description: `${group(String(res.data?.total_distributed ?? "0"))} USDC moved from ${
          res.data?.markets_processed ?? 0
        } markets.`,
      })
    },
  })

  const stepUp = useStepUp()

  /**
   * Collected minus distributed, exactly.
   *
   * Shown even when it is zero, and shown as a discrepancy when it is negative -
   * a distribution recorded without its counterpart landing is a real state to
   * notice, not something to round away.
   */
  const pending =
    data == null ? undefined : subtract(data.total_fees_collected, data.total_fees_distributed)
  const nothingToMove = pending !== undefined && Number(pending) === 0

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Treasury</h1>
        <p className="text-sm text-muted-foreground">
          Protocol fees accumulated in markets, and the balance they have moved to.
        </p>
      </div>

      {isError ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 px-5 py-8 text-center">
            <p className="text-sm font-medium">The treasury balance could not be loaded</p>
            <Button size="sm" variant="outline" onClick={() => refetch()}>
              Try again
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Figure
              label="Waiting to be distributed"
              value={pending}
              hint="Collected, not yet moved to the treasury"
              emphasis
            />
            <Figure
              label="Treasury balance"
              value={data?.balance}
              hint="Settled and held by the treasury wallet"
            />
            <Figure
              label="Total collected"
              value={data?.total_fees_collected}
              hint="All protocol fees ever taken from trades"
            />
          </div>

          <Card>
            <CardContent className="flex flex-wrap items-center justify-between gap-4 px-5 py-4">
              <div className="space-y-1">
                <p className="flex items-center gap-1.5 text-sm font-medium">
                  <Landmark className="size-3.5" aria-hidden />
                  Move protocol fees to the treasury
                </p>
                <p className="text-xs text-muted-foreground">
                  Withdraws the waiting balance from every market that holds it. Recorded against
                  your account.
                </p>
              </div>

              {nothingToMove ? (
                <Badge variant="outline">Nothing to distribute</Badge>
              ) : (
                <AlertDialog>
                  <AlertDialogTrigger
                    render={
                      <Button size="sm" disabled={isLoading || pending === undefined} />
                    }
                  >
                    <Coins className="size-3.5" aria-hidden />
                    Distribute fees
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>
                        Move {pending !== undefined ? group(pending) : "0"} USDC to the treasury?
                      </AlertDialogTitle>
                      <AlertDialogDescription>
                        This withdraws the accumulated protocol fees from every market that holds
                        them. Markets keep trading; the fee balance moves.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() =>
                          stepUp.begin({
                            title: "Distribute protocol fees",
                            description: "Prove you are the operator before money moves.",
                            consequence: (
                              <>
                                <strong>{pending !== undefined ? group(pending) : "0"} USDC</strong>{" "}
                                will be withdrawn from markets and moved to the treasury wallet.
                              </>
                            ),
                            confirmLabel: "Distribute fees",
                            run: async (credentials) => {
                              await distributed.mutateAsync(credentials)
                            },
                          })
                        }
                      >
                        Continue
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              )}
            </CardContent>
          </Card>

          <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
            <TrendingUp className="mt-0.5 size-3 shrink-0" aria-hidden />
            Distributions are recorded in the audit trail with the amount moved and the number of
            markets processed.
          </p>
        </>
      )}

      <TreasuryHistory />

      <StepUpPrompt {...stepUp.promptProps} />
    </div>
  )
}