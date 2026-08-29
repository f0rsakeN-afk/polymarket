import Link from "next/link"
import { SettingsBreadcrumb } from "@/components/settings/settings-breadcrumb"
import { Card, CardContent } from "@workspace/ui/components/card"
import { ShieldCheck, Users, Bell, KeyRound } from "lucide-react"

const sections = [
  {
    href: "/settings/sessions",
    icon: Users,
    title: "Active Sessions",
    description:
      "Manage your active sessions and revoke devices you don't recognize.",
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
    <div className="container mx-auto max-w-7xl space-y-6 px-4 py-8">
      <SettingsBreadcrumb page="Overview" />

      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Manage your account and preferences.
        </p>
      </div>

      <div className="grid gap-4">
        {sections.map(({ href, icon: Icon, title, description }) => (
          <Link key={href} href={href} className="group block">
            <Card className="overflow-hidden transition-colors group-hover:bg-accent/40">
              <CardContent className="px-6 py-5">
                <div className="flex items-center gap-4">
                  <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent">
                    <Icon className="size-4 text-muted-foreground" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium group-hover:text-foreground">
                      {title}
                    </p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {description}
                    </p>
                  </div>
                  <div className="size-4 shrink-0 text-muted-foreground/40">
                    <svg
                      viewBox="0 0 16 16"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                    >
                      <path
                        d="M6 3l5 5-5 5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
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
