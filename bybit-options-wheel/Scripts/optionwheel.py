"""
========================================================================
REFERENCE IMPLEMENTATION — How to Make the API Calls for Options Wheel
========================================================================

This Python file demonstrates the Bybit v5 calls an AI agent needs to
make to execute Options Wheel: Vol Skew scan, contract selection, order
placement, position monitoring. The signing logic + endpoint quirks
(baseCoin filter, optionsType vs optionType, strike-from-symbol, etc.)
are all here.

How to use this file depends on the agent's host:

  • If your host can execute Python (Code Interpreter / shell access /
    Claude Code Bash tool / etc.), you may run this script against
    Bybit demo or testnet for development. For production, use the
    user's API key + their AI Subaccount.
  • If your host cannot execute Python, read this file as a reference
    for what HTTP calls to make. You can implement the same API
    sequence using whatever HTTP tooling your host provides.

Either way, follow the rules in Skill.md → "For AI Agents Receiving
This Skill Package":

  • Always start with Step 1: check for the user's API key
  • Always confirm the defaults (Step 3) before placing any order
  • Tag your orders with orderLinkId prefix "wheel-" so the user can
    identify them in their order history
  • Hold the API key in session memory only; never echo it back

========================================================================

Bybit Options Wheel Strategy (风火轮) — Reference Implementation
Depends on: optionwheel_bybit_client.OptionWheelClient

Strategy modes:
  A - Sell Put Loop         (bullish / neutral-bullish)
  B - Sell Call Loop        (bearish / neutral-bearish)
  C - Sequential Rotation   (neutral / range-bound; one leg at a time,
                             alternates Put↔Call each round)
  D - AI Smart Switch       (default; AI scans Vol Skew each round;
                             may sell both legs simultaneously when
                             |Skew| ≤ 5pp)

All API requests automatically include:
  User-Agent: bybit-skill/1.3.0
  X-Referer: bybit-skill
"""

import argparse
import json
import os
import sys
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from optionwheel_bybit_client import OptionWheelClient, print_error_hint

# ------------------------------------------------------------------ #
# Cross-session state (drawdown baseline) — see Skill.md "Cross-session state"
# ------------------------------------------------------------------ #

STATE_FILE = Path(__file__).resolve().parent.parent / ".wheel_state.json"


def load_state():
    """Return persisted state dict, or {} if missing/unreadable.

    Never store API key/secret here — per Skill.md Rule 2, those stay
    in the session env. This file is only for derived baselines
    (starting_equity, round counter, etc.).
    """
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [warn] could not read state file ({e}); starting fresh.")
    return {}


def save_state(state):
    """Persist baseline state. Best-effort; failures are non-fatal."""
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except OSError as e:
        print(f"  [warn] could not write state file: {e}")


def resolve_starting_equity(client, current_equity, subaccount_id=None, force_reset=False):
    """Per Skill.md priority order: session → file → ask → reset.

    For this CLI we collapse "session" + "file" (no persistent agent
    process), then fall through to console prompt.
    """
    if force_reset:
        print(f"  [reset] Using current equity ${current_equity:,.2f} as new baseline.")
        return current_equity
    state = load_state()
    if state.get("starting_equity") and (
        subaccount_id is None or state.get("subaccount_id") == subaccount_id
    ):
        baseline = float(state["starting_equity"])
        started = state.get("started_at", "?")
        print(f"  [resume] Loaded baseline ${baseline:,.2f} (started {started})")
        return baseline
    # First-time setup: snapshot current equity as baseline
    print(f"  [new] First session — snapshotting baseline = current equity ${current_equity:,.2f}")
    return current_equity

# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #

SKEW_THRESHOLD = 5.0          # pp; above = sell put, below = sell call
IV_LOW_PERCENTILE = 25        # IV%ile below this -> downgrade to conservative
TREND_PAUSE_THRESHOLD = 0.08  # 8% 24h move triggers pause
ORDER_REFRESH_MINUTES = 30    # only used in --limit refresh mode
ORDER_MAX_RETRIES = 3
LIMIT_FILL_POLL_SECONDS = 60  # how often to check fill status in --limit mode

# Risk tier delta targets
RISK_TIERS = {
    "conservative": (0.15, 0.20),
    "standard":     (0.20, 0.25),
    "aggressive":   (0.25, 0.35),
}


# ------------------------------------------------------------------ #
# Session-state IV history (rolling, warm-start for IV%ile)
# ------------------------------------------------------------------ #
# Bybit public API has no historical-IV endpoint, so we keep a rolling
# window of mark-IV samples in process memory. Cold start = unknown
# percentile (no downgrade); after ~30 samples we have a usable signal.
# For genuine 30-day percentile, the agent host should warm-start this
# from a persisted store (see Skill.md §"Cross-session state").
_IV_HISTORY = {"BTC": deque(maxlen=720), "ETH": deque(maxlen=720),
               "SOL": deque(maxlen=720), "XAUT": deque(maxlen=720)}


def _record_iv(symbol, atm_iv):
    if symbol in _IV_HISTORY and atm_iv > 0:
        _IV_HISTORY[symbol].append(float(atm_iv))


def compute_iv_percentile(symbol, current_iv):
    """Return IV percentile (0-100) of `current_iv` against the rolling
    in-session history for `symbol`. Returns None if fewer than 30
    samples — caller must treat as "unknown, do not downgrade".
    """
    hist = _IV_HISTORY.get(symbol)
    if not hist or len(hist) < 30 or current_iv <= 0:
        return None
    below = sum(1 for v in hist if v < current_iv)
    return 100.0 * below / len(hist)


# ------------------------------------------------------------------ #
# 24h price-change risk modulator (Skill.md trend pause)
# ------------------------------------------------------------------ #

_SPOT_SYMBOL = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "XAUT": "XAUTUSDT", "XRP": "XRPUSDT", "DOGE": "DOGEUSDT"}


def get_24h_price_change(client, symbol):
    """Return 24h price change as a fraction (e.g. -0.08 for -8%).

    Reads /v5/market/tickers?category=spot&symbol=<sym>USDT — the
    `price24hPcnt` field is already a fraction in Bybit v5. Returns
    None if the call fails so the caller can treat it as "unknown,
    don't pause".
    """
    spot = _SPOT_SYMBOL.get(symbol)
    if not spot:
        return None
    resp = client.get("/v5/market/tickers", {"category": "spot", "symbol": spot})
    if not resp or resp.get("retCode") != 0:
        return None
    rows = resp.get("result", {}).get("list", [])
    if not rows:
        return None
    try:
        return float(rows[0].get("price24hPcnt", "0") or 0)
    except (ValueError, TypeError):
        return None


def apply_risk_modulators(symbol, mode, risk_tier, directions, atm_iv, price_change_24h, dry_run=False):
    """Apply Skill.md §"Risk Modulators" rules. Returns (effective_risk_tier,
    effective_directions, notes[]).
    """
    notes = []
    eff_tier = risk_tier
    eff_directions = list(directions)

    if atm_iv is not None and atm_iv > 0:
        pct = compute_iv_percentile(symbol, atm_iv)
        if pct is not None and pct < IV_LOW_PERCENTILE and eff_tier != "conservative":
            notes.append(f"IV%ile={pct:.0f} < {IV_LOW_PERCENTILE} → downgrade to conservative for this round")
            eff_tier = "conservative"

    if price_change_24h is not None:
        if price_change_24h < -TREND_PAUSE_THRESHOLD and "Put" in eff_directions:
            notes.append(f"24h move {price_change_24h*100:+.1f}% < -{TREND_PAUSE_THRESHOLD*100:.0f}% → pause new Put opens")
            eff_directions = [d for d in eff_directions if d != "Put"]
        if price_change_24h > TREND_PAUSE_THRESHOLD and "Call" in eff_directions:
            notes.append(f"24h move {price_change_24h*100:+.1f}% > +{TREND_PAUSE_THRESHOLD*100:.0f}% → pause new Call opens")
            eff_directions = [d for d in eff_directions if d != "Call"]

    return eff_tier, eff_directions, notes


# ------------------------------------------------------------------ #
# Vol Skew helpers
# ------------------------------------------------------------------ #

def _parse_symbol(sym):
    """Parse 'BTC-27JUN26-69000-C-USDT' into (base, expiry_str, strike, type).
    Returns None if format unexpected.
    """
    parts = sym.split("-")
    if len(parts) < 4:
        return None
    return parts[0], parts[1], parts[2], parts[3]


def _expiry_to_ms(expiry_str):
    """Parse 'DDMMMYY' → unix ms (UTC 08:00 expiry, Bybit convention)."""
    months = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,
              "JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}
    try:
        from datetime import datetime, timezone
        day = int(expiry_str[:-5])
        mon = months[expiry_str[-5:-2]]
        yr = 2000 + int(expiry_str[-2:])
        return int(datetime(yr, mon, day, 8, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    except Exception:
        return None


def compute_vol_skew(client, symbol, skew_delta=0.25):
    """
    Compute Skew = D{skew_delta} Put IV - D{skew_delta} Call IV
    for the nearest expiry.
    Returns (put_iv, call_iv, skew_pp, expiry, tickers_by_symbol) or None on failure.
    """
    resp = client.get_option_tickers(symbol)
    if not resp or resp.get("retCode") != 0:
        return None

    tickers = resp["result"].get("list", [])
    by_expiry = {}
    tickers_by_symbol = {}
    for t in tickers:
        parsed = _parse_symbol(t.get("symbol", ""))
        if not parsed:
            continue
        _, expiry, _, opt_type = parsed
        if opt_type not in ("P", "C"):
            continue
        by_expiry.setdefault(expiry, []).append((opt_type, t))
        tickers_by_symbol[t["symbol"]] = t

    if not by_expiry:
        return None

    # Pick nearest expiry by parsed date, not lexicographic
    def expiry_sort_key(e):
        ms = _expiry_to_ms(e)
        return ms if ms is not None else 10**18
    nearest_expiry = sorted(by_expiry.keys(), key=expiry_sort_key)[0]
    contracts = by_expiry[nearest_expiry]

    put_candidates  = [(abs(abs(float(t.get("delta", 0) or 0)) - skew_delta), t) for ot, t in contracts if ot == "P"]
    call_candidates = [(abs(abs(float(t.get("delta", 0) or 0)) - skew_delta), t) for ot, t in contracts if ot == "C"]

    if not put_candidates or not call_candidates:
        return None

    put_ticker  = sorted(put_candidates,  key=lambda x: x[0])[0][1]
    call_ticker = sorted(call_candidates, key=lambda x: x[0])[0][1]

    put_iv  = float(put_ticker.get("markIv", 0) or 0)
    call_iv = float(call_ticker.get("markIv", 0) or 0)
    skew_pp = (put_iv - call_iv) * 100

    return put_iv, call_iv, skew_pp, nearest_expiry, tickers_by_symbol


def decide_direction(skew_pp, mode, prev_leg=None):
    """
    Mode D: AI Smart Switch based on skew.
    Mode C: Sequential rotation — alternates Put↔Call each round based
            on prev_leg. If prev_leg is None (first round), start with Put.
    Returns: 'Put', 'Call', or 'Both' (dual-leg, Mode D balanced only).

    NOTE: This Python reference honors SKILL.md Mode C semantics
    (sequential rotation) via prev_leg. Callers that don't pass prev_leg
    fall back to legacy "Both" behavior for Mode C — a known reference
    limitation; the AI-agent path (Skill.md) is the ground truth.
    """
    if mode in ("A",):
        return "Put"
    if mode in ("B",):
        return "Call"
    if mode in ("C",):
        if prev_leg == "Put":
            return "Call"
        if prev_leg == "Call":
            return "Put"
        return "Put"  # first round default
    # Mode D
    if skew_pp > SKEW_THRESHOLD:
        return "Put"
    if skew_pp < -SKEW_THRESHOLD:
        return "Call"
    return "Both"


# ------------------------------------------------------------------ #
# Contract selection
# ------------------------------------------------------------------ #

def select_contract(client, symbol, direction, risk_tier,
                    preferred_expiry_days=7, tickers_cache=None):
    """
    Select the best contract matching target delta and expiry.
    tickers_cache: dict[symbol → ticker] populated by compute_vol_skew (avoids re-fetching).
    Returns contract info dict or None.
    """
    resp = client.get_instruments(symbol)
    if not resp or resp.get("retCode") != 0:
        return None

    now_ms = int(time.time() * 1000)
    options_type = "Put" if direction == "Put" else "Call"
    type_char = "P" if direction == "Put" else "C"
    delta_lo, delta_hi = RISK_TIERS[risk_tier]
    target_delta = (delta_lo + delta_hi) / 2
    preferred_ms = preferred_expiry_days * 86400 * 1000

    # Build/use ticker cache. Fall back to fetching all tickers once.
    if tickers_cache is None:
        tresp = client.get_option_tickers(symbol)
        tickers_cache = {}
        if tresp and tresp.get("retCode") == 0:
            for t in tresp["result"].get("list", []):
                tickers_cache[t["symbol"]] = t

    candidates = []
    for inst in resp["result"].get("list", []):
        if inst.get("optionsType") != options_type:
            continue
        parsed = _parse_symbol(inst["symbol"])
        if not parsed or parsed[3] != type_char:
            continue
        try:
            strike = float(parsed[2])
        except (ValueError, TypeError):
            continue

        delivery_time = int(inst.get("deliveryTime", 0) or 0)
        days_to_expiry = (delivery_time - now_ms) / 86400000
        if days_to_expiry <= 1:
            continue

        t = tickers_cache.get(inst["symbol"])
        if not t:
            continue
        delta = abs(float(t.get("delta", 0) or 0))
        if not (delta_lo <= delta <= delta_hi):
            continue

        expiry_score = abs(delivery_time - now_ms - preferred_ms)
        delta_score  = abs(delta - target_delta)
        candidates.append({
            "symbol": inst["symbol"],
            "strike": strike,
            "delivery_time": delivery_time,
            "days_to_expiry": days_to_expiry,
            "delta": delta,
            "mark_iv": float(t.get("markIv", 0) or 0),
            "bid": float(t.get("bid1Price", 0) or 0),
            "ask": float(t.get("ask1Price", 0) or 0),
            "mark_price": float(t.get("markPrice", 0) or 0),
            "tick_size": float(inst.get("priceFilter", {}).get("tickSize", "0.5") or 0.5),
            "min_qty": float(inst.get("lotSizeFilter", {}).get("minOrderQty", "0.01") or 0.01),
            "qty_step": float(inst.get("lotSizeFilter", {}).get("qtyStep", "0.01") or 0.01),
            "expiry_score": expiry_score,
            "delta_score": delta_score,
        })

    if not candidates:
        return None
    return sorted(candidates, key=lambda x: (x["expiry_score"], x["delta_score"]))[0]


def mid_price(contract):
    """Mid of bid/ask. Falls back to markPrice if either side is missing (illiquid demo)."""
    bid = contract.get("bid", 0)
    ask = contract.get("ask", 0)
    if bid > 0 and ask > 0:
        raw = (bid + ask) / 2
    else:
        raw = contract.get("mark_price", 0) or max(bid, ask)
    tick = contract.get("tick_size", 0.5) or 0.5
    # Round to nearest tick
    return round(round(raw / tick) * tick, 8)


# ------------------------------------------------------------------ #
# Order execution
# ------------------------------------------------------------------ #

def place_market_sell(client, symbol, qty, contract, env_label, dry_run=False):
    """Place a market Sell on `contract`. Default path for Step 4 of
    Skill.md — fills in the same chat turn so we can report fill
    price + premium back to the user immediately.

    Returns (order_id, fill_price) or (None, None) on failure.
    In dry_run mode: prints what would be placed and returns
    ("DRY-RUN", mid_price(contract)) without hitting the API.
    """
    order_link_id = f"wheel-{symbol.lower()}-{contract['symbol'].split('-')[-1].lower()}-{int(time.time() * 1000)}"
    expected_mid = mid_price(contract)

    if dry_run:
        print(f"  [DRY-RUN] Would place Market Sell {contract['symbol']} qty={qty} (est. mid ${expected_mid})")
        return "DRY-RUN", expected_mid

    for attempt in range(1, ORDER_MAX_RETRIES + 1):
        resp = client.place_sell_option(contract["symbol"], qty, order_link_id)
        if resp and resp.get("retCode") == 0:
            order_id = resp["result"]["orderId"]
            # Pull execution detail for the fill price (Market orders settle instantly)
            time.sleep(0.5)
            exec_resp = client.get_executions(symbol, limit=5)
            fill_price = None
            if exec_resp and exec_resp.get("retCode") == 0:
                for ex in exec_resp["result"].get("list", []):
                    if ex.get("orderLinkId") == order_link_id:
                        fill_price = float(ex.get("execPrice", 0) or 0)
                        break
            print(f"  [{env_label}] Market Sell filled: {order_id} | {contract['symbol']} | price=${fill_price or expected_mid}")
            return order_id, (fill_price or expected_mid)
        ret_code = resp.get("retCode") if resp else -1
        print(f"  Order attempt #{attempt} failed: retCode={ret_code}")
        print_error_hint(ret_code)
        if ret_code == 10006:
            time.sleep(0.5 + attempt * 0.3)
        else:
            break  # non-rate-limit error — don't burn retries blindly

    print("  Market sell failed after retries.")
    return None, None


def place_limit_and_track(client, symbol, qty, contract, env_label, dry_run=False):
    """Limit-order variant — only used when the user explicitly asks
    for a limit (Skill.md "Refreshing an unfilled limit order").
    Polls in 1-minute intervals up to 5 minutes, then surfaces the
    choice to the user (refresh / wait / convert). Returns
    (order_id, status_or_price).
    """
    price = mid_price(contract)
    order_link_id = f"wheel-{symbol.lower()}-{contract['symbol'].split('-')[-1].lower()}-{int(time.time() * 1000)}"

    if dry_run:
        print(f"  [DRY-RUN] Would place Limit Sell {contract['symbol']} qty={qty} @ ${price}")
        return "DRY-RUN", price

    resp = client.place_sell_option(contract["symbol"], qty, order_link_id, price=price)
    if not resp or resp.get("retCode") != 0:
        ret_code = resp.get("retCode") if resp else -1
        print(f"  Limit order placement failed: retCode={ret_code}")
        print_error_hint(ret_code)
        return None, None
    order_id = resp["result"]["orderId"]
    print(f"  [{env_label}] Limit placed: {order_id} | {contract['symbol']} | @${price}")
    # Short poll — agent (chat) only stays around briefly.
    for _ in range(5):
        time.sleep(LIMIT_FILL_POLL_SECONDS)
        open_resp = client.get_open_orders(symbol)
        if open_resp and open_resp.get("retCode") == 0:
            still_open = any(o["orderId"] == order_id for o in open_resp["result"].get("list", []))
            if not still_open:
                print(f"  Limit {order_id} filled.")
                return order_id, "filled"
    print(f"  Limit {order_id} still unfilled after 5min. Surface refresh / wait / convert to user (CONFIRM-A/B/C).")
    return order_id, "unfilled"


# ------------------------------------------------------------------ #
# Auto-Roll evaluation
# ------------------------------------------------------------------ #

def evaluate_auto_roll(client, symbol, current_contract, risk_tier):
    """
    Called 1-2 days before expiry.
    Returns True if rolling is preferred over closing.

    Heuristic: roll if next-expiry premium received (selling new contract)
    EXCEEDS the cost of buying back the current short (its mark price).
    Both are quoted in USDT per contract — same unit, comparable.

    The previous version used `mark_iv` (IV in decimal form, e.g. 0.59)
    as the close cost, which is the wrong unit (volatility vs price).
    Fixed: pull the current contract's markPrice live from /v5/market/tickers.
    """
    days_left = current_contract.get("days_to_expiry", 0)
    if days_left > 2:
        return False

    direction = "Put" if "-P" in current_contract["symbol"] else "Call"
    next_contract = select_contract(client, symbol, direction, risk_tier, preferred_expiry_days=7)
    if not next_contract:
        return False

    # Fetch the CURRENT contract's live markPrice — that's our cost to
    # buy-to-close. Not mark_iv (volatility), not the stale field from
    # the snapshot when we entered.
    current_sym = current_contract["symbol"]
    ticker_resp = client.get(
        "/v5/market/tickers",
        {"category": "option", "symbol": current_sym},
    )
    close_cost = 0.0
    if ticker_resp and ticker_resp.get("retCode") == 0:
        tickers = ticker_resp["result"].get("list", [])
        if tickers:
            close_cost = float(tickers[0].get("markPrice", 0) or 0)

    next_premium = mid_price(next_contract)
    should_roll = next_premium > close_cost

    if should_roll:
        print(f"  Auto-Roll: next premium ({next_premium}) > buy-to-close cost ({close_cost:.2f}). Rolling.")
    else:
        print(f"  Auto-Roll: next premium ({next_premium}) <= buy-to-close cost ({close_cost:.2f}). Let it settle.")
    return should_roll


# ------------------------------------------------------------------ #
# Core strategy loop
# ------------------------------------------------------------------ #

def run_round(client, symbol, mode, risk_tier, order_qty,
              round_num, skew_delta=0.25, preferred_expiry_days=7,
              dry_run=False, use_limit=False, prev_leg=None):
    """Execute a single Options Wheel round. Returns result dict.

    dry_run=True: no order/cancel/amend calls hit Bybit. Skew/select/
    balance reads still happen — they're idempotent reads.
    use_limit=True: place GTC limits at mid + poll fill (matches the
    old behaviour, kept for users who explicitly ask for limits).
    Default = Market for same-turn fill confirmation per Skill.md.
    order_qty: contracts per leg. If None, resolves at execution time
    to the chosen contract's `min_qty` (safe starter default per
    SKILL.md §Position Sizing).
    """
    env_label = client._env_label()
    mode_tag = " [DRY-RUN]" if dry_run else ""
    print(f"\n[Round {round_num}{mode_tag}] Starting Options Wheel round...")

    # Step 1: Vol Skew scan
    skew_result = compute_vol_skew(client, symbol, skew_delta)
    put_iv, call_iv, skew_pp, expiry, tickers_cache = 0, 0, 0, "N/A", None
    if skew_result:
        put_iv, call_iv, skew_pp, expiry, tickers_cache = skew_result
        print(f"  Vol Skew: Put IV={put_iv*100:.1f}% | Call IV={call_iv*100:.1f}% | Skew={skew_pp:+.1f}pp | Nearest expiry: {expiry}")
        # Record ATM IV (average of put/call) into rolling history for IV%ile
        _record_iv(symbol, (put_iv + call_iv) / 2)
    else:
        print("  WARNING: Vol Skew scan failed. Defaulting to neutral (Dual-Leg).")

    # Step 2: Risk modulators — IV%ile + 24h trend pause
    price_change_24h = get_24h_price_change(client, symbol)
    initial_direction = decide_direction(skew_pp, mode, prev_leg=prev_leg)
    initial_dirs = ["Put", "Call"] if initial_direction == "Both" else [initial_direction]
    eff_tier, eff_directions, mod_notes = apply_risk_modulators(
        symbol, mode, risk_tier, initial_dirs,
        atm_iv=(put_iv + call_iv) / 2 if put_iv and call_iv else None,
        price_change_24h=price_change_24h,
        dry_run=dry_run,
    )
    for note in mod_notes:
        print(f"  Risk modulator: {note}")
    if not eff_directions:
        print("  All directions paused by trend filter. Skipping round.")
        return {"status": "skipped", "reason": "trend_pause"}

    # Step 3: Check balance (basic floor — per-round margin check happens
    # after contract selection when we know strike × qty)
    available_usdt = client.get_usdt_available()
    MIN_ROUND_USDT = 100.0
    if available_usdt < MIN_ROUND_USDT:
        print(f"  Insufficient balance ({available_usdt:.2f} USDT < {MIN_ROUND_USDT}). Skipping round.")
        return {"status": "skipped", "reason": "insufficient_balance"}

    placed_orders = []
    for dir_ in eff_directions:
        contract = select_contract(client, symbol, dir_, eff_tier, preferred_expiry_days, tickers_cache=tickers_cache)
        if not contract:
            print(f"  No suitable {dir_} contract found for {symbol}. Skipping direction.")
            continue

        # Resolve orderQty: user override wins; else fall back to symbol's
        # min lot from instruments-info (safe starter per SKILL.md).
        min_qty = contract.get("min_qty", 0.01)
        if order_qty is None:
            qty = min_qty
        elif order_qty < min_qty:
            print(f"  Requested qty {order_qty} < minOrderQty {min_qty} for {contract['symbol']}. Using min lot.")
            qty = min_qty
        else:
            qty = order_qty
        premium_mid = mid_price(contract)                # per-contract mid price (USDT)
        gross_premium = premium_mid * qty                # what the user actually collects on fill
        # Yield expressed against capital at risk.
        # Sell Put: max loss = strike × qty (if underlying → 0); use as capital denominator.
        # Sell Call: theoretical max loss is unbounded — use strike × qty as a notional
        #            proxy so the yield print stays interpretable. The Risk note below +
        #            Skill.md defaults card call out the unbounded upside separately.
        capital_at_risk = contract["strike"] * qty
        yield_hold_pct = (gross_premium / capital_at_risk * 100) if capital_at_risk > 0 else 0
        annualised_pct_gross = yield_hold_pct * (365 / max(contract["days_to_expiry"], 1))

        # AI Decision Summary
        print(f"\n  === Round {round_num} AI Decision ===")
        print(f"  Recommendation: Sell {dir_} ({symbol}, Delta~{contract['delta']:.2f}, expiry {contract['days_to_expiry']:.0f}d)")
        print(f"  Put IV: {put_iv*100:.1f}% | Call IV: {call_iv*100:.1f}% | Skew: {skew_pp:+.1f}pp")
        print(f"  Contract: {contract['symbol']} | Strike: {contract['strike']}")
        print(f"  Expected gross premium: ${gross_premium:.2f} (mid ${premium_mid:.2f} × {qty} contracts)")
        print(f"    Hold yield: {yield_hold_pct:.2f}% over {contract['days_to_expiry']:.0f}d  |  Linear annualised: ~{annualised_pct_gross:.0f}% GROSS")
        print(f"    Note: excludes taker fees + ITM losses; historical NET on Δ0.25 dual-leg ≈ 4-6% (see Backtest/REPORT.md)")
        print(f"  Risk note: {dir_} seller, strike {contract['strike']}, {contract['days_to_expiry']:.0f}d buffer")

        # Step 5: Confirm and place order
        summary = {
            "Action":    f"Sell {dir_}",
            "Symbol":    contract["symbol"],
            "Qty":       f"{qty} contract",
            "Strike":    contract["strike"],
            "Expiry":    f"{contract['days_to_expiry']:.0f} days",
            "OrderType": "Limit" if use_limit else "Market",
            "Premium":   f"${gross_premium:.2f} gross (~{annualised_pct_gross:.0f}% ann. GROSS; NET usually 4-6%)",
        }
        if dry_run:
            print(f"  [DRY-RUN] Skipping CONFIRM gate (read-only run).")
        elif not client.confirm_operation(summary):
            print("  Order cancelled by user.")
            continue

        if use_limit:
            order_id, fill_or_status = place_limit_and_track(client, symbol, qty, contract, env_label, dry_run=dry_run)
        else:
            order_id, fill_or_status = place_market_sell(client, symbol, qty, contract, env_label, dry_run=dry_run)
        if order_id:
            placed_orders.append({
                "order_id": order_id,
                "symbol": contract["symbol"],
                "direction": dir_,
                "strike": contract["strike"],
                "premium": premium_mid,   # per-contract mid at open (USDT)
                "gross_premium": gross_premium,
                "fill_price": fill_or_status if isinstance(fill_or_status, (int, float)) else None,
                "delivery_time": contract["delivery_time"],
                "days_to_expiry": contract["days_to_expiry"],
                "qty": qty,
            })

    return {"status": "ok", "round": round_num, "orders": placed_orders}


def monitor_and_settle(client, symbol, positions, risk_tier):
    """Monitor positions until expiry, evaluating auto-roll near expiry."""
    while positions:
        time.sleep(3600)  # Check every hour
        pos_resp = client.get_positions(symbol)
        if not pos_resp or pos_resp.get("retCode") != 0:
            continue

        active = {p["symbol"]: p for p in pos_resp["result"].get("list", [])}
        settled = []
        for pos in positions:
            sym = pos["symbol"]
            if sym not in active:
                # Settled
                exec_resp = client.get_executions(symbol, limit=10)
                print(f"  Position {sym} settled.")
                settled.append(pos)
            else:
                # Near expiry auto-roll check
                days_left = (pos["delivery_time"] - int(time.time() * 1000)) / 86400000
                if days_left <= 2:
                    should_roll = evaluate_auto_roll(client, symbol, {
                        **pos, "days_to_expiry": days_left
                    }, risk_tier)
                    if should_roll:
                        # Close current and open next (simplified: just notify)
                        print(f"  Auto-roll triggered for {sym}. Opening next round.")

        for s in settled:
            positions.remove(s)


# ------------------------------------------------------------------ #
# Max drawdown protection
# ------------------------------------------------------------------ #

def check_drawdown(client, initial_equity, max_drawdown):
    """Returns True if drawdown limit exceeded."""
    if max_drawdown is None:
        return False
    resp = client.get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
    if not resp or resp.get("retCode") != 0:
        return False
    equity_str = resp["result"].get("list", [{}])[0].get("totalEquity", str(initial_equity))
    current_equity = float(equity_str)
    drawdown = (initial_equity - current_equity) / initial_equity
    if drawdown >= max_drawdown:
        print(f"  Max drawdown reached ({drawdown*100:.1f}%). Pausing strategy.")
        return True
    return False


# ------------------------------------------------------------------ #
# Main entry
# ------------------------------------------------------------------ #

def main():
    parser = argparse.ArgumentParser(description="Bybit Options Wheel Strategy (风火轮)")
    parser.add_argument("--symbol",         default="BTC",      help="Any Bybit-listed options baseCoin (as of 2026-07-15: BTC / ETH / SOL / XAUT / XRP / DOGE)")
    parser.add_argument("--mode",           default="D",        choices=["A","B","C","D"], help="Strategy mode (D=AI Smart Switch)")
    parser.add_argument("--risk-tier",      default="standard", choices=list(RISK_TIERS),   help="conservative / standard / aggressive")
    parser.add_argument("--order-qty",      type=float, default=None, help="Contracts per leg. Defaults to the symbol's lotSizeFilter.minOrderQty (read live from instruments-info; reference values 2026-07-15: BTC 0.01 / ETH 0.1 / SOL 1 / XAUT 0.1 / XRP 10 / DOGE 100). Override only if you specifically want a larger size.")
    parser.add_argument("--skew-delta",     type=float, default=0.25, help="Delta level for Vol Skew scan (default 0.25, user-configurable)")
    parser.add_argument("--expiry-days",    type=int,   default=7,   help="Preferred expiry in days (default 7)")
    parser.add_argument("--max-drawdown",   type=float, default=0.20, help="Max drawdown limit as fraction (default 0.20 = 20%%, user-configurable)")
    parser.add_argument("--rounds",         type=int,   default=0,   help="Max rounds to run (0 = unlimited)")
    parser.add_argument("--testnet",        action="store_true",     help="Use testnet API")
    parser.add_argument("--demo",           action="store_true",     help="Use Bybit Demo Trading API (api-demo.bybit.com)")
    parser.add_argument("--debug",          action="store_true",     help="True dry-run: read-only API calls only (no order/amend/cancel hits Bybit)")
    parser.add_argument("--limit",          action="store_true",     help="Use Limit orders instead of Market (only if user explicitly wants limits)")
    parser.add_argument("--reset-baseline", action="store_true",     help="Discard persisted drawdown baseline; use today's equity as new baseline")
    args = parser.parse_args()

    if args.testnet and args.demo:
        print("ERROR: --testnet and --demo are mutually exclusive.")
        sys.exit(1)
    # --debug is now a true read-only dry-run — it composes with any env
    # (mainnet/testnet/demo). Read endpoints still hit the real API so
    # vol skew, contract selection, balance preflight are realistic.

    env_override = "testnet" if args.testnet else ("demo" if args.demo else None)
    client = OptionWheelClient(env_override=env_override)
    # In true dry-run mode we still verify credentials (read-only) so the
    # user sees the masked key + balance preflight pass. Only order
    # placement (POST /v5/order/*) is skipped.
    client.verify_credentials()
    if args.debug:
        print("[DEBUG MODE] True dry-run: read-only API calls only. No orders will hit Bybit.")

    # Get current equity and resolve drawdown baseline (cross-session)
    eq_resp = client.get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
    current_equity = float(
        (eq_resp or {}).get("result", {}).get("list", [{}])[0].get("totalEquity", "10000")
    )
    initial_equity = resolve_starting_equity(client, current_equity, force_reset=args.reset_baseline)
    # Persist for next session (best-effort)
    if not args.debug:
        save_state({
            "starting_equity": initial_equity,
            "started_at": load_state().get("started_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "max_drawdown": args.max_drawdown,
            "symbol": args.symbol,
            "mode": args.mode,
        })

    qty_label = f"{args.order_qty}" if args.order_qty is not None else "auto (symbol min lot)"
    print(f"\nOptions Wheel Strategy Starting")
    print(f"  Symbol: {args.symbol} | Mode: {args.mode} | Risk: {args.risk_tier}")
    print(f"  Order Qty: {qty_label} | Skew Delta: {args.skew_delta}")
    print(f"  Max Drawdown: {args.max_drawdown*100:.0f}% | Expiry Pref: {args.expiry_days}d")
    print(f"  Order type: {'Limit (poll for fill)' if args.limit else 'Market (instant fill)'}")

    round_num = 0
    cumulative_pnl = 0.0
    last_leg = None  # Mode C sequential rotation memory

    while True:
        round_num += 1
        if args.rounds > 0 and round_num > args.rounds:
            print(f"  Reached max rounds ({args.rounds}). Stopping.")
            break

        # Drawdown check (skip in dry-run so we can preview the round)
        if not args.debug and check_drawdown(client, initial_equity, args.max_drawdown):
            print("  Strategy paused. Require manual restart.")
            break

        result = run_round(
            client, args.symbol, args.mode, args.risk_tier,
            args.order_qty, round_num,
            skew_delta=args.skew_delta,
            preferred_expiry_days=args.expiry_days,
            dry_run=args.debug,
            use_limit=args.limit,
            prev_leg=last_leg,
        )
        # For Mode C: remember which side we sold so next round flips
        if args.mode == "C" and result.get("status") == "ok":
            for order in result.get("orders", []):
                side = order.get("direction")
                if side in ("Put", "Call"):
                    last_leg = side

        if result["status"] == "skipped":
            if args.debug:
                print("  [DEBUG] Round skipped. Exiting.")
                break
            print("  Round skipped. Retrying in 1 hour.")
            time.sleep(3600)
            continue

        positions = result.get("orders", [])
        if args.debug:
            print(f"  [DEBUG] Dry-run round complete. Would have placed {len(positions)} order(s). Exiting.")
            break
        if positions:
            monitor_and_settle(client, args.symbol, positions, args.risk_tier)

        print(f"\n  Round {round_num} complete. Starting next round after settlement.")


if __name__ == "__main__":
    main()
