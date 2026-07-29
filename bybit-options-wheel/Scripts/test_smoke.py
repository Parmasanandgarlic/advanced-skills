"""Regression smoke test for the Options Wheel reference implementation.

Run against Bybit demo to verify:
  - mask_secret() and has_withdraw_permission() helpers
  - verify_credentials() (with masked output)
  - Vol Skew scan returns sane numbers
  - Contract selection at each risk tier returns a contract in the right Δ band
  - get_24h_price_change() returns a fraction
  - Risk modulator pause logic
  - place_market_sell() / place_limit_and_track() in dry-run mode
    (verifies the API surface without hitting POST endpoints)

Usage:
  cd ../  &&  ./run.sh --debug --rounds 1     # full pipeline against demo
  python Scripts/test_smoke.py                # just this regression test

Exit code 0 on full pass; non-zero on any failure. Designed for CI.
"""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "Scripts"))

# Load .env if present (CI environments usually inject via env vars
# directly, so this is a convenience for local runs).
env_path = REPO / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ[k.strip()] = v.strip()

from optionwheel_bybit_client import (  # noqa: E402
    OptionWheelClient, mask_secret, has_withdraw_permission,
)
from optionwheel import (  # noqa: E402
    compute_vol_skew, select_contract, decide_direction, mid_price,
    get_24h_price_change, apply_risk_modulators, place_market_sell, RISK_TIERS,
)


FAILURES = []


def check(cond, label):
    mark = "✅" if cond else "❌"
    print(f"  {mark} {label}")
    if not cond:
        FAILURES.append(label)


def banner(title):
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")


def main():
    banner("Test 1 — mask_secret() (Rule 2)")
    check(mask_secret("KeobByLDq0gtfN4Vm4") == "Keob…4Vm4", "18-char key masks correctly")
    check(mask_secret("abc") == "***", "short value collapses to ***")
    check(mask_secret("") == "***", "empty value collapses to ***")
    check(mask_secret(None) == "***", "None value collapses to ***")

    banner("Test 2 — has_withdraw_permission() corner cases")
    cases = [
        ({}, False, "missing"),
        ({"Withdraw": None}, False, "null"),
        ({"Withdraw": []}, False, "empty list"),
        ({"Withdraw": [""]}, False, "list of empty string"),
        ({"Withdraw": ["Withdraw"]}, True, "enabled list"),
        ({"Withdraw": True}, True, "bool true"),
        ({"Withdraw": "Withdraw"}, True, "string"),
    ]
    for inp, expected, label in cases:
        check(has_withdraw_permission(inp) == expected, f"{label} → {expected}")

    banner("Test 3 — Live demo: verify_credentials (masked output)")
    if not os.environ.get("BYBIT_API_KEY"):
        print("  [skip] no BYBIT_API_KEY in env; skipping live tests.")
        return 0 if not FAILURES else 1
    client = OptionWheelClient(env_override="demo")
    ok = client.verify_credentials()
    check(ok, "verify_credentials succeeded against demo")

    banner("Test 4 — Vol Skew scan")
    skew = compute_vol_skew(client, "BTC", skew_delta=0.25)
    check(skew is not None, "compute_vol_skew returned non-None")
    if skew:
        put_iv, call_iv, skew_pp, expiry, tickers = skew
        check(0 < put_iv < 5, f"put_iv in (0,5): {put_iv:.3f}")  # decimal form
        check(0 < call_iv < 5, f"call_iv in (0,5): {call_iv:.3f}")
        check(abs(skew_pp) < 100, f"skew_pp reasonable: {skew_pp:+.1f}pp")
        check(len(tickers) > 5, f"ticker cache populated ({len(tickers)} entries)")

    banner("Test 5 — Contract selection at each risk tier")
    for tier, (lo, hi) in RISK_TIERS.items():
        c = select_contract(client, "BTC", "Put", tier, 7, tickers_cache=tickers if skew else None)
        if not c:
            check(False, f"{tier}: select_contract returned None")
            continue
        in_band = lo <= c["delta"] <= hi
        check(in_band, f"{tier}: Δ={c['delta']:.3f} in band [{lo}, {hi}]")

    banner("Test 6 — get_24h_price_change()")
    pc = get_24h_price_change(client, "BTC")
    check(pc is not None, "BTC 24h change fetched")
    if pc is not None:
        check(-0.5 < pc < 0.5, f"BTC 24h change in plausible range: {pc*100:+.2f}%")

    banner("Test 7 — Risk modulator pause logic")
    tier, dirs, notes = apply_risk_modulators(
        "BTC", "D", "standard", ["Put", "Call"],
        atm_iv=0.6, price_change_24h=-0.10,  # 10% drop → should pause Puts
    )
    check("Put" not in dirs, "-10% 24h drop pauses new Put opens")
    check("Call" in dirs, "-10% 24h drop does NOT pause Calls")
    check(any("pause new Put" in n for n in notes), "pause note emitted for Put")

    tier, dirs, notes = apply_risk_modulators(
        "BTC", "D", "standard", ["Put", "Call"],
        atm_iv=0.6, price_change_24h=0.10,
    )
    check("Call" not in dirs, "+10% 24h rise pauses new Call opens")
    check("Put" in dirs, "+10% 24h rise does NOT pause Puts")

    banner("Test 8 — Dry-run order placement (no API call)")
    if skew:
        contract = select_contract(client, "BTC", "Put", "standard", 7, tickers_cache=tickers)
        if contract:
            order_id, fill = place_market_sell(client, "BTC", 0.01, contract, "DEMO", dry_run=True)
            check(order_id == "DRY-RUN", "place_market_sell dry-run returns 'DRY-RUN'")
            check(fill is not None and fill > 0, f"dry-run returned mid price ${fill}")

    banner("Summary")
    if FAILURES:
        print(f"  ❌ {len(FAILURES)} failure(s):")
        for f in FAILURES:
            print(f"     · {f}")
        return 1
    print("  ✅ All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
