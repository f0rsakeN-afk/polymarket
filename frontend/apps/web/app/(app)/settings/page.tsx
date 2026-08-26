import Link from "next/link"
import { SettingsBreadcrumb } from "@/components/settings/settings-breadcrumb"
import { Card, CardContent } from "@workspace/ui/components/card"
import { ShieldCheck, Users, Bell, KeyRound } from "lucide-react"

const sections = [
  {
    href: "/settings/sessions",
    icon: Users,
    title: "Active Sessions",
    description: "Manage your active sessions and revoke devices you don't recognize.",
  },
  {
    href: "/settings/referrals",
    icon: KeyRound,
    title: "Referrals",
    description: "Invite friends and earn rewards for every completed signup.",
  },
  {
    href: "/settings/notifications",
    icon: Bell,
    title: "Notifications",
    description: "Choose how you receive alerts — email and in-app.",
  },
  {
    href: "/settings/2fa",
    icon: ShieldCheck,
    title: "Security",
    description: "Manage 2FA, password, and account security settings.",
  },
]

export default function SettingsPage() {
  return (
    <div className="container mx-auto max-w-7xl px-4 py-8 space-y-6">
      <SettingsBreadcrumb page="Overview" />

      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Manage your account and preferences.
        </p>
      </div>

      <div className="grid gap-4">
        {sections.map(({ href, icon: Icon, title, description }) => (
          <Link key={href} href={href} className="block group">
            <Card className="overflow-hidden group-hover:bg-accent/40 transition-colors">
              <CardContent className="py-5 px-6">
                <div className="flex items-center gap-4">
                  <div className="size-9 rounded-lg bg-accent flex items-center justify-center shrink-0">
                    <Icon className="size-4 text-muted-foreground" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium group-hover:text-foreground">{title}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
                  </div>
                  <div className="size-4 text-muted-foreground/40 shrink-0">
                    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path d="M6 3l5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}
