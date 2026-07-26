# How Does Everything Work? — Simple Guide

This guide explains every concept in plain language. No jargon. No math. Just what's happening and why.

---

## What Is This Platform?

Imagine a group of friends trying to guess what will happen next week. "I think it'll rain on Tuesday." "No way, it'll be sunny." On this platform, you can actually **put money behind your guess** and trade with other people who have different opinions.

The result? The price of each guess tells you what the group collectively thinks the chances are. If "it'll rain on Tuesday" costs $0.70, the crowd is saying there's a 70% chance of rain.

This is called a **prediction market**. It's not gambling — it's a way to turn guesses into numbers you can actually trade.

---

## The Order Book — What Are People Willing to Pay?

Think of an order book like a notice board at school. People post what they're willing to buy or sell, and at what price.

```
People wanting to BUY "Yes" (bids):
  Will pay $0.72 for 50 shares
  Will pay $0.70 for 100 shares
  Will pay $0.68 for 200 shares

People wanting to SELL "Yes" (asks):
  Will sell at $0.75 for 30 shares
  Will sell at $0.78 for 20 shares
  Will sell at $0.80 for 100 shares
```

- If someone is **buying** at $0.72 and someone else is **selling** at $0.75, there's a gap — that's the **spread** ($0.03).
- When someone places a **market order** (just wants it done now), the trade happens at whatever price is available.
- When someone places a **limit order** (only at $0.70 or better), they wait until the price matches.

---

## Liquidity Pools — The Pool of Money That Makes Trading Possible

Here's the problem: if nobody else wants to trade with you, your trade doesn't happen. The **liquidity pool** solves this.

Imagine a big jar of money in the middle of the room. Two types of tokens live in the jar: **YES tokens** and **NO tokens**. When you want to trade, you don't need another person — you trade against the jar itself.

### Who fills the jar?

**Liquidity Providers (LPs)**. They put in USDC (the platform's money) and get token shares in return. In exchange, they earn a small cut (1% fee) from every trade that happens in the market.

Example: Someone puts in $1000 into a new market. The jar splits it evenly:
- 500 YES tokens
- 500 NO tokens
- That person gets LP tokens (like a receipt saying "I own part of this jar")

Now the market is ready for trading. Anyone can buy or sell against the jar.

### Why does liquidity matter?

Without liquidity:
- If you try to sell $500 worth of shares, the price crashes badly
- It's hard to trade at a fair price
- Nobody wants to be in this market

With good liquidity:
- Big trades barely move the price
- The spread stays tight (bids and asks are close together)
- Everyone gets a fair deal

---

## How Are Prices Set at the Start?

### When nobody puts in money: $0.50

A brand-new market with no money in it starts at **$0.50** for both YES and NO. It's like a coin flip — the market has no opinion yet.

### When you put in money without a probability: still $0.50

Even if you deposit $1000, if you don't say what you think, the split is 50/50. The market still thinks it's a coin flip.

### When you put in money AND say what you think: informed price

This is the interesting part. You can tell the market **"I think there's a 70% chance this event happens."** The system then splits your money according to that belief:

With $1000 and a 70% belief:
- YES tokens get: $1000 × (1 - 0.70) = **$300 worth**
- NO tokens get: $1000 × 0.70 = **$700 worth**

The market price becomes: **YES costs $0.70, NO costs $0.30** — matching your stated belief.

Why does this matter? Because now the market doesn't start ignorant. It starts with someone's informed opinion, and from there, other traders can agree or disagree — and the price moves based on what the crowd collectively decides.

---

## Buying Shares — "I Think This Will Happen"

When you **buy YES shares**, you're saying: "I believe this event will happen."

Here's what happens:
1. You deposit USDC (the platform's money)
2. The AMM (the jar) takes a **2% fee**
3. The jar gives you YES shares in return

Think of it like buying a receipt that says "I own a piece of the truth that X happened." If X does happen, your receipt is worth $1. If X doesn't happen, your receipt is worth $0.

You can also **buy NO shares** if you think the event WON'T happen.

---

## Selling Shares — "I've Changed My Mind"

When you **sell your shares**, you're cashing out.

1. You give back your YES shares (or NO shares)
2. The jar gives you USDC minus a **2% fee**

You might be selling because:
- You want to lock in your profit
- You think the price is going the other way
- You just don't care anymore

---

## The AMM — The Math That Makes It All Work

The AMM (Automated Market Maker) is a simple formula that always sets a fair price based on the ratio of shares in the jar.

The formula is: **YES price = NO shares in jar ÷ total shares in jar**

Simple example:
- Jar has 700 NO tokens and 300 YES tokens (total = 1000)
- YES price = 700 / 1000 = **$0.70**
- NO price = 300 / 1000 = **$0.30**

When you buy YES shares, you're adding NO tokens to the jar (yes, the opposite). This shifts the ratio, and the price goes up slightly. That's called **price impact** — your trade moves the market a tiny bit.

Small trades? Barely any impact. Big trades? More impact. This discourages people from manipulating the market with huge single trades.

---

## Merging and Splitting — Swapping Between Money and Balanced Pairs

### Splitting: $1 → YES + NO

**Splitting** is when you turn your USDC into a balanced pair of YES and NO tokens. You put in $100, the system takes a 2% fee, and you get $49 of YES tokens and $49 of NO tokens.

Why split?
- You want to become a **liquidity provider** (the jar needs both sides to work)
- You want to hedge your bets — you're not sure which way things will go
- You want to earn trading fees as an LP

### Merging: YES + NO → $1 (minus fees)

**Merging** is the reverse. You give back equal YES and NO tokens and get USDC back. The system takes a 2% fee.

Why merge?
- You want to cash out your liquidity
- You're done being an LP in this market
- You want to redeploy your money elsewhere

### How is this different from buying/selling?

- **Buy/Sell** — you're trading your opinion. You're picking a side.
- **Split/Merge** — you're depositing or withdrawing balanced value. You're not picking a side, you're just moving money in and out of the jar.

---

## Disputes — What If Someone Resolves a Market Wrongly?

Sometimes a market is resolved, and people think the resolution is wrong. Maybe someone claimed "It rained on Tuesday" but in fact it didn't. Maybe the source they cited isn't credible.

The dispute system lets people challenge bad resolutions. Here's how it works:

### Step 1: Market gets resolved
An admin announces "This market is resolved: Yes." The status changes to `resolved`.

### Step 2: 48-hour dispute window
For the next 48 hours, any user can file a dispute if they believe the resolution is wrong. They must provide:
- A **written explanation** of why they think it's wrong
- A **link** to credible evidence (like a news article or official source)

Once a dispute is filed, the market status changes to `dispute_window`. The resolution is paused.

### Step 3: An admin decides
An admin reviews the dispute and makes one of two rulings:

- **Upheld**: The dispute has merit. If there was a proposed resolution, it gets applied. If not, the market returns to active so the resolution can be re-attempted.
- **Dismissed**: The dispute has no merit. The market stays resolved as-is.

The user who filed the dispute gets notified of the outcome.

### Why is this important?

Without disputes:
- A lazy or biased admin could resolve markets incorrectly
- Users would have no recourse
- The platform wouldn't be trustworthy

With disputes:
- Every resolution is challengeable
- Decisions require evidence, not just opinion
- The platform stays fair and accountable

---

## How Is This Different from Gambling?

This is the most common question, and honestly, on the surface it looks similar. At 1xBet, people bet "Will Gol score a goal or not?" And 1xBet also has a **cashout** feature where you can sell your bet early before the match ends — at a price the house offers. So the resemblance is real. But here's what's different underneath:

### 1. Who Sets the Cashout Price?

At 1xBet, the **house** decides the cashout price and whether to accept it. If they think your bet is about to win, they might delay the cashout or offer a low price. If they think it's about to lose, they might let you out quickly. You don't get to choose the terms — the house does.

On our platform, you trade against **other people** at a price determined by the AMM formula (the jar). There's no house deciding whether your sale goes through. If someone else is willing to buy your share at $0.65, the trade happens instantly. You don't wait for approval.

### 2. The Price Reflects the Crowd, Not the House's Profit Margin

At a casino, the cashout price is based on the house's profit margin, not on what people collectively think. The house adjusts it to guarantee they make money regardless.

On our platform, the price moves based on **what traders actually believe**. If a key player gets injured right before a match, the YES price might drop from $0.60 to $0.30 in seconds because real people update their beliefs. The price is a living summary of what everyone currently knows.

### 3. No House Edge - Flat Fee, Not a Cut of Your Losses

Casinos are businesses that profit from your losses over time. Their odds are structured so the house always wins more than it pays out. That's the entire business model.

Our platform charges a flat **1% fee on every trade** — whether you win or lose. Whether you profit or lose on a specific trade, the platform earns the same 1%. It's the same model as a stock broker's commission. The platform provides the infrastructure (the jar, the AMM, the matching engine) and charges a small service fee. It doesn't profit from your losses.

### 4. Outcomes Are Verifiable Facts, Not Random

Casino outcomes are determined by random chance — a dice roll, a roulette wheel spin. You can't predict them, and neither can the house. The house can change the rules at any time.

Prediction markets resolve based on **verifiable real-world facts**. Did Ronaldo score a goal? Check the official match stats. Did Trump win the election? Check the certified results. The event already happened or is happening — the market is just estimating the probability before the truth comes out. And if someone claims the truth is different from what actually happened, the dispute system lets people challenge that.

### The Actual Comparison

| | Casino (like 1xBet) | Prediction Market |
|---|---|---|
| **Who decides your exit price?** | The house — unilaterally, at their discretion | The market — AMM formula based on real trades |
| **Can the house reject your cashout?** | Yes — they can delay or deny it | No — you can always sell if someone buys from you |
| **Your opponent?** | The house (which always profits) | Other people with different opinions |
| **How does the platform profit?** | From your losses over time | Flat 1% fee on every trade, regardless of outcome |
| **What determines the outcome?** | Random chance (dice, roulette) | Verifiable real-world fact |
| **Does the price encode information?** | No — odds are set by the house to guarantee profit | Yes — price reflects what the crowd collectively believes |
| **Can you trade freely?** | You're locked in once you place a bet | You can buy, sell, or exit anytime before resolution |

### A Note on Legitimacy

Prediction markets are used by major organizations worldwide. Intelligence agencies use them to forecast geopolitical events. Journalists use them to gauge public expectations. Researchers study them to understand how crowds aggregate information. The technology behind this platform is the same one powering some of the most respected forecasting tools in the world — not just a betting site.