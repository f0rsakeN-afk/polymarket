"use client"

import { useCallback } from "react"
import { useReferralCode, useReferralStats } from "@/hooks/use-referrals"
import { Card, CardContent, CardHeader, CardTitle } from "@workspace/ui/components/card"
import { Button } from "@workspace/ui/components/button"
import { Spinner } from "@workspace/ui/components/spinner"
import { Copy, Check } from "lucide-react"
import { useState } from "react"
import { sileo } from "sileo"

export default function ReferralsPage() {
  const { data: codeData, isLoading: codeLoading } = useReferralCode()
  const { data: statsData, isLoading: statsLoading } = useReferralStats()
  const [copied, setCopied] = useState(false)

  const referralCode = codeData?.referral_code ?? null
  const referralLink = referralCode ? `${typeof window !== "undefined" ? window.location.origin : ""}/register?ref=${referralCode}` : ""

  const copyCode = useCallback(async () => {
    if (!referralCode) return
    await navigator.clipboard.writeText(referralCode)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [referralCode])

  const copyLink = useCallback(async () => {
    if (!referralLink) return
    await navigator.clipboard.writeText(referralLink)
    sileo.success({ title: "Link copied!" })
  }, [referralLink])

  if (codeLoading || statsLoading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner className="size-6" />
      </div>
    )
  }

  const stats = statsData ?? null

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Referrals</h1>
        <p className="text-sm text-muted-foreground">Invite friends and earn rewards</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Your Referral Code</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {referralCode ? (
            <>
              <div className="flex items-center gap-2">
                <code className="flex-1 rounded-md bg-muted px-4 py-2 text-lg font-mono font-bold tracking-wider">
                  {referralCode}
                </code>
                <Button variant="outline" size="sm" onClick={copyCode}>
                  {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
                </Button>
              </div>
              <div className="flex items-center gap-2">
                <input
                  readOnly
                  value={referralLink}
                  className="flex-1 rounded-md bg-muted px-3 py-2 text-xs font-mono"
                />
                <Button size="sm" onClick={copyLink}>Copy Link</Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Share this link with friends. They get bonus credits on signup!
              </p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">No referral code available</p>
          )}
        </CardContent>
      </Card>

      {stats && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Your Stats</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-4 text-center">
              <div>
                <p className="text-2xl font-bold">{stats.total_referrals}</p>
                <p className="text-xs text-muted-foreground">Total Referrals</p>
              </div>
              <div>
                <p className="text-2xl font-bold">{stats.completed_referrals}</p>
                <p className="text-xs text-muted-foreground">Completed</p>
              </div>
              <div>
                <p className="text-2xl font-bold">${stats.total_rewards_earned?.toFixed(2) ?? "0.00"}</p>
                <p className="text-xs text-muted-foreground">Rewards Earned</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}