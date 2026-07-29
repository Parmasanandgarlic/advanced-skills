"""
========================================================================
REFERENCE IMPLEMENTATION — HTTP signing + endpoint patterns for Options Wheel
========================================================================

Bybit v5 HMAC-SHA256 signing logic, environment routing
(mainnet / testnet / demo), wallet balance handling with the UTA
empty-availableToWithdraw quirk, etc.

If your host supports Python, you can use this client directly. If
not, port the signing logic to your host's HTTP tooling — the key
formulas are in _sign() and the mandatory headers in MANDATORY_HEADERS.

Holds the API key + secret in process memory only. Do not log them.

========================================================================

Bybit Options Wheel API Client (reference) with HMAC-SHA256 authentication.
All requests include mandatory headers:
  User-Agent: bybit-skill/1.3.0
  X-Referer: bybit-skill
"""

import os
import sys
import time
import hmac
import hashlib
import json
from urllib.parse import urlencode

import requests

MAINNET_URL = "https://api.bybit.com"
TESTNET_URL = "https://api-testnet.bybit.com"
DEMO_URL = "https://api-demo.bybit.com"
RECV_WINDOW = "5000"
SKILL_VERSION = "1.3.0"

MANDATORY_HEADERS = {
    "User-Agent": f"bybit-skill/{SKILL_VERSION}",
    "X-Referer": "bybit-skill",
}


def has_withdraw_permission(permissions):
    """Return True iff the API key's permissions dict says Withdraw is
    enabled. Matches the predicate in Skill.md → "Step 1a" exactly:

      - True / non-empty "Withdraw" string / list containing a
        non-empty string → enabled
      - None / [] / [""] / missing field → not enabled
    """
    w = (permissions or {}).get("Withdraw")
    if w is True:
        return True
    if isinstance(w, str):
        return bool(w.strip())
    if isinstance(w, list):
        return any(isinstance(x, str) and x.strip() for x in w)
    return False


def mask_secret(value):
    """Mask an API key/secret for display. Shows first4…last4; secrets
    that are too short to mask safely collapse to `***`.

    Use this for ANY chat / log / debug surface where you would
    otherwise show a raw credential. The secret (BYBIT_API_SECRET)
    should never reach a display surface at all — refuse and explain
    it stays in the session env.
    """
    if not value or not isinstance(value, str):
        return "***"
    if len(value) < 12:
        return "***"
    return f"{value[:4]}…{value[-4:]}"


class OptionWheelClient:
    """Bybit API client for Options Wheel strategy."""

    def __init__(self, env_override=None):
        self.api_key = os.environ.get("BYBIT_API_KEY", "")
        self.api_secret = os.environ.get("BYBIT_API_SECRET", "")
        if env_override:
            self.env = env_override.lower()
        else:
            self.env = os.environ.get("BYBIT_ENV", "mainnet").lower()
        if self.env == "testnet":
            self.base_url = TESTNET_URL
        elif self.env == "demo":
            self.base_url = DEMO_URL
        else:
            self.base_url = MAINNET_URL
        self._last_get_time = 0
        self._last_post_time = 0

    # Auth

    def verify_credentials(self):
        if not self.api_key or not self.api_secret:
            print("ERROR: BYBIT_API_KEY and BYBIT_API_SECRET are required.")
            sys.exit(1)
        env_label = self._env_label()
        print(f"[{env_label}] Verifying API connection...")
        time_resp = self.get("/v5/market/time")
        if time_resp is None:
            print("ERROR: Failed to connect to Bybit API.")
            sys.exit(1)
        server_time = int(time_resp["result"]["timeSecond"])
        if abs(server_time - int(time.time())) > 5:
            print("WARNING: Clock drift detected. Please sync your system clock.")
            sys.exit(1)
        # Step 1a — Withdraw permission gate (Skill.md security rule).
        # Demo accounts often skip query-api entirely; treat missing
        # endpoint as a soft warn, not a hard fail.
        api_resp = self.get("/v5/user/query-api")
        if api_resp and api_resp.get("retCode") == 0:
            perms = api_resp.get("result", {}).get("permissions", {}) or {}
            if has_withdraw_permission(perms):
                print("ERROR: Your API key has Withdraw permission enabled.")
                print("       Options Wheel only needs Read + Trade. Regenerate the key")
                print("       with Withdraw unchecked and try again.")
                sys.exit(1)
        else:
            ret_code = api_resp.get("retCode") if api_resp else "N/A"
            print(f"  [warn] /v5/user/query-api unavailable (retCode={ret_code}); skipping Withdraw preflight. OK on demo.")
        balance_resp = self.get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        if not balance_resp or balance_resp.get("retCode") != 0:
            ret_code = balance_resp.get("retCode") if balance_resp else "N/A"
            print(f"ERROR: API verification failed. retCode={ret_code}")
            sys.exit(1)
        coins = balance_resp["result"].get("list", [{}])[0].get("coin", [])
        usdt = next((c.get("walletBalance", "0") for c in coins if c.get("coin") == "USDT"), "0")
        equity = balance_resp["result"].get("list", [{}])[0].get("totalEquity", "?")
        print(f"  Connected [{env_label}] | Key: {mask_secret(self.api_key)} | USDT: {usdt} | Total Equity: {equity}")
        return True

    def _env_label(self):
        return {"testnet": "TESTNET", "demo": "DEMO"}.get(self.env, "MAINNET")

    def request_demo_funds(self, coin="USDT", amount="10000"):
        """Demo-only: request virtual funds. Ref: POST /v5/account/demo-apply-money"""
        if self.env != "demo":
            print("request_demo_funds is only valid on demo environment.")
            return None
        return self.post("/v5/account/demo-apply-money", {
            "adjustType": 0,
            "utaDemoApplyMoney": [{"coin": coin, "amountStr": str(amount)}],
        })

    # Internals

    def _sign(self, timestamp, params_str):
        param_str = f"{timestamp}{self.api_key}{RECV_WINDOW}{params_str}"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            param_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _rate_limit(self, method):
        now = time.time()
        if method == "GET":
            elapsed = now - self._last_get_time
            if elapsed < 0.1:
                time.sleep(0.1 - elapsed)
            self._last_get_time = time.time()
        else:
            elapsed = now - self._last_post_time
            if elapsed < 0.3:
                time.sleep(0.3 - elapsed)
            self._last_post_time = time.time()

    # HTTP

    def get(self, endpoint, params=None):
        self._rate_limit("GET")
        timestamp = str(int(time.time() * 1000))
        query_string = urlencode(params) if params else ""
        sign = self._sign(timestamp, query_string)
        headers = {
            **MANDATORY_HEADERS,
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": sign,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
        }
        url = f"{self.base_url}{endpoint}"
        if query_string:
            url += f"?{query_string}"
        try:
            return requests.get(url, headers=headers, timeout=10).json()
        except Exception as e:
            print(f"Request error: {e}")
            return None

    def post(self, endpoint, body=None):
        self._rate_limit("POST")
        timestamp = str(int(time.time() * 1000))
        json_body = json.dumps(body, separators=(",", ":")) if body else ""
        sign = self._sign(timestamp, json_body)
        headers = {
            **MANDATORY_HEADERS,
            "Content-Type": "application/json",
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": sign,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
        }
        try:
            return requests.post(
                f"{self.base_url}{endpoint}", headers=headers, data=json_body, timeout=10
            ).json()
        except Exception as e:
            print(f"Request error: {e}")
            return None

    # Market data

    def get_option_tickers(self, symbol):
        """Fetch all option tickers for a base coin (BTC / ETH / SOL ...).
        Bybit options use baseCoin filter, not symbol.
        Key fields: symbol, bid1Price, ask1Price, markIv, delta, openInterest, underlyingPrice
        Ref: GET /v5/market/tickers
        """
        return self.get("/v5/market/tickers", {"category": "option", "baseCoin": symbol})

    def get_instruments(self, symbol):
        """List available option contracts for a base coin.
        Key fields: symbol, optionsType (Put/Call), deliveryTime, settleCoin
        Note: instruments-info does NOT return strikePrice; parse from symbol.
        Ref: GET /v5/market/instruments-info
        """
        return self.get("/v5/market/instruments-info", {
            "category": "option", "baseCoin": symbol, "status": "Trading"
        })

    def get_orderbook(self, symbol, limit=5):
        """Fetch orderbook for mid-price calculation.
        Mid price = (best_bid + best_ask) / 2
        Ref: GET /v5/market/orderbook
        """
        return self.get("/v5/market/orderbook", {
            "category": "option", "symbol": symbol, "limit": limit
        })

    # Account

    def get_usdt_available(self):
        """Return USDT available for new positions (margin check before each round).
        Ref: GET /v5/account/wallet-balance
        On UTA, availableToWithdraw is empty when no margin is locked;
        fall back to walletBalance - locked.
        """
        resp = self.get("/v5/account/wallet-balance", {"accountType": "UNIFIED", "coin": "USDT"})
        if not resp or resp.get("retCode") != 0:
            return 0.0
        coins = resp["result"].get("list", [{}])[0].get("coin", [])
        for c in coins:
            if c.get("coin") == "USDT":
                atw = c.get("availableToWithdraw", "") or ""
                if atw.strip():
                    return float(atw)
                wallet = float(c.get("walletBalance", "0") or 0)
                locked = float(c.get("locked", "0") or 0)
                return max(0.0, wallet - locked)
        return 0.0

    # Orders

    def place_sell_option(self, symbol, qty, order_link_id, price=None):
        """Place a Sell order on an option contract.

        Default = Market order (matches Skill.md "Step 4" spec — fills
        in the same chat turn so the agent can report fill price +
        premium back to the user immediately).

        Pass `price=<float>` to switch to a GTC Limit order at that
        price. The agent only takes this path when the user
        explicitly requests a limit (see Skill.md "Refreshing an
        unfilled limit order").

        order_link_id format: wheel-{symbol-lowercase}-{put|call}-{ts}
        Ref: POST /v5/order/create
        """
        body = {
            "category": "option",
            "symbol": symbol,
            "side": "Sell",
            "qty": str(qty),
            "orderLinkId": order_link_id,
            "reduceOnly": False,
        }
        if price is None:
            body["orderType"] = "Market"
        else:
            body["orderType"] = "Limit"
            body["price"] = str(price)
            body["timeInForce"] = "GTC"
        return self.post("/v5/order/create", body)

    def buy_to_close(self, symbol, qty, order_link_id, price=None):
        """Buy-to-close an existing short option position (reduceOnly).

        Used for roll, manual close-all, and drawdown-trip auto-close.
        Distinct from /v5/order/cancel — that's for unfilled orders;
        this is for filled positions. See Skill.md §Step 5.
        """
        body = {
            "category": "option",
            "symbol": symbol,
            "side": "Buy",
            "qty": str(qty),
            "orderLinkId": order_link_id,
            "reduceOnly": True,
        }
        if price is None:
            body["orderType"] = "Market"
        else:
            body["orderType"] = "Limit"
            body["price"] = str(price)
            body["timeInForce"] = "GTC"
        return self.post("/v5/order/create", body)

    def amend_order(self, symbol, order_id, new_price):
        """Refresh order price (call after 30 min unfilled).
        Ref: POST /v5/order/amend
        """
        return self.post("/v5/order/amend", {
            "category": "option",
            "symbol": symbol,
            "orderId": order_id,
            "price": str(new_price),
        })

    def cancel_order(self, symbol, order_id):
        """Cancel an open order. Ref: POST /v5/order/cancel"""
        return self.post("/v5/order/cancel", {
            "category": "option", "symbol": symbol, "orderId": order_id,
        })

    def get_open_orders(self, symbol):
        """List open orders. Same baseCoin/symbol heuristic as
        get_positions — options batch needs baseCoin.

        Ref: GET /v5/order/realtime
        """
        params = {"category": "option", "openOnly": 1}
        if "-" in symbol:
            params["symbol"] = symbol
        else:
            params["baseCoin"] = symbol
        return self.get("/v5/order/realtime", params)

    # Positions

    def get_positions(self, symbol):
        """List open positions for a base coin (BTC / ETH / XAUT).

        IMPORTANT: same quirk as option tickers — options batch query
        uses `baseCoin` not `symbol`. Passing `symbol="BTC"` silently
        returns an empty list (caller wonders why position isn't
        showing). Always pass baseCoin here.

        For a single specific contract, pass the full contract symbol
        as `symbol` instead (e.g. "BTC-3JUL26-58000-P-USDT").

        Ref: GET /v5/position/list
        """
        # Heuristic: full contract symbols contain dashes; bare base
        # coins like "BTC" don't. Route accordingly.
        if "-" in symbol:
            return self.get("/v5/position/list", {"category": "option", "symbol": symbol})
        return self.get("/v5/position/list", {"category": "option", "baseCoin": symbol})

    def get_executions(self, symbol, limit=50):
        """Trade history and settlement records. Same baseCoin/symbol
        heuristic as get_positions.

        Ref: GET /v5/execution/list
        """
        params = {"category": "option", "limit": limit}
        if "-" in symbol:
            params["symbol"] = symbol
        else:
            params["baseCoin"] = symbol
        return self.get("/v5/execution/list", params)

    # Confirmation

    def confirm_operation(self, summary, batch=False):
        """Print confirmation card and require strict CONFIRM on mainnet.

        Per Skill.md Rule 1: literal `CONFIRM` only — case-sensitive,
        exact match. Synonyms (`ok`, `yes`, `confirm`, `好`, `确认`,
        etc.) bounce with a reminder, then re-prompt.

        batch=True: this is a single intent with multiple coordinated
        sub-actions (close-all, batch-roll). Accept `CONFIRM-ALL` as
        the strict keyword instead of `CONFIRM`. See Skill.md Rule 1
        → "Batch exception".
        """
        keyword = "CONFIRM-ALL" if batch else "CONFIRM"
        env_label = self._env_label()
        print("\n" + "=" * 50)
        print(f"[{env_label}] Options Wheel Operation" + (" (BATCH)" if batch else ""))
        print("-" * 50)
        for k, v in summary.items():
            if isinstance(v, list):
                print(f"  {k}:")
                for item in v:
                    print(f"    · {item}")
            else:
                print(f"  {k}: {v}")
        print("-" * 50)
        if self.env in ("testnet", "demo"):
            print(f"({env_label} — executing without confirmation)")
            return True
        # Mainnet: strict CONFIRM, up to 3 attempts.
        prompt = f'Type {keyword} (uppercase, exact) to execute, anything else to abort: > '
        for attempt in range(3):
            reply = input(prompt).strip()
            if reply == keyword:
                return True
            if reply == "":
                print("  Aborted (empty reply).")
                return False
            print(f'  "{reply}" is not {keyword}. Type the literal string {keyword} (uppercase) or press Enter to abort.')
        print("  Aborted (3 invalid attempts).")
        return False


# Error code hints
ERROR_HINTS = {
    10001: "Invalid parameter — check symbol format and required fields.",
    10003: "Invalid API key — verify key matches environment.",
    10004: "Signature error — check timestamp sync, use compact JSON.",
    10006: "Rate limited — backoff 500-1500ms, retry up to 3 times.",
    110004: "Insufficient balance — reduce qty or deposit.",
    110007: "Insufficient available balance — cancel orders to free margin.",
    110020: "Too many active orders — cancel some first.",
}


def print_error_hint(ret_code):
    hint = ERROR_HINTS.get(ret_code)
    if hint:
        print(f"  -> {hint}")


if __name__ == "__main__":
    client = OptionWheelClient()
    client.verify_credentials()
    print("\nOptions Wheel client ready.")
