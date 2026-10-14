"use client"

import { useCallback, useState } from "react"
import { useRouter } from "next/navigation"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { sileo } from "sileo"
import { Download, Loader2, TriangleAlert } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
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
import { Spinner } from "@workspace/ui/components/spinner"
import { SettingsBreadcrumb } from "@/components/settings/settings-breadcrumb"
import { apiErrorMessage, ApiError } from "@/lib/api/client"
import { accountApi, downloadAccountExport } from "@/lib/api/account"
import { queryKeys } from "@/lib/api/queryKeys"
import { useCurrentUser } from "@/hooks/use-auth"

/**
 * Two things in one page, and they belong together: the export and the erasure.
 *
 * Presenting "download my data" immediately above "delete my account" is the
 * point. Someone deciding whether to leave should not have to go looking for
 * what we hold - and the deletion dialog says plainly what survives, because
 * "we deleted your account" and "we deleted your data" are different claims and
 * only one of them is true.
 */

// ── Export ────────────────────────────────────────────────────────────────────

function ExportCard() {
  const [isDownloading, setIsDownloading] = useState(false)

  const onDownload = useCallback(async () => {
    setIsDownloading(true)
    try {
      await downloadAccountExport()
      sileo.success({ title: "Your export is downloading" })
    } catch (err) {
      sileo.error({ title: apiErrorMessage(err, "Could not build your export") })
    } finally {
      setIsDownloading(false)
    }
  }, [])

  return (
    <Card>
      <CardContent className="space-y-4 px-6 py-5">
        <div>
          <h2 className="text-sm font-medium">Download your data</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            A single JSON file with your profile, sessions, orders, positions,
            trades, transactions, wallet, comments and notifications.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={onDownload}
          disabled={isDownloading}
          aria-busy={isDownloading}
        >
          {isDownloading ? (
            <>
              <Loader2 className="size-3.5 animate-spin" />
              Building your export…
            </>
          ) : (
            <>
              <Download className="size-3.5" />
              Download my data
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  )
}

// ── Deletion ──────────────────────────────────────────────────────────────────

function DeleteCard() {
  const router = useRouter()
  const qc = useQueryClient()
  const { data: user } = useCurrentUser()
  const [password, setPassword] = useState("")
  const [code, setCode] = useState("")
  const [open, setOpen] = useState(false)

  // Whether 2FA is required is the server's answer, not a guess from a client
  // that may be looking at stale state - and the server decides it regardless.
  const { data: impact, isLoading } = useQuery({
    queryKey: queryKeys.deletionImpact(),
    queryFn: () => accountApi.deletionImpact().then((r) => r.data),
    // Never retry: a 401 here means signed out, and retrying a failing probe on
    // every render is what turns one dead session into a request storm.
    retry: false,
  })

  // The server decides this regardless — sending password-only against a 2FA
  // account is refused with STEP_UP_2FA_REQUIRED, not silently downgraded. This
  // only decides whether to *ask* for the code up front, so the user is not
  // handed a failure after typing their password.
  const needsCode = user?.is_2fa_enabled ?? false

  const deleteMutation = useMutation({
    mutationFn: () => accountApi.delete(password, code || undefined),
    onSuccess: () => {
      // Everything cached belongs to a person who no longer exists. Leaving it
      // in place would show the next person to sign in on this device a
      // stranger's balances and orders.
      qc.clear()
      setOpen(false)
      sileo.success({ title: "Your account has been deleted" })
      router.push("/")
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        // Outstanding orders or unsettled positions. The server has said what
        // they are; re-query so the card reflects the current state.
        qc.invalidateQueries({ queryKey: queryKeys.deletionImpact() })
      }
      sileo.error({ title: apiErrorMessage(err, "Could not delete your account") })
    },
  })

  const blocked = impact ? !impact.can_delete : false

  return (
    <Card className="border-destructive/30">
      <CardContent className="space-y-4 px-6 py-5">
        <div>
          <h2 className="text-sm font-medium text-destructive">Delete your account</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Removes your profile and signs you out everywhere. This cannot be
            undone.
          </p>
        </div>

        {isLoading ? (
          <div className="flex h-9 items-center" role="status">
            <Spinner className="size-4" />
            <span className="sr-only">Checking what would block deletion…</span>
          </div>
        ) : (
          <>
            {impact?.retained_even_after_deletion?.length ? (
              <p className="text-xs text-muted-foreground">
                Your trades, orders, positions, transactions, comments and
                referrals are kept — they are the market&apos;s shared history and
                our accounting record. They are simply no longer attached to you.
              </p>
            ) : null}

            {blocked && (
              <div
                role="alert"
                className="flex gap-2.5 rounded-md border border-amber-500/40 bg-amber-500/5 p-3"
              >
                <TriangleAlert className="mt-0.5 size-4 shrink-0 text-amber-600" />
                <p className="text-xs text-muted-foreground">
                  {impact?.blocked_detail?.message ??
                    "You have open orders or unsettled positions that must be resolved first."}
                </p>
              </div>
            )}

            <Button
              variant="outline"
              size="sm"
              disabled={blocked}
              onClick={() => setOpen(true)}
              className="text-destructive hover:bg-destructive/10 hover:text-destructive"
            >
              Delete my account
            </Button>
          </>
        )}
      </CardContent>

      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete your account?</AlertDialogTitle>
            <AlertDialogDescription>
              Your profile is erased and every session is signed out. This cannot
              be undone. Your trade and transaction history is kept, because it is
              the market&apos;s record as much as yours.
            </AlertDialogDescription>
          </AlertDialogHeader>

          <div className="space-y-3 py-2">
            <div className="space-y-1.5">
              <Label htmlFor="delete-password">Confirm your password</Label>
              <Input
                id="delete-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {needsCode && (
              <div className="space-y-1.5">
                <Label htmlFor="delete-code">Two-factor code</Label>
                <Input
                  id="delete-code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                />
              </div>
            )}
          </div>

          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteMutation.isPending}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={
                deleteMutation.isPending || password.length === 0 || needsCode && code.length !== 6
              }
              onClick={(e) => {
                // Keep the dialog open on failure so the reason is visible in
                // place; closing it would discard what the user just typed.
                e.preventDefault()
                deleteMutation.mutate()
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteMutation.isPending ? "Deleting…" : "Delete permanently"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function AccountPageClient() {
  return (
    <div className="container mx-auto max-w-3xl px-4 py-8 space-y-6">
      <SettingsBreadcrumb page="Your data" />

      <div>
        <h1 className="text-2xl font-bold tracking-tight">Your data</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Take a copy of everything we hold about you, or close your account.
        </p>
      </div>

      <ExportCard />
      <DeleteCard />
    </div>
  )
}