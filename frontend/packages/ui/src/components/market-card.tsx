"use client"

import * as React from "react"

import { cn } from "@workspace/ui/lib/utils"

const dummyMarket = {
  question: "Will BTC exceed $100,000 by Dec 31, 2025?",
  yesProb: 58,
  noProb: 42,
  yesPrice: "₿0.58",
  noPrice: "₿0.42",
  volume: "$9.8M",
  activities: [
    { type: "buy", amount: "250", price: "₿0.58", prob: "58%", time: "2m ago" },
    { type: "sell", amount: "100", price: "₿0.57", prob: "57%", time: "5m ago" },
    { type: "buy", amount: "500", price: "₿0.59", prob: "59%", time: "8m ago" },
    { type: "sell", amount: "150", price: "₿0.56", prob: "56%", time: "12m ago" },
    { type: "buy", amount: "300", price: "₿0.58", prob: "58%", time: "15m ago" },
  ],
}

type Tab = "shares" | "bought" | "activity"
type PositionTab = "all" | "my"

function MarketCard({ className }: { className?: string }) {
  const [activeTab, setActiveTab] = React.useState<Tab>("shares")
  const [positionTab, setPositionTab] = React.useState<PositionTab>("all")

  return (
    <div
      className={cn(
        "w-full max-w-md rounded-xl border border-border bg-card p-4 text-xs/relaxed shadow-sm",
        className
      )}
    >
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[10px] font-bold tracking-widest text-muted-foreground">
          POLYMARKET
        </span>
        <div className="flex rounded-md border border-border p-0.5">
          {(["shares", "bought", "activity"] as Tab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "rounded-sm px-2 py-0.5 text-[10px] uppercase tracking-wide transition-colors",
                activeTab === tab
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted"
              )}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Question */}
      <h2 className="mb-3 text-sm font-medium leading-snug">
        {dummyMarket.question}
      </h2>

      {/* Yes/No Buttons */}
      <div className="mb-3 grid grid-cols-2 gap-2">
        <button className="flex flex-col items-start rounded-lg border border-green-500/30 bg-green-500/5 p-2.5 text-left transition-colors hover:bg-green-500/10">
          <div className="mb-1 flex w-full items-center justify-between">
            <span className="text-[10px] font-semibold uppercase text-green-500">
              Yes
            </span>
            <span className="text-lg font-bold text-green-500">
              {dummyMarket.yesProb}%
            </span>
          </div>
          <span className="text-muted-foreground">{dummyMarket.yesPrice}</span>
        </button>
        <button className="flex flex-col items-start rounded-lg border border-red-500/30 bg-red-500/5 p-2.5 text-left transition-colors hover:bg-red-500/10">
          <div className="mb-1 flex w-full items-center justify-between">
            <span className="text-[10px] font-semibold uppercase text-red-500">
              No
            </span>
            <span className="text-lg font-bold text-red-500">
              {dummyMarket.noProb}%
            </span>
          </div>
          <span className="text-muted-foreground">{dummyMarket.noPrice}</span>
        </button>
      </div>

      {/* Volume */}
      <div className="mb-4 text-muted-foreground">
        Vol{" "}
        <span className="font-medium text-foreground">
          {dummyMarket.volume}
        </span>
      </div>

      {/* Position Tabs */}
      <div className="mb-2 flex gap-4 border-b border-border">
        {(["all", "my"] as PositionTab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setPositionTab(tab)}
            className={cn(
              "pb-2 text-[10px] uppercase tracking-wide transition-colors",
              positionTab === tab
                ? "border-b-2 border-primary font-medium text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {tab === "all" ? "All" : "My Position"}
            {tab === "all" && (
              <span className="ml-1 text-muted-foreground">•</span>
            )}
          </button>
        ))}
      </div>

      {/* Activity List */}
      <div className="space-y-2">
        {dummyMarket.activities.map((activity, i) => (
          <div
            key={i}
            className="flex items-center justify-between py-1.5"
          >
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase",
                  activity.type === "buy"
                    ? "bg-green-500/10 text-green-500"
                    : "bg-red-500/10 text-red-500"
                )}
              >
                {activity.type}
              </span>
              <span className="font-medium">{activity.amount}</span>
              <span className="text-muted-foreground">@{activity.price}</span>
            </div>
            <div className="flex items-center gap-3 text-muted-foreground">
              <span>{activity.prob}</span>
              <span className="w-12 text-right">{activity.time}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export { MarketCard }
