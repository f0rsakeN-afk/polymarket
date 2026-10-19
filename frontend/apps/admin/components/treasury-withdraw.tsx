"use client"

/**
 * Withdrawing a chosen amount to the treasury.
 *
 * ## Why this exists separately from the fee sweep
 *
 * `distribute-protocol-fees` moves whatever the accumulated fee balance happens to
 * be — the amount is derived, and the operator has just seen it. This one moves
 * a *stated* number, chosen by the operator. Different operation, different risk,
 * and it is the one that deserves to feel deliberate rather than routine.
 *
 * The endpoint has had step-up and an audit row since it was hardened. What it
 * did not have was any way to reach it — so a capability existed with no surface.
 *
 * ## The arithmetic is decimal, never floating point
 *
 * The amount is parsed and validated as a string and only converted at the moment
 * it crosses the wire. `parseFloat("0.3") - parseFloat("0.1")` is
 * `0.19999999999999998`, and a number an operator cannot read is a number they
 * should not be asked to approve. This screen moves money; the value they approve
 * has to be the value that moves.
 *
 * ## Balance checks are done here, and still done on the server
 *
 * The client check exists to avoid a pointless round trip and to explain *why*
 * something cannot be done. The server check is the real one — a balance can move
 * between the page rendering and the click, and a client-side guard is a
 * convenience, never an authority.
 */

import { useCallback, useMemo, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { BanknoteArrowDown, TriangleAlert } from "lucide-react"
import { sileo } from "sileo"

import { adminApi } from "@workspace/api-client/admin"
import { apiErrorMessage } from "@workspace/api-client/client"
import { queryKeys } from "@/lib/queryKeys"
import { group, subtract } from "@/lib/decimal"
import { useStepUp } from "@/hooks/use-step-up"
import { Button } from "@workspace/ui/components/button"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Input } from "@workspace/ui/components/input"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@workspace/ui/components/field"
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

/** Mirrors the API's `gt=0, le=100_000_000`. */
const MAX_WITHDRAWAL = "100000000";

/** Eight decimal places, which is the column's scale. Anything finer is noise. */
const AMOUNT_PATTERN = /^\d{1,12}(\.\d{1,8})?$/;

function validateAmount(raw: string): string | null {
  const value = raw.trim();
  if (!value) return "Enter an amount to withdraw.";
  if (!AMOUNT_PATTERN.test(value)) {
    // Rejecting the shape rather than parsing it is deliberate: `parseFloat`
    // accepts "1e5", "0x10" and " 12 ", none of which are amounts anyone means.
    return "Enter a plain number, like 250 or 250.50 — up to 8 decimal places.";
  }
  if (Number(value) <= 0) return "The amount must be more than zero.";
  if (Number(value) > Number(MAX_WITHDRAWAL)) {
    return `The maximum single withdrawal is ${group(MAX_WITHDRAWAL)} USDC.`;
  }
  return null;
}

export function TreasuryWithdraw({ balance }: { balance: string }) {
  const qc = useQueryClient()
  const stepUp = useStepUp()

  const [amount, setAmount] = useState("")
  const [touched, setTouched] = useState(false)
  const [confirming, setConfirming] = useState(false)

  const problem = useMemo(() => validateAmount(amount), [amount])
  const showProblem = touched && problem;

  /** Only meaningful once the amount itself parses. */
  const exceedsBalance = useMemo(() => {
    if (problem) return false;
    try {
      return subtract(balance, amount.trim()).startsWith("-");
    } catch {
      return false;
    }
  }, [amount, balance, problem]);

  const withdraw = useMutation({
    mutationFn: (credentials: { password: string; code?: string }) =>
      adminApi.treasuryDistribute({
        amount: Number(amount.trim()),
        password: credentials.password,
        ...(credentials.code ? { code: credentials.code } : {}),
      }),
    onSuccess: () => {
      // Both lists, because the balance moved and the history now has a row the
      // operator is looking at. Leaving the history stale shows a withdrawal
      // they just made as not having happened.
      qc.invalidateQueries({ queryKey: ["admin", "treasury"] });
      qc.invalidateQueries({ queryKey: queryKeys.treasuryLogs(1) });
      sileo.success({
        title: "Withdrawal complete",
        description: `${amount.trim()} USDC moved to the treasury.`,
      });
      setAmount("");
      setTouched(false);
    },
    onError: (err) => {
      sileo.error({
        title: "Withdrawal failed",
        description: apiErrorMessage(err, "Try again."),
      });
    },
  });

  const onConfirm = useCallback(() => {
    setConfirming(false);
    stepUp.begin({
      title: "Withdraw to the treasury",
      description: "Prove you are the operator before money moves.",
      // The number, exact and grouped, twice: once in the consequence and once in
      // the confirm label. This is the last screen where the operator can stop.
      consequence: (
        <>
          <strong>{group(amount.trim())} USDC</strong> will move out of the protocol
          fee balance and into the treasury wallet. This cannot be undone from here.
        </>
      ),
      confirmLabel: `Withdraw ${group(amount.trim())} USDC`,
      run: async (credentials) => {
        await withdraw.mutateAsync(credentials);
      },
    });
  }, [amount, stepUp, withdraw]);

  const canWithdraw = !problem && !exceedsBalance;

  return (
    <Card>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <BanknoteArrowDown className="size-4 text-muted-foreground" aria-hidden />
            Withdraw a specific amount
          </h2>
          <p className="text-xs text-muted-foreground">
            Move an exact amount from the protocol fee balance to the treasury.
            Distinct from sweeping everything that has accrued.
          </p>
        </div>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            setTouched(true);
            if (!canWithdraw) return;
            setConfirming(true);
          }}
          className="space-y-3"
        >
          <Field data-invalid={showProblem || exceedsBalance ? true : undefined}>
            <FieldLabel htmlFor="withdraw-amount">Amount (USDC)</FieldLabel>
            <div className="flex gap-2">
              <Input
                id="withdraw-amount"
                inputMode="decimal"
                autoComplete="off"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                onBlur={() => setTouched(true)}
                placeholder="250.00"
                aria-invalid={showProblem || exceedsBalance ? true : undefined}
                aria-describedby="withdraw-amount-hint"
                className="font-mono"
              />
              {/* Not disabled when the amount will not do. A disabled button
                  gives no reason and, being the only control that could set
                  "touched", silently swallows the click that would explain
                  itself. The form validates on submit and says what is wrong. */}
              <Button type="submit">Withdraw</Button>
            </div>

            {showProblem ? (
              <FieldError id="withdraw-amount-error" role="alert">
                {problem}
              </FieldError>
            ) : exceedsBalance ? (
              /* Explained rather than merely refused: the operator can see the
                 balance, and telling them which of the two numbers is wrong
                 saves guessing. */
              <FieldError id="withdraw-amount-error" role="alert">
                That is more than the {group(balance)} USDC available.
              </FieldError>
            ) : (
              <FieldDescription id="withdraw-amount-hint">
                Available: {group(balance)} USDC. Up to eight decimal places.
              </FieldDescription>
            )}
          </Field>
        </form>

        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
          This is one of two treasury actions. Both record who did it in the audit
          trail, and both require your password again at the point of moving money.
        </p>

        <AlertDialog open={confirming} onOpenChange={setConfirming}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>
                Withdraw {group(amount.trim())} USDC to the treasury?
              </AlertDialogTitle>
              <AlertDialogDescription>
                This is a chosen amount, not a computed one. It moves out of the
                protocol fee balance and cannot be reversed from this screen.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction onClick={onConfirm}>Continue</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </CardContent>
    </Card>
  );
}