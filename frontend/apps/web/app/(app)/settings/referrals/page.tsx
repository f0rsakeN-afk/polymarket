"use client"

import { useCallback, useState, useSearchParams, useRouter } from "react"
import { useReferralCode, useReferralStats } from "@/hooks/api/use-referrals"
import { SettingsBreadcrumb } from "@/components/settings/settings-breadcrumb"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Button } from "@workspace/ui/components/button"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { Badge } from "@workspace/ui/components/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import { Copy, Check, Gift, Users, Coins } from "lucide-react"
import { sileo } from "sileo"
import { cn } from "@workspace/ui/lib/utils"

// ── Helpers ──────────────────────────────────────────────────────────────────
function formatDateShort(dateStr: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
  }).format(new Date(dateStr))
}

type ReferralStatus = "pending" | "completed" | "expired"

type ReferralItem = {
  id: string
  referred_id: string
  status: string
  reward_amount: string
  created_at: string
  completed_at: string | null
}

function StatusBadge({ status }: { status: ReferralStatus }) {
  const styles: Record<ReferralStatus, string> = {
    pending: "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300",
    completed: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300",
    expired: "bg-muted text-muted-foreground",
  }
  return (
    <Badge className={cn("text-xs capitalize font-medium", styles[status] ?? styles.pending)}>
      {status}
    </Badge>
  )
}

// ── Stat Card ──────────────────────────────────────────────────────────────────

function StatCard({
  icon,
  label,
  value,
  sub,
}: {
  icon: typeof Gift
  label: string
  value: string | number
  sub?: string
}) {
  return (
    <Card className="overflow-hidden pt-0">
      <CardContent className="pt-6">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{label}</p>
            <p className="text-2xl font-bold mt-1">{value}</p>
            {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
          </div>
          <div className="size-9 rounded-lg bg-accent flex items-center justify-center shrink-0 mt-0.5">
            <Icon className="size-4 text-muted-foreground" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ── Code Display ───────────────────────────────────────────────────────────────

function CodeDisplay({ code, link }: { code: string; link: string }) {
  const [codeCopied, setCodeCopied] = useState(false)
  const [linkCopied, setLinkCopied] = useState(false)

  const copyCode = useCallback(async () => {
    await navigator.clipboard.writeText(code)
    setCodeCopied(true)
    sileo.success({ title: "Referral code copied!" })
    setTimeout(() => setCodeCopied(false), 2000)
  }, [code])

  const copyLink = useCallback(async () => {
    await navigator.clipboard.writeText(link)
    setLinkCopied(true)
    sileo.success({ title: "Referral link copied!" })
    setTimeout(() => setLinkCopied(false), 2000)
  }, [link])

  return (
    <Card className="overflow-hidden pt-0">
      <CardContent className="pt-6 space-y-4">
        {/* Code row */}
        <div className="flex items-center gap-3">
          <div className="flex-1 rounded-lg bg-muted border px-4 py-3 flex items-center justify-between">
            <span className="text-xl font-mono font-bold tracking-widest">{code}</span>
            <button
              onClick={copyCode}
              className={cn(
                "size-8 rounded-md flex items-center justify-between transition-all",
                codeCopied
                  ? "bg-emerald-100 text-green-700 dark:bg-emerald-900 dark:text-emerald-300"
                  : "bg-accent text-muted-foreground hover:bg-accent/80",
              )}
            >
              {codeCopied ? <Check className="size-4" /> : <Copy className="size-4" />}
            </button>
          </div>
        </div>

        {/* Link row */}
        <div className="flex items-center gap-3">
          <div className="flex-1 rounded-lg bg-muted border px-3 py-2 flex items-center overflow-hidden">
            <span className="text-xs font-mono text-muted-foreground truncate">{link}</span>
          </div>
          <button
            onClick={copyLink}
            className="shrink-0"
          >
            {linkCopied ? <Check className="size-4 mr-1" /> : <Copy className="size-4 mr-1" />}
            {linkCopied ? "Copied" : "Copy Link"}
          </button>
        </div>

        <p className="text-xs text-muted-foreground">
          Share your link • friends get bonus credits on signup and you earn when they complete their first trade.
        </p>
      </CardContent>
    </Card>
  )
}

// ── Referrals Table ───────────────────────────────────────────────────────────

function ReferralsTable({ referrals }: { referrals: ReferralItem[] }) {
  if (referrals.length === 0) {
    return (
      <Card className="overflow-hidden pt-0">
        <CardContent className="flex h-48 items-center justify-center text-sm text-muted-foreground">
          No referrals yet • share your code to get started!
        </CardContent>
      )
    )
  }

  return (
    <Card className="overflow-hidden pt-0">
      <div className="overflow-auto" style={{ maxHeight: "600px", minHeight: "200px" }}>
        <Table noWrapper className="w-full" style={{ tableLayout: "fixed" }}>
          <colgroup>
            <col className="w-[35%]" />
            <col className="w-[15%]" />
            <col className="w-[15%]" />
            <col className="w-[20%]" />
            <col className="w-[15%]" />
          </colgroup>
          <TableHeader className="sticky top-0 z-20 bg-muted">
            <TableRow className="hover:bg-transparent">
              <TableHead>Referred User</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Reward</TableHead>
              <TableHead>Invited</TableHead>
              <TableHead>Completed</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {referrals.map((ref: ReferralItem) => (
              <TableRow key={ref.id} className="hover:bg-accent/30 transition-colors">
                <TableCell>
                  <p className="text-sm font-mono text-muted-foreground truncate">
                    {ref.referred_id.slice(0, 8)}…
                  </p>
                </TableCell>
                <TableCell>
                  <StatusBadge status={ref.status as ReferralStatus} />
                </TableCell>
                <TableCell>
                  <p className="text-sm font-medium">
                    {ref.reward_amount && Number(ref.reward_amount) > 0
                      ? `$${Number(ref.reward_amount).toFixed(2)}`
                      : "•"}
                  </p>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {formatDateShort(ref.created_at)}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {ref.completed_at ? formatDateShort(ref.completed_at) : "•"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </Card>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function ReferralsPage() {
  const { data: codeData, isLoading: codeLoading } = useReferralCode()
  const { data: statsData } = useReferralStats()
  const searchParams = useSearchParams()
  const refParam = searchParams.get("ref") ?? undefined
  const utmParam = searchParams.get("utm_source") ?? undefined
  const redirectParam = searchParams.get("redirect") ?? undefined

  const referralCode = codeData?.referral_code ?? null
  const origin = typeof window !== "undefined" ? window.location.origin : ""

  // Build referral link with UTM parameters
  const referralLink = referralCode
    ? `${origin}/register?ref=${referralCode}&utm_source=website&utm_medium=referral&utm_campaign=referral_program`
    : ""

  // If there's a ref param in URL, extract the code
  const urlReferralCode = refParam || undefined

  // If there's a redirect param, use it after auth
  const redirectTo = redirectParam || "/markets"

  const stats = statsData ?? null
  const isAnyLoading = codeLoading

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8 space-y-6">
      <SettingsBreadcrumb page="Referrals" />
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Referrals</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Invite friends and earn rewards for every completed signup.
        </p>
      </div>

      {isAnyLoading ? (
        <div className="space-y-6">
          {/* Code + stats skeletons */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <Card>
              <CardContent className="pt-6 space-y-4">
                <Skeleton className="h-8 w-full rounded-lg" />
                <Skeleton className="h-9 w-full rounded-lg" />
                <Skeleton className="h-3 w-48" />
              </CardContent>
            </Card>
            <div className="lg:col-span-2 grid grid-cols-3 gap-4">
              {[1, 2, 3].map((i) => (
                <Card key={i}>
                  <CardContent className="pt-6">
                    <div className="flex items-start justify-between">
                      <div className="space-y-1">
                        <Skeleton className="h-3 w-20" />
                        <Skeleton className="h-7 w-12 mt-2" />
                        <Skeleton className="h-3 w-16 mt-1" />
                      </div>
                      <Skeleton className="size-9 rounded-lg" />
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <>
          {/* Code + Stats */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-1">
              {referralCode ? (
                <CodeDisplay code={referralCode} link={referralLink} />
              ) : (
                <Card className="overflow-hidden pt-0">
                  <CardContent className="pt-6 text-sm text-muted-foreground">
                    No referral code available
                  </CardContent>
                </Card>
              )}
            </div>

            <div className="lg:col-span-2 grid grid-cols-3 gap-4">
              <StatCard
                icon={Users}
                label="Total Referrals"
                value={stats?.total_referrals ?? 0}
                sub="invited"
              />
              <StatCard
                icon={Check}
                label="Completed"
                value={stats?.completed_referrals ?? 0}
                sub="signed up & traded"
              />
              <StatCard
                icon={Coins}
                label="Rewards Earned"
                value={`$${Number(stats?.total_rewards_earned ?? 0).toFixed(2)}`}
                sub="total earned"
              />
            </div>
          </div>

          {/* Code + Link Section */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div>
              {referralCode ? (
                <>
                  <CodeDisplay code={referralCode} link={referralLink} />
                  <p className="text-sm text-muted-foreground mt-2">
                    Share this link with friends • friends get bonus credits on signup and you earn when they complete their first trade
                  </p>
                </>
              ) : (
                <Card className="overflow-hidden pt-0">
                  <CardContent className="pt-6 text-sm text-muted-foreground">
                    No referral code available
                  </CardContent>
                </Card>
              )}
            </div>
            <div>
              <p className="text-sm text-muted-foreground mb-2">
                Your referral link:
              </p>
              <CodeDisplay code={referralCode} link={referralLink} />
            </div>
          </div>

          {/* Traffic Source Info */}
          {utmParam && (
            <div className="mt-4 p-3 bg-muted rounded-lg text-sm text-muted-foreground">
              <p className="font-medium">Traffic source detected:</p>
              <p className="mt-1">{utmParam}</p>
            </div>
          )}

          {/* Redirect Notice */}
          {redirectParam && (
            <div className="mt-4 p-3 bg-muted rounded-lg text-sm text-muted-foreground">
              <p className="font-medium">Redirect after signup:</p>
              <p className="mt-1">{redirectParam}</p>
            </div>
          )}

          {/* Referral History */}
          <div>
            <h2 className="text-sm font-semibold text-foreground mb-3">Referral History</h2>
            {/* Extract referred IDs from URL params if present */}
            {refParam && <p className="text-xs text-muted-foreground mb-2">
              Visitor came via referral code: {refParam}
            </p>}
            <ReferralsTable referrals={(stats?.referrals as ReferralItem[]) ?? []} />
          </div>
        </>
      )}
    </div>
  )
}