# Options Wheel API Reference

All requests MUST include headers:

```
User-Agent: bybit-skill/1.3.0
X-Referer: bybit-skill
```

---

## Authentication

|Header|Value|
|---|---|
|X\-BAPI\-API\-KEY|API Key|
|X\-BAPI\-TIMESTAMP|Unix ms timestamp|
|X\-BAPI\-SIGN|HMAC\-SHA256 signature|
|X\-BAPI\-RECV\-WINDOW|5000|
|User\-Agent|bybit\-skill/2\.0\.5|
|X\-Referer|bybit\-skill|

Signature string:

- GET: `{timestamp}{apiKey}{recvWindow}{queryString}`

- POST: `{timestamp}{apiKey}{recvWindow}{jsonBody}`

---

## Market Data

### GET /v5/market/tickers

Get option tickers for Vol Skew calculation\.

```
GET /v5/market/tickers?category=option&baseCoin=BTC
```

⚠️ **Options batch query uses `baseCoin`, not `symbol`**\. Passing `symbol=BTC`
returns an empty list\. To query a single specific contract, use the full
contract name as `symbol` \(e\.g\. `symbol=BTC-3JUL26-57000-P-USDT`\)\.

Key response fields:

- `symbol` — Option contract name \(e\.g\., BTC\-04JUL26\-90000\-P\)

- `bid1Price` / `ask1Price` — Best bid/ask

- `markIv` — Mark implied volatility. **Decimal form**, annualised: e\.g\. `"0.5906"` means IV = 59\.06%\. Multiply by 100 when displaying as a percentage; do not multiply when feeding into pricing math\.

- `delta` — Option delta\. Put delta is **negative** \(e\.g\. `-0.18`\), Call delta is **positive** \(e\.g\. `0.22`\)\. When comparing against `skewDelta` (default 0\.25), take `abs(delta)` first\.

- `openInterest` — Open interest

### GET /v5/market/instruments\-info

Get available option contracts for contract selection\.

```
GET /v5/market/instruments-info?category=option&baseCoin=BTC&status=Trading&limit=500
```

⚠️ **Same `baseCoin` rule as tickers**\. Also pass `limit=500` and handle
`nextPageCursor` for pagination — BTC option contracts routinely exceed
the default limit and would be silently truncated otherwise\.

Key response fields:

- `symbol` — Full contract name \(e\.g\. `BTC-3JUL26-57000-P-USDT`\)

- `optionsType` — Put / Call \(**plural `s` — field is `optionsType`, not `optionType`**\)

- `deliveryTime` — Expiry timestamp \(ms\)

- `settleCoin` — Settlement coin \(USDT for the contracts this skill uses\)

- `lotSizeFilter.minOrderQty` / `qtyStep` — minimum size and step

- `priceFilter.tickSize` — minimum price increment

⚠️ **`instruments-info` does NOT return `strikePrice`**\. Parse the strike
from the symbol's 3rd dash-separated segment instead:
`BTC-3JUL26-57000-P-USDT` → strike = 57000\.

### GET /v5/market/orderbook

Get orderbook for mid\-price calculation\.

```
GET /v5/market/orderbook?category=option&symbol=BTC-3JUL26-57000-P-USDT&limit=5
```

Mid price calculation: `(best_bid + best_ask) / 2`

---

## Account

### GET /v5/user/query\-api

Preflight permission inspection — call this BEFORE the wallet balance
check\. Used to verify the supplied API key has the correct scope and
does NOT have Withdraw permission\.

```
GET /v5/user/query-api
```

Key response fields:

- `permissions.ContractTrade` — should contain `Order`, `Position` for trading
- `permissions.Options` — should contain `OptionsTrade`
- `permissions.Withdraw` — **MUST be empty / null** for this skill\.
  Bybit returns this as `list[str]`\. Treat the key as Withdraw\-enabled
  iff the list contains a non\-empty string \(e\.g\. `["Withdraw"]`\)\.
  `null`, missing field, `[]`, or `[""]` all mean Withdraw is OFF \—
  accept the key\. See `Skill.md` → "Step 1a" for the exact predicate
  to use\.
- `permissions.Wallet` — `AccountTransfer` is acceptable if needed; do NOT require
- `readOnly` — should be `0` \(read-write\); `1` \(read-only\) cannot place orders
- `ips` — list of IP allowlists; `[]` means no restriction

### GET /v5/account/wallet\-balance

Check available USDT balance before placing orders\.

```
GET /v5/account/wallet-balance?accountType=UNIFIED&coin=USDT
```

Key response fields:

- `totalEquity` — Total account equity

- `availableToWithdraw` — Available balance for new positions

- `walletBalance` — Wallet balance

- `locked` — Margin locked by open positions

- `totalMarginBalance` — Total margin balance

⚠️ **UTA quirk**: `availableToWithdraw` is an **empty string** when no
margin is currently locked\. Fall back to `walletBalance - locked` when
the field is empty\.

Usage: Verify the resolved available balance ≥ required margin before
each round\.

---

## Options Trading

### POST /v5/order/create — open a position (Sell)

Place a market sell order\. v2\.0 default uses market for same-turn fill
confirmation; limit is supported when a user explicitly requests it\.

```json
{
  "category": "option",
  "symbol": "BTC-3JUL26-57000-P-USDT",
  "side": "Sell",
  "orderType": "Market",
  "qty": "0.01",
  "orderLinkId": "wheel-btc-put-1782400000000",
  "reduceOnly": false
}
```

Required fields:

- `category`: Must be `option`

- `side`: `Sell` for opening a wheel leg

- `orderType`: `Market` \(default in v2\.0\) — fills in the same chat turn\. `Limit` is supported with an additional `price` field\.

- `qty`: Number of contracts as a string\. Use the contract's `lotSizeFilter.minOrderQty` (BTC: `0.01`) for a first-round safe size; **never default to `1`** (that is one full BTC underlying)\.

- `orderLinkId`: Unique identifier per order\. **Bybit caps `orderLinkId` at 36 characters** — the API returns `retCode 10001 "orderLinkId's length can not exceed 36"` if you exceed this. Do NOT embed the full contract symbol (which alone can be 22+ chars). Use a compact form: `wheel-<baseCoin-lower>-<put|call>-<ms>` (27 chars) or short-tags like `wheel-r<round>-c<c|p>-<ms>` (22 chars). Used by the agent to recognise its own orders in history\.

### POST /v5/order/create — close a position (Buy + reduceOnly)

Closing an open option short \(roll, stop, drawdown trip\) is a **separate
Sell→Buy market order with `reduceOnly: true`**, NOT a `/v5/order/cancel`\.

```json
{
  "category": "option",
  "symbol": "BTC-3JUL26-57000-P-USDT",
  "side": "Buy",
  "orderType": "Market",
  "qty": "0.01",
  "orderLinkId": "wheel-close-btc-put-1782400000000",
  "reduceOnly": true
}
```

### POST /v5/order/amend (limit-order refresh)

Refresh price (or qty) on an unfilled limit order\. Not used in the
default market-order path, but **required** for the "refresh unfilled
limit" flow when the user explicitly chose `orderType=Limit`\. See
Skill\.md → "Refreshing an unfilled limit order" for the user-facing
flow\.

```json
{
  "category": "option",
  "symbol": "BTC-3JUL26-57000-P-USDT",
  "orderId": "order_id_here",
  "price": "510"
}
```

Key behaviours:

- Amend preserves any partial fill \(`cumExecQty`\); cancel-and-replace
  would lose it\. Always prefer amend over cancel-and-replace for
  re-pricing\.
- `price` must respect `priceFilter.tickSize` — round before sending,
  else `retCode=10001`\.
- If the order has already filled or been cancelled by the time the
  amend request arrives, Bybit returns `retCode=110041`\. Pull
  `/v5/order/realtime` to find out which state it landed in\.
- Each amend in the user-facing flow is its own state change and
  requires a fresh `CONFIRM-A` per Rule 1 in `Skill.md`\.

### POST /v5/order/cancel

Cancel an open order\.

```json
{
  "category": "option",
  "symbol": "BTC-3JUL26-57000-P-USDT",
  "orderId": "order_id_here"
}
```

---

## Position Management

### GET /v5/position/list

Monitor open option positions\.

```
GET /v5/position/list?category=option&baseCoin=BTC
```

⚠️ **Same `baseCoin` rule as tickers and instruments\-info**\. Passing
`symbol=BTC` returns an empty list silently — the caller sees "no
position" right after a successful order placement and wonders why\.
For a SPECIFIC contract, pass the full contract symbol \(e\.g\.
`symbol=BTC-3JUL26-58000-P-USDT`\)\. This same rule applies to
`/v5/order/realtime` and `/v5/execution/list`\.

Key response fields:

- `symbol` — Contract name

- `side` — Sell \(for this strategy\)

- `size` — Position size

- `avgPrice` — Average entry price \(premium received\)

- `unrealisedPnl` — Unrealized P\&L

- `delta` — Current delta

- `markPrice` — Current mark price

- `liqPrice` — Liquidation price

### GET /v5/execution/list

Get trade history and settlement records\.

```
GET /v5/execution/list?category=option&baseCoin=BTC&limit=50
```

Key response fields:

- `execType` — Trade / Delivery \(settlement\)

- `execPrice` — Execution price

- `execQty` — Executed quantity

- `execFee` — Fee charged

- `closedSize` — Closed size \(for settlements\)

---

## Order Monitoring

### GET /v5/order/realtime

Check status of open orders\.

```
GET /v5/order/realtime?category=option&baseCoin=BTC&openOnly=1
```

Key response fields:

- `orderId` — Order ID

- `orderStatus` — New / PartiallyFilled / Filled / Cancelled

- `price` — Order price

- `qty` — Order quantity

- `leavesQty` — Remaining unfilled quantity

- `createdTime` — Order creation timestamp \(ms\)

---

## Vol Skew Calculation

To compute Δ0\.25 Put IV vs Δ0\.25 Call IV:

1. Fetch all option tickers for the symbol

2. Filter contracts with `delta` closest to 0\.25 \(Put\) and \-0\.25 \(Call\) for the nearest expiry

3. Read `markIv` for each

4. Skew = Put\_IV − Call\_IV \(in percentage points\)

```python
# Example: compute skew
put_iv = 0.68   # 68%
call_iv = 0.61  # 61%
skew = (put_iv - call_iv) * 100  # +7pp → recommend Sell Put
```

---

## IV Percentile Calculation

1. Fetch historical `markIv` for the ATM option over the past 30 days

2. Rank current IV against the historical distribution

3. `IV%ile = percentile_rank(current_iv, historical_ivs)`

```python
# Correct: rank of current IV within the historical distribution
from scipy.stats import percentileofscore
current_iv_percentile = percentileofscore(historical_ivs, current_iv, kind='rank')
# Returns e.g. 18.4 → current IV is at the 18th percentile of recent history

# WRONG (common mistake): this returns the value AT the 25th percentile,
# not the rank of the current IV:
#   np.percentile(historical_ivs, 25)  # ← this is the quantile value, not the rank
```

---

## Rate Limits

|Request Type|Minimum Interval|
|---|---|
|GET \(read\)|100ms|
|POST \(write\)|300ms|

On retCode=10006 \(rate limited\): wait random 500–1500ms, retry up to 3 times\.

---

## Common Error Codes

|retCode|Meaning|Resolution|
|---|---|---|
|0|Success|—|
|10001|Invalid parameter|Check symbol format, required fields|
|10003|Invalid API key|Verify key matches environment|
|10004|Signature error|Check timestamp sync, compact JSON|
|10006|Rate limited|Backoff 500–1500ms, retry|
|110004|Insufficient balance|Reduce qty or deposit|
|110007|Insufficient available balance|Cancel orders to free margin|
|110020|Too many active orders|Cancel some orders first|
|110041|Order already filled / cancelled (amend race)|Re-query `/v5/order/realtime` to see final state, report to user|

---

## Supported Symbols

|Symbol|Option Format Example|
|---|---|
|BTC|BTC\-04JUL26\-90000\-P|
|ETH|ETH\-04JUL26\-3000\-C|
|XAUT|XAUT\-04JUL26\-3200\-P|

Symbol format: `{BASE}-{DDMMMYY}-{STRIKE}-{P/C}`
