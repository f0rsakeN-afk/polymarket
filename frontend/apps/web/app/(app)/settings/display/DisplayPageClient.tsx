"use client"

import { SettingsBreadcrumb } from "@/components/settings/settings-breadcrumb"
import { Button } from "@workspace/ui/components/button"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Label } from "@workspace/ui/components/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { Switch } from "@workspace/ui/components/switch"
import { cn } from "@workspace/ui/lib/utils"
import {
  useRealtimePrefs,
  type MotionMode,
  type SignificanceRule,
} from "@/lib/realtime-prefs"

/**
 * The realtime preferences, made reachable.
 *
 * They already existed and already worked — `usePriceTick` and the market cards
 * read them, and the defaults they fell back to were correct. But
 * `RealtimePrefsProvider` was never mounted and nothing ever called `set` or
 * `setMotion`, so the whole layer was unreachable: every user got the shipped
 * defaults and no way to change them.
 *
 * That matters for the screen-reader announcement especially. An announcement
 * preference that cannot be turned on is not a preference.
 *
 * Grouped under one heading rather than scattered, because they answer a single
 * question: **how much do I want realtime updates interrupting me?** Motion is
 * visual interruption, speech is audible interruption, and they are correlated
 * enough to belong together and separate enough to need their own switches.
 */

const MOTION_OPTIONS: { value: MotionMode; label: string; hint: string }[] = [
  { value: "off", label: "Never", hint: "Quietest. Right for a dense grid." },
  { value: "significant", label: "Significant moves only", hint: "A move the number on screen would show." },
  { value: "all", label: "Every change", hint: "Everything, however small." },
]

const RULE_OPTIONS: { value: SignificanceRule; label: string }[] = [
  { value: "display", label: "When the displayed number changes" },
  { value: "absolute", label: "A fixed number of points" },
  { value: "relative", label: "A fraction of the current price" },
]

function Row({
  title,
  description,
  children,
  htmlFor,
}: {
  title: string
  description: string
  children: React.ReactNode
  htmlFor?: string
}) {
  return (
    <div className="flex items-start justify-between gap-6 py-4 not-last:border-b">
      <div className="min-w-0">
        <Label htmlFor={htmlFor} className="text-sm font-medium">
          {title}
        </Label>
        <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

export function DisplayPageClient() {
  const {
    prefs,
    motionOverride,
    setMotion,
    set,
    reset,
    systemReducedMotion,
  } = useRealtimePrefs()

  return (
    <div className="container mx-auto max-w-3xl px-4 py-8 space-y-6">
      <SettingsBreadcrumb page="Display" />

      <div>
        <h1 className="text-2xl font-bold tracking-tight">Display &amp; announcements</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          How much the realtime layer is allowed to interrupt you.
        </p>
      </div>

      <Card>
        <CardContent className="px-6 py-2">
          <Row
            title="Price change animation"
            htmlFor="motion-mode"
            description={
              systemReducedMotion && motionOverride === null
                ? "Currently following your system’s reduced-motion setting."
                : "Highlight a card when its price moves."
            }
          >
            <div className="w-56">
              <Select
                value={motionOverride ?? (systemReducedMotion ? "off" : prefs.motion)}
                onValueChange={(value) => setMotion(value as MotionMode)}
              >
                <SelectTrigger id="motion-mode" aria-label="Price change animation">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MOTION_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </Row>

          <Row
            title="What counts as a move"
            htmlFor="significance-rule"
            description="Shared by the animation and the spoken announcements, so they never disagree about what moved."
          >
            <div className="w-56">
              <Select
                value={prefs.rule}
                onValueChange={(value) => set("rule", value as SignificanceRule)}
              >
                <SelectTrigger id="significance-rule" aria-label="What counts as a move">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RULE_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </Row>

          <Row
            title="Live indicator"
            htmlFor="show-live-badge"
            description="Show the streaming dot on cards fed by the socket."
          >
            <Switch
              id="show-live-badge"
              checked={prefs.showLiveBadge}
              onCheckedChange={(checked) => set("showLiveBadge", checked)}
            />
          </Row>

          <Row
            title="Recent-move tint"
            htmlFor="show-active-tint"
            description="Tint a card that moved in the last few seconds."
          >
            <Switch
              id="show-active-tint"
              checked={prefs.showActiveTint}
              onCheckedChange={(checked) => set("showActiveTint", checked)}
            />
          </Row>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="px-6 py-2">
          <Row
            title="Announce price changes"
            htmlFor="announce-prices"
            description="Read significant price moves aloud through your screen reader. Moves are grouped into one announcement per market so a busy market is summarised rather than read tick by tick."
          >
            <Switch
              id="announce-prices"
              checked={prefs.announcePrices}
              onCheckedChange={(checked) => set("announcePrices", checked)}
            />
          </Row>

          {prefs.announcePrices && (
            <Row
              title="Minimum gap between announcements"
              htmlFor="announce-interval"
              description="How long to collect price changes before reading them out."
            >
              <div className="w-56">
                <Select
                  value={String(prefs.announceIntervalMs)}
                  onValueChange={(value) => set("announceIntervalMs", Number(value))}
                >
                  <SelectTrigger id="announce-interval" aria-label="Minimum gap between announcements">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1000">Every second</SelectItem>
                    <SelectItem value="2000">Every 2 seconds</SelectItem>
                    <SelectItem value="5000">Every 5 seconds</SelectItem>
                    <SelectItem value="15000">Every 15 seconds</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </Row>
          )}
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button variant="outline" size="sm" onClick={reset}>
          Reset to defaults
        </Button>
        <p className={cn("text-xs text-muted-foreground")}>
          Saved on this device. Nothing is sent to the server.
        </p>
      </div>
    </div>
  )
}