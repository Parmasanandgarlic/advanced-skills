---
name: farmdash-trail-intelligence
description: Read-only DeFi research with timestamps and risk evidence.
metadata:
  version: 3.1.3
  author: FarmDash Pioneers (@Parmasanandgarlic)
  source: hububstudio/farmdashbeta
  source_commit: 3b6a83dd5bfa239c85b68797bd27651294f335ab
---

# FarmDash Trail Intelligence

A third-party, read-only DeFi research skill adapted from the canonical FarmDash Trail Intelligence manual. Use it for protocol discovery, Trail Heat, event and historical research, hypothetical allocation analysis, route feasibility, and defensive Sybil-risk review. It never executes, signs, broadcasts, changes allowances, or creates execution authority.

This skill does not use Bybit credentials or trade a Bybit account. Submission to this repository is not a claim of Bybit endorsement. It is research, not investment advice, asset promotion, or a promise of eligibility or returns.

## When to use

- Compare protocols, airdrop or points programs using sourced evidence.
- Inspect historical trends, upcoming events, missing data, or research risks.
- Analyze a user-supplied public wallet only when the user requests it.
- Preview route economics without preparing approvals or transactions.

Do not use this skill for swaps, bridges, deposits, withdrawals, perpetual orders, signing, or delegated execution. A user-requested state-changing action requires a separate execution surface; do not automatically invoke one.

## Setup and current discovery

Read these public contracts before selecting tools:

- MCP discovery: https://www.farmdash.one/.well-known/mcp.json
- OpenAPI: https://www.farmdash.one/agents/openapi.yaml
- Capability and access status: https://www.farmdash.one/api/v1/agent/status
- Integration documentation: https://www.farmdash.one/docs

The manifest describes a locally installed Node.js **stdio** server, not a remote HTTPS MCP endpoint. Use its current public source/build instructions. The npm package is not advertised as published. With an existing installed and built public MCP server, configure the host with `command: node` and `args: ["<installed-mcp-server>/dist/index.js"]`. Set `FARMDASH_BASE_URL` to `https://www.farmdash.one/api` unless intentionally using a trusted alternate deployment. Inspect the runtime's `tools/list`; a manifest entry is not proof that a deployment is ready.

`FARMDASH_API_KEY` is optional. Scout is keyless or accepts the public `fd_scout_free` token: 30 requests per 24 hours per IP. Pioneer is $39.99/month with 1,500 requests/day; Syndicate is $199/month with 50,000 requests/day. Use current status and endpoint policy to resolve paid/full-data access and optional x402 one-off capacity. Never infer access from a tool name, manufacture tier-masked values, solicit a subscription during a safety warning, or silently make a payment. API access is not wallet authority.

For attribution, configure `FARMDASH_SKILL_ID=farmdash-trail-intelligence` in the adapter, or send `X-ClawHub-Skill: farmdash-trail-intelligence` on FarmDash HTTP calls. This header is optional analytics metadata, never authentication; absence does not block a request. Never put a wallet address, user ID, or secret in it.

## Tool and endpoint contract

Read [research input schemas](reference/research-tools.json) before forming calls. The focused tool set comes from the canonical skill; input schemas were refreshed from the live MCP manifest on 2026-10-28. Current runtime discovery and response fields remain authoritative.

| MCP tool | HTTP research surface | Usage |
|---|---|---|
| `get_trail_heat` | `GET /api/v1/trail-heat` | Canonical quantitative Trail Heat, not catalog editorial score |
| `get_protocol_metadata`, `get_protocol_risk_factors` | `/api/v1/agent/protocols` | Use `protocolId`; no invented audits or admin-key facts |
| `get_chain_breakdown` | `GET /api/v1/agent/chain-breakdown` | Chain distribution and context |
| `get_agent_events` | `GET /api/v1/agent/events` | Returned events with their actual coverage and timestamps |
| `get_historical_trailheat` | `GET /api/v1/agent/historical-trailheat` | Preserve evidence vintage; old editorial snapshots are not quantitatively comparable |
| `audit_sybil_risk` | `POST /api/v1/agent/sybil-audit` | 1–10 public EVM addresses; defensive heuristics, not eligibility certification |
| `simulate_points` | `POST /api/v1/agent/simulate-points` | Deterministic FarmScore scenario arithmetic, not reward dollars or ROI |
| `get_wallet_balances` | `GET /api/v1/agent/balances` | User-requested public-wallet reads; respect endpoint access gates |
| `get_token_prices` | `GET /api/v1/agent/prices` | Source-labeled prices and freshness |
| `optimize_portfolio` | `/api/v1/agent/intent` | Hypothetical allocation planning only |
| `find_capital_route` | `/api/agents/quote` | Indicative route feasibility only; no approval, calldata preparation, or broadcast |

Use the manifest and OpenAPI for method, parameter, and response details rather than guessing from this table. `find_capital_route` uses `fromChainId`, `toChainId`, `fromToken`, `toToken`, and integer-string `fromAmount` in token base units. Automatic provider selection is preferred; current active routes are LI.FI and Relay. 0x is operator-paused, x402 is payment/access rather than a swap provider, and OKX is quarantined. A preview is not an executable firm quote. Do not call firm quote-intent, simulation-to-execution, approval, onboarding-registration, session mutation, or transaction endpoints from this skill.

## Research procedure

1. Record the goal, horizon, user constraints, permitted chains/protocols, and whether public-wallet disclosure is authorized. No wallet is needed for general protocol research.
2. Gather events and canonical `get_trail_heat`; shortlist at least three valid candidates for a broad comparison, or disclose that fewer were returned. Inspect metadata, risk factors, historical vintages, and chain context without filling gaps.
3. Preserve per-number evidence states: `observed`, `derived`, `editorial`, `stale`, or `unavailable`. Null means unknown, not zero. Unresolved protocols are excluded from numeric rankings. Trail Heat is a heuristic, not probability, expected return, or smart-contract safety.
4. Use `simulate_points` only for requested hypothetical scenarios, with sanitized inputs and the formula shown. It does not supply token value, APY, yield decay, gas estimates, or eligibility. Never recommend transactions designed to inflate a score.
5. Use Sybil review defensively. Report exact returned signals and `dataQuality`; never certify a wallet as clean, infer common control without evidence, or prescribe timing changes, activity patterns, or wallet rotation to defeat protocol anti-abuse controls.
6. When requested, preview route costs, gas, bridge fees, slippage, timing, and exit-liquidity gaps. Missing reward valuation or negative all-cost edge means `monitor`, not a trade instruction. A route preview cannot authorize or execute anything.
7. Return a ranked, timestamped evidence report. Stop at analysis. If the user asks to act, explain that a separate user-authorized execution skill must obtain its own fresh firm quote, simulation, confirmation, and local signature.

## Report and verification

For each material conclusion include objective/horizon, `asOf`, exact sources, source timestamps, freshness window, tier/masked fields, methodology, known costs, downside/invalidation, concentration impact, missing evidence, and `recommend` / `monitor` / `avoid`. Use `recommend` only for an evidence-supported research conclusion, not a directive to move money. If the API returns `timestamp`, retain that raw field and clearly label any derived `asOf`; client retrieval time is not an upstream observation timestamp.

Never combine unrelated heuristic scores into a synthetic probability. Require independently sourced audit evidence for audit-level claims. Missing data remains `unavailable`. No affiliate/referral links, asset promotion, raw personal wallet examples, or guaranteed outcomes belong in the report.

Validate that every tool called is read-only, every numeric claim has evidence, every stale/masked field is disclosed, and no signing, execution, allowance, registration, or authority-changing call was made. For 402/403, explain the access limitation; for 429, respect `Retry-After`; use bounded retries only on explicitly retryable failures.

## Privacy and risk boundaries

FarmDash and its upstream RPC/data providers may receive authorized public wallet addresses, research parameters, optional FarmDash bearer tokens, and attribution metadata. Public addresses can be linked to a user; obtain consent for wallet-specific research. Never request, receive, log, or transmit private keys, seed phrases, mnemonics, wallet exports, Bybit credentials, or account passwords. Smart-contract, liquidity, bridge, price, and speculative-airdrop risks remain even when a score is high.

Canonical source: https://www.farmdash.one/openclaw-skills/farmdash-trail-intelligence/SKILL.md

Contract verification: current MCP input schemas and live capability status checked on 2026-10-28 against canonical main `45196127e861f55fa3fb0e295dc4580a6bdfe4ad`. The source-adaptation commit above is historical provenance, not a claim that it is current main.
