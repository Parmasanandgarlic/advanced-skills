# Bybit Options Wheel AI Skill (Options Wheel / 风火轮)

> **Discovery**: users download the skill from the **Bybit Skill Hub** (App / web).
>
> **Usage**: the user hands the skill to an AI assistant (Claude / ChatGPT / Cursor / ...), and the AI uses the user's Bybit API key to execute the strategy against the real v5 API.
>
> **AI is an executor, not an advisor**: explain the strategy → list defaults → CONFIRM → **actually place orders**. No App push channel; **whether a background loop runs depends on host capability** (Step 0 detection) — session-persistent or scheduled-task hosts can run continuous rounds; single-shot hosts fall back to manual per-round.
>
> **Bilingual runtime**: the skill supports both English and Chinese users. The AI mirrors the user's language for narrative output; CONFIRM synonyms (`OK`, `yes`, `好`, `确认`, `確認`, ...) and position-sizing phrases (`position 30%`, `仓位 30%`) are recognised in both languages.
>
> This document (Readme.md) is the internal-stakeholder view.

## One-line positioning

**A short-option premium collection strategy executed inside chat via the user's AI Subaccount + AI agent.** The AI uses the user-authorised API key to place real orders on Bybit v5, selling OTM Puts / Calls to collect premium each round.

### User journey (executor model)

```
[Discovery]
Bybit Skill Hub → user finds Options Wheel → downloads skill package
        ↓
[Setup in Bybit App]
User opens AI Subaccount + deposits USDT + enables options + issues API key
(Read + Trade Options; Withdraw disabled)
        ↓
[Chat with AI agent]
Hand the skill to Claude / ChatGPT / Cursor
        ↓
AI Step 1: Check for API key
  ├ Missing → one-time prompt "open subaccount + issue key in App, then return", stop
  └ Present → one /v5/account/wallet-balance connectivity check
        ↓
AI Step 2: Explain strategy + best / likely / worst framing
        ↓
AI Step 3: Show defaults — "OK to run / tell me what to change"
  defaults: BTC / Mode D / Standard / orderQty = min_qty (BTC 0.01) /
            7d expiry / 20% max DD (auto-close on trip)
  size override: user may say "position X%" or "仓位 X%" or a specific qty;
                 agent translates and re-renders the confirmation card
        ↓
AI Step 4: User CONFIRMs → AI executes
  - Vol Skew scan          (/v5/market/tickers)
  - Contract selection     (/v5/market/instruments-info)
  - Balance check          (/v5/account/wallet-balance)
  - Spread sanity check    (>5% asks user to reconfirm)
  - Market order placement (/v5/order/create orderType=Market,
                            orderLinkId=wheel-...)
  - Same-turn reply: fill price + net premium received
        ↓
[Follow-up actions — only when the user asks]
"how are my positions?" / "我倉位怎樣?"
                       → /v5/position/list + /v5/order/realtime
"should I roll?" (T-2d) → compute next-round premium vs current mark, recommend
"stop"                 → clarify intent: "stop opening new"
                         (/v5/order/cancel unfilled)
                         OR "close everything"
                         (cancel unfilled + Buy reduceOnly to flatten)
"check drawdown"       → compute (start − current) / start;
                         force stop if over threshold
```

### Key boundaries
- **Continuous rounds is the default** — Step 3 CONFIRM authorises the whole wheel to auto-roll and auto-start subsequent rounds under the same parameters.
- Continuous rounds **depend on host capability** (Step 0 detection): session-persistent hosts (Claude Desktop / ChatGPT) require the chat window to stay open; scheduled-task hosts (Claude Code Cron, etc.) can wake up in the background; single-shot hosts (single-question browser sessions) **fall back to manual per-round**, and the Step 3 card is rewritten with the fallback message.
- No App push channel (the agent does not push to the App or send email; status is reported inside the chat).
- Failure handling: drawdown breached → auto-close all + wait for `CONFIRM-RESUME`; three consecutive open failures → pause.
- Need 24/7 server-side execution independent of host → use the Bybit App-side Skill Hub Options Wheel form instead.

---

## Integration with existing Bybit products

| Existing product | Integration |
|---|---|
| **AI Subaccount** (live) | This skill only runs inside an AI Subaccount; funds and permissions are isolated from the main account. |
| **Skill Hub** (Michael Mei's admin) | Add a new "Persistent Bot" category, separated from the six existing Earn-oriented chat skills. |
| **Easy / Pro Mode** (Andy) | Same framework: Easy exposes 3–4 sliders; Pro exposes the full spec. |
| **Bybit Strategy Trading** (DBU TWAP / Chase / POV) | Same "server-hosted algo" mental model, but runs on agent runtime, not the strategy engine. |
| **Bybit Options App** (v3 prototype) | The skill's dashboard lives inside the AI Subaccount; the Options App's "My Strategies" page could cross-link. |

---

## Design choice: Chat Executor model

| Aspect | Description |
|---|---|
| Execution locus | AI agent runs inside a chat session |
| Authentication | User's Bybit API key (scope: Read + Trade Options; Withdraw disabled) |
| Environment | Determined by the user's key (mainnet / testnet / demo) |
| Confirmation flow | One CONFIRM at launch authorises the whole wheel; subsequent rounds report inside chat, non-blocking |
| Session | **Runs only while the chat session is active**; closing the chat stops execution |
| Status / Roll / Stop | **Triggered by user prompts in chat** |
| Position monitoring | Fetched inside the current turn; no background polling |
| Notifications | Reported inside chat; **no App push / email / webhook** |

The Python code in `Scripts/` is a reference implementation, usable directly by hosts that support Python. Hosts without Python can reimplement the signing logic in their native HTTP tooling.

---

## User experience (executor flow)

```
1. User opens an AI Subaccount in the Bybit App, deposits USDT,
   enables options, and issues an API key
   (Read + Trade Options; do NOT check Withdraw)
2. Share the skill with an AI assistant (Claude / ChatGPT / Cursor)
3. AI Step 1: check API key → connectivity ping /v5/account/wallet-balance
4. AI Step 2: explain the strategy with best / likely / worst framing
5. AI Step 3: show defaults — "OK, or tell me what to change"
6. AI Step 4: user CONFIRMs → same-turn market order + net-premium report
7. User closes chat → positions remain on Bybit and expire naturally
8. Next time the user returns and asks → AI fetches live API data and reports PnL
9. T-2d: user asks → AI computes and recommends a roll
10. User says stop → AI clarifies "stop opening new" vs "close everything"
```

---

## Core strategy logic (for internal PM / Eng alignment)

### Four modes

**A — Short Put loop (bullish / neutral-bullish)**
```
Sell OTM Put → not exercised: collect premium, open next round
             → exercised:     cash-settled USDT loss, equivalent to
                              "buying at the strike"
```

**B — Short Call loop (bearish / neutral-bearish)**
```
Sell OTM Call → not exercised: collect premium, open next round
              → exercised:     cash-settled USDT loss, equivalent to
                               "selling at the strike"
```

**C — Two-leg rotation (neutral / range-bound)**
```
Sell Put and Call sequentially (Put ↔ Call each round), same expiry, same baseCoin
→ collect premium on both sides across rounds
```

**D — AI Smart Switch (default)**
```
Before opening each round, compute Skew = Δ0.25 Put IV − Δ0.25 Call IV
  Skew > +5pp  → route to A (short Put)
  Skew < -5pp  → route to B (short Call)
  |Skew| ≤ 5pp → route to C (rotation)
```

### Delta bands per risk tier

| Tier | Delta target | Meaning |
|---|---|---|
| Conservative | 0.15–0.20 | Lower premium, lower exercise probability |
| Standard | 0.20–0.25 | Balanced |
| Aggressive | 0.25–0.35 | Higher premium, higher exercise probability |

### Safety mechanisms

| Condition | Action |
|---|---|
| IV%ile < 25 | Downgrade this round to Conservative |
| 24h drop > 8% | Pause new Put opens |
| 24h rise > 8% | Pause new Call opens |
| Drawdown > user-set cap | Flatten all + pause + wait for user CONFIRM-RESUME |
| Insufficient balance | Skip this round |

### Auto-Roll (modes A / B)

1–2 days before expiry, compare:
- Current contract's remaining mark value (cost to close)
- Same-Delta next-expiry premium

If roll premium > close cost → auto-roll without blocking.

---

## Strategy parameters

| Parameter | Description | Default | Exposed in Easy Mode? |
|---|---|---|---|
| `symbol` | Underlying — any baseCoin Bybit lists for options (as of 2026-07-15: BTC / ETH / SOL / XAUT / XRP / DOGE; read live from `instruments-info`) | BTC | Yes |
| `mode` | Strategy mode A / B / C / D (C = sequential Put ↔ Call rotation, not simultaneous dual-leg) | D | No (locked to D) |
| `riskTier` | Risk tier | standard | Yes |
| `orderQty` | Contracts per leg | symbol `minOrderQty` from `instruments-info` (reference values 2026-07-15: BTC 0.01 / ETH 0.1 / SOL 1 / XAUT 0.1 / XRP 10 / DOGE 100) | Yes |
| `positionRatio` | Optional percentage (agent translates to `orderQty`) | null | No |
| `preferredExpiryDays` | Preferred days to expiry | 7 | No |
| `targetAnnualYield` | Target annualised yield (affects position sizing) | null | No |
| `maxDrawdown` | Max drawdown cap; triggers auto-close | 0.20 | Yes |
| `skewDelta` | Delta point for Skew scan | 0.25 | No |
| `ivPercentileFloor` | IV%ile threshold that forces Conservative | 25 | No |
| `notificationChannel` | Notification channel | app_push | Yes |

See `Reference/strategy_spec.schema.json` for the full schema.

---

## Status report format (chat output, sole channel)

> This format aligns with the "Canonical status-report format" section in `SKILL.md`. The agent produces this shape whenever the user asks "how's my position?". The Chinese-mirrored reference template lives in `SKILL.md`; the agent renders in whichever language the user is writing in. There are no App-side buttons (the agent cannot draw buttons), so the original `[ Pause ]` / `[ Modify ]` / `[ Stop ]` buttons are replaced by **the chat commands the user should type**.

```
Options Wheel · BTC · AI Smart Switch (Mode D)
Status: Running · Round 1 · 1 leg open (short Put)

Current round
  Direction: short Put | Strike: $58,000 | Expiry: 2026-07-04 (T-3d)
  Quantity:  0.01 contracts
  Open net premium: $5.04 (gross $5.22 − open fee $0.18)
  Current mark:     $5.20 | Unrealised PnL: −$0.16
  Round Skew:       Put IV 47.3% vs Call IV 44.0% (+3.3pp Put premium)

Cumulative performance (since round 1, 18h elapsed)
  Net premium income: $5.04
  Net USDT PnL:       −$0.16 (0 ITM settlements so far)
  OTM expiry rate:    0/0 rounds (no settlements yet)
  [Annualised figures hidden until elapsed ≥ 30 days — short-sample
   annualisation is misleading]

Unfilled orders (if any)
  · ord …4F2A · BTC-3JUL26-58000-P-USDT · limit $620 · leaves 0.01/0.01
    Order age: 12 min; reply CONFIRM-A to re-quote

Next steps (please tell me clearly)
  · Check another leg / "how's the Call leg?"
  · Evaluate roll / "should I roll?" (only meaningful within T-2d)
  · Modify params / "switch to standard tier"
  · Stop: two flavours — "stop opening new" (cancel unfilled only)
                       or "close everything" (cancel unfilled +
                                              buy-to-close positions)
```

Notes for PM / stakeholder alignment:

- **No App buttons**. The original App-dashboard elements (`[ Pause ] [ Modify ] [ Stop & Close ]`) do not exist on this chat-agent path; there is no button channel.
- **Quantity is always displayed**. `Quantity: 0.01 contracts` is Bybit's minimum option lot; without it, the user cannot read the absolute PnL.
- **Annualised figures only shown when ≥ 30 days have elapsed**. Hidden in early rounds to avoid annualising an 18-hour sample into a misleading `+36% / +200%`.
- **Unfilled orders are listed separately**. `/v5/order/realtime` and `/v5/position/list` are two different APIs with two different "stop" flows; the UI must separate them.

---

## Notification design

**Sole channel = AI chat**. The agent has no push / email / App notification capability.

| Event | How the user is told |
|---|---|
| Order placed / filled | Same-turn reply |
| Market order partially filled / rejected | Same-turn message with next-step suggestion |
| Drawdown breached | Agent flags proactively inside chat + suggests stop / close |
| Expiry settlement | Reported when the user next returns and asks; agent pulls execution history |
| Auto-roll recommendation | Computed and offered when the user asks at T-2d |
| API errors | Reported honestly inside chat with a next-step suggestion |

Side effect: **if the user does not return to the chat, they receive no update**. This is the trade-off of the executor model. For 24/7 auto-run with active push notifications, use a server-side runtime (out of scope for this skill).

---

## Risk disclosures

1. Bybit options are USDT cash-settled; on exercise, the account bears the USDT difference — this is not physical delivery.
2. The strategy's primary income source is premium; exercise is a normal path and does not indicate strategy failure.
3. In a one-sided market, cumulative losses can exceed total premium collected.
4. The AI's parameters are based on historical patterns and do not guarantee future returns.
5. Under extreme market conditions (black swan), realised losses can exceed the historical backtest's maximum drawdown.
6. This tool does not constitute investment advice of any kind.

---

## User eligibility requirements

- AI Subaccount already opened
- Subaccount has passed the options knowledge test
- Subaccount has ≥ 500 USDT available balance
- Subaccount has options trading permission enabled

---

## Cross-BU collaboration opportunities

| BU | Touchpoint |
|---|---|
| **DBU — AI Subaccount Team** (Andy / Lance / Wanny) | The skill is a use case for AI Subaccount and doubles as a "why open an AI Sub" conversion narrative. |
| **DBU — Options App Team** | Vol Skew visualisation can reuse the IV / Skew module from the v3 prototype; the two flows can cross-link. |
| **DBU — Strategy Trading** | The Options Wheel dashboard styling aligns with TWAP / Chase for a consistent user experience. |
| **OBU** | The options knowledge test flow reuses OBU's existing compliance flow. |
| **Risk Team** | Max drawdown / trend-pause mechanisms need a Risk sign-off pass. |
| **App Notification Center** | Push payload schema aligned with the existing standard. |

---

## Version history

| Version | Date | Notes |
|---|---|---|
| 1.0.0 | 2026-07-15 | Initial public release. AI Subaccount + agent runtime architecture; four modes A / B / C / D with AI Smart Switch as default; continuous rounds (Step 3 CONFIRM authorises the full wheel); Host Capability Detection (session-persistent / scheduled-task / single-shot); auto-fire Auto-Roll; drawdown-triggered auto-close with `CONFIRM-RESUME`; supports any baseCoin Bybit lists for options (BTC / ETH / SOL / XAUT / XRP / DOGE as of release); secret-handling hardening (no key literals inside tool payloads). |
