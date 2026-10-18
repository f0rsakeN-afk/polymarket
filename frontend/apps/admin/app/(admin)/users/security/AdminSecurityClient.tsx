"use client"

/**
 * The operator's own session and two-factor state.
 *
 * ## Why this page exists in the admin app at all
 *
 * The storefront already has sessions and 2FA. So why here?
 *
 * Because step-up makes the factor load-bearing for the most dangerous actions in
 * the product, and the person who needs to turn it on *cannot currently do it
 * from the tool that requires it*. An operator whose only 2FA enrolment lives on
 * the storefront has to switch applications to manage the thing that gates the
 * admin tool — which is exactly the friction that leaves it off.
 *
 * And "which other sessions does this account have" is the first question a
 * security-conscious operator asks when they suspect something. Answering it in a
 * different app means a context switch to get an answer about *this* app.
 *
 * ## What this page deliberately does not do
 *
 * It does not enrol a new factor. That is a QR-code flow with a provisioning
 * secret, a confirmation code, and a genuine risk of stranding an operator
 * half-enrolled mid-shift with step-up suddenly demanding a code they have not
 * finished setting up. Linking to the storefront's flow, where it is already built
 * and tested, is the honest answer — a half-built enrolment here would be worse
 * than a link.
 */

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { KeyRound, Laptop, MapPin, ShieldCheck, ShieldOff, Trash2 } from "lucide-react"
import { sileo } from "sileo"

import { adminApi, type AdminSession } from "@workspace/api-client/admin"
import { apiErrorMessage } from "@workspace/api-client/client"
import { queryKeys } from "@/lib/queryKeys"
import { Button, buttonVariants } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"
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
} from "@workspace/ui/components/alert-dialog"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import { Skeleton } from "@workspace/ui/components/skeleton"

import { PageHeader } from "@/components/page-header"

/**
 * A user-agent string, reduced to something an operator can recognise.
 *
 * Shown in full it is an unreadable wall; shown reduced to a browser and a
 * platform it answers "is that mine?" at a glance. `unknown` rather than an empty
 * cell, because a blank reads as "loading" forever.
 */
function describeAgent(userAgent: string | null): string {
  if (!userAgent) return "Unknown device"

  const ua = userAgent.toLowerCase()
  const browser = ua.includes("edg/")
    ? "Edge"
    : ua.includes("chrome/")
      ? "Chrome"
      : ua.includes("firefox/")
        ? "Firefox"
        : ua.includes("safari/")
          ? "Safari"
          : "Browser"

  const platform = ua.includes("android")
    ? "Android"
    : ua.includes("iphone") || ua.includes("ipad")
      ? "iOS"
      : ua.includes("windows")
        ? "Windows"
        : ua.includes("mac os")
          ? "macOS"
          : ua.includes("linux")
            ? "Linux"
            : "Unknown platform"

  return `${browser} on ${platform}`
}

function relative(iso: string) {
  const then = new Date(iso).getTime()
  const minutes = Math.floor((Date.now() - then) / 60_000)
  if (minutes < 1) return "just now"
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`
  return new Date(iso).toLocaleDateString()
}

export function AdminSecurityClient() {
  const qc = useQueryClient()

  const sessions = useQuery({
    queryKey: queryKeys.sessions(),
    queryFn: () => adminApi.sessions().then((r) => r.data),
    retry: false,
  })

  const twoFactor = useQuery({
    queryKey: queryKeys.twoFactor(),
    queryFn: () => adminApi.twoFactorStatus().then((r) => r.data),
    retry: false,
  })

  const revoke = useMutation({
    mutationFn: (sessionId: string) => adminApi.revokeSession(sessionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.sessions() })
      sileo.success({ title: "Session revoked" })
    },
    onError: (err) => {
      sileo.error({ title: "Could not revoke that session", description: apiErrorMessage(err, "Try again.") })
    },
  })

  const rows: AdminSession[] = sessions.data ?? []
  const others = rows.filter((s) => !s.is_current)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Sessions &amp; two-factor"
        description="What is signed in to this account, and what gates privileged actions."
      />

      <TwoFactorCard
        isLoading={twoFactor.isLoading}
        isError={twoFactor.isError}
        enabled={twoFactor.data?.is_2fa_enabled}
        pending={twoFactor.data?.is_2fa_pending}
      />

      <section aria-labelledby="sessions-heading" className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          {/* An `<h2>` rather than a styled `<p>`: the page has one `<h1>` and
              this is the next level down, and a screen reader's heading list is
              the fastest way to understand the page's structure. */}
          <h2 id="sessions-heading" className="text-base font-semibold">
            Active sessions
          </h2>
          {sessions.isSuccess ? (
            <p className="text-xs text-muted-foreground">
              {rows.length} active{others.length > 0 ? ` · ${others.length} other` : ""}
            </p>
          ) : null}
        </div>

        {sessions.isLoading ? (
          <div className="space-y-2" role="status">
            <span className="sr-only">Loading sessions…</span>
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        ) : sessions.isError ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-3 px-5 py-8 text-center">
              <p className="text-sm font-medium">Could not load your sessions</p>
              <Button size="sm" variant="outline" onClick={() => sessions.refetch()}>
                Try again
              </Button>
            </CardContent>
          </Card>
        ) : rows.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <Laptop className="size-6 text-muted-foreground" aria-hidden />
              <EmptyTitle>No active sessions</EmptyTitle>
              <EmptyDescription>
                That is unexpected while you are signed in — a session you are
                currently using should appear below.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <ul className="space-y-2">
            {rows.map((session) => (
              <li key={session.id}>
                <SessionRow
                  session={session}
                  onRevoke={() => revoke.mutate(session.id)}
                  revoking={revoke.isPending && revoke.variables === session.id}
                />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function TwoFactorCard({
  isLoading,
  isError,
  enabled,
  pending,
}: {
  isLoading: boolean
  isError: boolean
  enabled: boolean | undefined
  pending: boolean | undefined
}) {
  return (
    <Card
      className={
        enabled ? "border-emerald-500/40" : "border-amber-500/40"
      }
    >
      <CardContent className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
        <div className="flex min-w-0 gap-3">
          <span
            className={`grid size-9 shrink-0 place-items-center rounded-md ${
              enabled ? "bg-emerald-500/10" : "bg-amber-500/10"
            }`}
          >
            {enabled ? (
              <ShieldCheck className="size-4 text-emerald-600" aria-hidden />
            ) : (
              <ShieldOff className="size-4 text-amber-600" aria-hidden />
            )}
          </span>
          <div className="min-w-0 space-y-1">
            <h2 className="text-sm font-semibold">Two-factor authentication</h2>
            {isLoading ? (
              <div className="flex h-5 items-center" role="status">
                <Spinner className="size-3.5" />
                <span className="sr-only">Checking two-factor status…</span>
              </div>
            ) : isError ? (
              <p className="text-xs text-muted-foreground">
                Status could not be read. Treat it as unknown rather than as off.
              </p>
            ) : enabled ? (
              <p className="text-xs text-muted-foreground">
                Enabled. Ruling on a dispute and moving fees will ask for your
                password and a one-time code.
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                Not enabled. Privileged actions ask for your password only, which
                is a weaker check than a password the attacker does not have.
              </p>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {isLoading ? null : isError ? null : enabled ? (
            <Badge variant="secondary">
              <ShieldCheck className="size-3" aria-hidden />
              Enabled
            </Badge>
          ) : (
            <Badge variant="outline" className="border-amber-500/50 text-amber-700 dark:text-amber-400">
              Off
            </Badge>
          )}
          {/* A styled `Link`, not a `Button` wrapping an anchor: Base UI's Button
              wants a real `<button>`, and forcing an anchor into it produced the
              `nativeButton` console error this page was the source of. The target
              is a different app on a different origin, so `Link` is right only
              when that origin is ours — hence the plain anchor with the same
              variant classes. */}
          <a
            href={`${process.env.NEXT_PUBLIC_SITE_URL ?? ""}/settings/two-factor`}
            className={cn(
              buttonVariants({ variant: "outline", size: "sm" }),
              "inline-flex"
            )}
          >
            <KeyRound className="size-3.5" aria-hidden />
            {enabled ? "Manage" : "Set up"}
          </a>
        </div>
      </CardContent>

      {pending ? (
        <p className="border-t px-5 py-2 text-xs text-amber-700 dark:text-amber-400">
          Setup is half-finished — a code was issued but never confirmed. Finish
          or cancel it from the storefront, or a pending enrolment may block the
          next sign-in.
        </p>
      ) : null}
    </Card>
  );
}

function SessionRow({
  session,
  onRevoke,
  revoking,
}: {
  session: AdminSession
  onRevoke: () => void
  revoking: boolean
}) {
  const [confirming, setConfirming] = useState(false)

  return (
    <>
      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
          <div className="flex min-w-0 items-start gap-3">
            <Laptop className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
            <div className="min-w-0 space-y-1">
              <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                <span className="truncate">{describeAgent(session.user_agent)}</span>
                {session.is_current ? (
                  <Badge variant="secondary">This device</Badge>
                ) : null}
              </p>
              <p className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <MapPin className="size-3" aria-hidden />
                  {session.ip_address ?? "unknown IP"}
                </span>
                <span>Last active {relative(session.last_active_at)}</span>
                <span className="hidden sm:inline">
                  Signed in {relative(session.created_at)}
                </span>
              </p>
            </div>
          </div>

          {!session.is_current ? (
            <Button
              size="sm"
              variant="ghost"
              className="shrink-0 text-destructive hover:text-destructive"
              onClick={() => setConfirming(true)}
            >
              <Trash2 className="size-3.5" aria-hidden />
              Revoke
            </Button>
          ) : null}
        </CardContent>
      </Card>

      {/* Confirmation, because a revoke is immediate and irreversible and the
          button is one of several identical-looking ones in a list. The title
          names the device so the dialog is unambiguous about what it is about to
          throw away. */}
      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Revoke {describeAgent(session.user_agent)}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              That device is signed in as you and will be signed out immediately.
              It cannot be restored from here — it will need to sign in again.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep it</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                onRevoke()
              }}
              disabled={revoking}
            >
              {revoking ? "Revoking…" : "Revoke session"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}