# How Does Everything Work? — Simple Guide

This guide explains every concept in plain language. No jargon. No math. Just what's happening and why.

> Written to be read by *anyone* on the team — no coding background needed. For the deeper version,
> see the siblings in this folder: `trading-engine.md` (exact formulas, order matching), 
> `architecture.md` (how the system is built), `auth-and-security.md`, `docker-concurrency-realtime.md`,
> and `viva-questions.md` (the question bank).

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

**Liquidity Providers (LPs)**. They put in USDC (the platform's money) and get LP tokens in return — a receipt showing what fraction of the jar they own. In exchange, they earn a share of the **2% trading fee** that stays inside the jar on every trade (and, at settlement, a share of the platform's collected protocol fees too).

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

### The market creator seeds it: liquidity + an optional belief

When someone creates a market they can pour in **initial liquidity** and optionally state an **initial probability** — their own belief about how likely YES is.

With $1000 of initial liquidity and an initial probability of 70%:
- YES side of the jar gets: $1000 × 0.70 = **$700**
- NO side of the jar gets: $1000 × 0.30 = **$300**

Because price is just "this side ÷ total", the prices open at **YES = $0.70, NO = $0.30** — exactly the belief the creator stated. (If they don't state a probability, the money is split 50/50 and the market opens at $0.50/$0.50.)

Why does this matter? Because the market doesn't start ignorant. It starts with someone's informed opinion, and from there, other traders can agree or disagree — and the price moves as the crowd updates what it collectively believes.

### Important: this only happens at creation

After that, ordinary traders cannot "state a belief". The `/split` endpoint gives everyone an **equal** YES+NO pair, and only **buying and selling** moves the price — your trade pushes the side you traded towards up, and the other side down.

---

## Buying Shares — "I Think This Will Happen"

When you **buy YES shares**, you're saying: "I believe this event will happen."

Here's what happens:
1. You deposit USDC (the platform's money)
2. The jar takes a **2% trading fee** out of your deposit (the platform separately records a **1% protocol fee** — together roughly 3% of the trade, and both are charged whether you end up winning or losing)
3. The jar gives you YES shares in return

Think of it like buying a receipt that says "I own a piece of the truth that X happened." If X does happen, your receipt is worth $1. If X doesn't happen, your receipt is worth $0.

You can also **buy NO shares** if you think the event WON'T happen.

---

## Selling Shares — "I've Changed My Mind"

When you **sell your shares**, you're cashing out.

1. You give back your YES shares (or NO shares)
2. The jar gives you USDC minus the **2% trading fee** (again, the 1% protocol fee is recorded on top)

You might be selling because:
- You want to lock in your profit
- You think the price is going the other way
- You just don't care anymore

---

## The AMM — The Math That Makes It All Work

The AMM (Automated Market Maker) is a simple formula that always sets a fair price based on the ratio of shares in the jar.

The formula is: **YES price = YES shares in jar ÷ total shares in jar** (and NO price is the other share, so the two always add up to exactly $1).

Simple example:
- Jar holds 700 YES tokens and 300 NO tokens (total = 1000)
- YES price = 700 / 1000 = **$0.70**
- NO price = 300 / 1000 = **$0.30**

When you buy YES shares, they go *into* the jar, so the YES side grows and **the YES price rises** (and NO falls with it). That's called **price impact** — your own trade moves the market a little bit.

Small trades? Barely any impact. Big trades? More impact: your order is charged at the *new, worse* price it created, all the way through. This is also why you can't cheat the jar — buy and immediately sell the same shares and you get back exactly what you put in **minus the fee**: the price you pushed up is the price you paid, the price you pushed down is the price you're paid at. The only thing trading can ever cost you is the fee.

---

## Merging and Splitting — Swapping Between Money and Balanced Pairs

### Splitting: $1 → YES + NO

**Splitting** is when you turn your USDC into a balanced pair of YES and NO tokens. You put in $100, the system takes a 2% fee, and you get $49 of YES tokens and $49 of NO tokens.

Why split?
- You want both sides at once: a YES+NO pair is always worth exactly $1, no matter what happens — so it's a *neutral* position you can later sell one side of
- You want to prepare shares to sell or to provide depth with
- (Becoming an LP — earning a cut of trading fees — is a **separate** "add liquidity" action that deposits into the jar itself, not a split.)

### Merging: YES + NO → $1 (minus fees)

**Merging** is the reverse. You give back equal YES and NO tokens and get USDC back. The system takes a 2% fee.

Why merge?
- You want to cash out a balanced pair back into dollars
- You want to redeploy your money elsewhere

Because you must hold *both* sides to merge, merging realizes the profit or loss on each side separately.

### Do split and merge move the price?

No. They only create or destroy shares **you** hold — they never touch the jar's own reserves, so the market price is unchanged. Split → merge in one go costs you exactly the fee, the same rule as trading.

### How is this different from buying/selling?

- **Buy/Sell** — you're trading your opinion. You're picking a side.
- **Split/Merge** — you're depositing or withdrawing balanced value. You're not picking a side, you're just moving money in and out of *your own holdings*.

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

## When the Event Ends — Settlement

Resolution is the moment the truth becomes official: did it rain, did the team win, did the candidate get elected?

1. **The market resolves.** An admin marks it `resolved` with YES or NO as the outcome (after the dispute window, if anyone challenged it).
2. **Winning shares pay $1 each.** If YES won, every YES share in your account is worth exactly $1 and is added to your wallet balance. NO shares are worth $0 and are recorded as a loss.
3. **Nobody is charged anything at this step.** The trading fee was already paid when you traded. Settlement itself takes no cut.
4. **It can only happen once.** Each position is flagged with a `settled_at` timestamp under a row lock, so a retried background job or a double-click on "claim" can never pay you twice.
5. **Where the money comes from:** the pool's escrow. Every buy, split and deposit put those dollars
   in; a sell, merge, LP exit or fee sweep took some out. At resolution the order is fixed —
   **winners, then the platform's fees, then liquidity providers** (a pro-rata slice of whatever is
   left) — so an LP carries the pool's trading P&L and the fees, not the outcome.

> Honest footnote: the escrow is enforced by one debit/credit choke point on the pool row, and
> settlement refuses to run at all if the escrow cannot cover the whole payout — nobody is paid
> partially, and a winner can always claim instead — and a nightly job re-checks every pool's
> escrow against its open claims so an imbalance surfaces before resolution rather than during
> it. What is missing is anyone *watching* those alerts. `trading-engine.md` §6 lists that alongside the
> other limits we admit to.

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

Our platform charges a small **flat trading fee — 2% inside the pool plus a 1% protocol fee, about 3% of the trade — whether you win or lose**, and **nothing at all is taken when you're paid out**. Whether you profit or lose on a specific trade, the platform earns the same fee. It's the same model as a stock broker's commission. The platform provides the infrastructure (the jar, the AMM, the matching engine) and charges a small service fee. It doesn't profit from your losses.

### 4. Outcomes Are Verifiable Facts, Not Random

Casino outcomes are determined by random chance — a dice roll, a roulette wheel spin. You can't predict them, and neither can the house. The house can change the rules at any time.

Prediction markets resolve based on **verifiable real-world facts**. Did Ronaldo score a goal? Check the official match stats. Did Trump win the election? Check the certified results. The event already happened or is happening — the market is just estimating the probability before the truth comes out. And if someone claims the truth is different from what actually happened, the dispute system lets people challenge that.

### The Actual Comparison

| | Casino (like 1xBet) | Prediction Market |
|---|---|---|
| **Who decides your exit price?** | The house — unilaterally, at their discretion | The market — AMM formula based on real trades |
| **Can the house reject your cashout?** | Yes — they can delay or deny it | No — you can always sell if someone buys from you |
| **Your opponent?** | The house (which always profits) | Other people with different opinions |
| **How does the platform profit?** | From your losses over time | A flat ~3% trading fee (2% pool + 1% protocol), same on every trade, and nothing at settlement |
| **What determines the outcome?** | Random chance (dice, roulette) | Verifiable real-world fact |
| **Does the price encode information?** | No — odds are set by the house to guarantee profit | Yes — price reflects what the crowd collectively believes |
| **Can you trade freely?** | You're locked in once you place a bet | You can buy, sell, or exit anytime before resolution |

### A Note on Legitimacy

Prediction markets are used by major organizations worldwide. Intelligence agencies use them to forecast geopolitical events. Journalists use them to gauge public expectations. Researchers study them to understand how crowds aggregate information. The technology behind this platform is the same one powering some of the most respected forecasting tools in the world — not just a betting site.