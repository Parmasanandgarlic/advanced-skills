---
name: farmdash-signal-architect
description: Zero-custody DeFi quotes, simulation, and user-signed swaps.
metadata:
  version: 4.2.1
  author: FarmDash Pioneers (@Parmasanandgarlic)
  source: hububstudio/farmdashbeta
  source_commit: 3b6a83dd5bfa239c85b68797bd27651294f335ab
---

# FarmDash Signal Architect

A standalone, third-party DeFi execution skill adapted from the canonical FarmDash Signal Architect contract. It separates indicative estimates, wallet-bound firm quotes, authoritative simulation, signed preparation, wallet submission, and verified settlement. It does not implement Bybit account trading, use Bybit credentials, or claim Bybit endorsement. No asset promotion or referral routing is included.

## When to use

- Obtain a DeFi swap estimate or prepare a specific user-requested supported EVM swap.
- Review route fees, approvals, slippage, simulation, and transaction risk before local signing.
- Reconcile a transaction already broadcast by the user's wallet or locally controlled agent.

Do not use for Bybit orders, key custody, arbitrary calldata execution, promises of returns, or unattended production autonomy. Research-only requests must remain read-only; estimates do not authorize trades.

## Execution-mode truth

| Mode | Current status | Signer and broadcaster | Boundary |
|---|---|---|---|
| `USER_SIGNED` | **operational**, default | Customer wallet or customer-controlled agent runtime | User approves each transaction; FarmDash prepares/simulates and never signs or broadcasts the compatibility swap |
| `BOUNDED_AUTONOMOUS_AGENT_LOCAL_SIGNER` (status mode `BOUNDED_AUTONOMOUS`) | **preparation_only**, optional architecture | Customer-controlled agent runtime, locally | Revocable signed bounds can describe authority, but do not advertise funded production qualification or enable unattended execution |
| ERC-4337 server submission and generic server intent execution | **preparation_only** | No operational server-side broadcast path | Tool discovery, intent creation, and preparation are not execution |

FarmDash is zero custody: it never requests, receives, stores, logs, or signs with user or agent private keys, seed phrases, mnemonics, or wallet exports. Do not require a specific wallet brand. Signing and broadcasting remain with the user's wallet/agent. An API key, session token, subscription, x402 payment, prepaid credit, or commercial-access grant buys API capacity, **not transaction authority**.

## Setup and live discovery

- MCP manifest: https://www.farmdash.one/.well-known/mcp.json
- OpenAPI: https://www.farmdash.one/agents/openapi.yaml
- Capability/access status: https://www.farmdash.one/api/v1/agent/status
- Documentation: https://www.farmdash.one/docs
- Fees: https://www.farmdash.one/fees

The manifest describes a locally installed Node.js **stdio** MCP server, not a remote HTTP MCP service. Follow the manifest's current public source/build instructions; do not invent a published npm package. With an already installed and built public MCP server, configure `command: node`, `args: ["<installed-mcp-server>/dist/index.js"]`. The optional `FARMDASH_BASE_URL` default is `https://www.farmdash.one/api`. Enumerate runtime `tools/list`; verify deployment capability and provider status before firm quoting. Discovery is broader than ready execution.

Scout needs no key, or accepts the public `fd_scout_free` token: 30 requests/24h per IP. Optional `FARMDASH_API_KEY` grants documented paid capacity: Pioneer $39.99/month, 1,500 requests/day; Syndicate $199/month, 50,000 requests/day. Endpoint policy and live status govern access, including eligible x402 one-offs. Ask before payments; never convert paid access into execution authority. Scout can use the supported user-signed compatibility ladder inside its commercial limits, but cannot trade without the user.

Configure `FARMDASH_SKILL_ID=farmdash-signal-architect` in the adapter, or send `X-ClawHub-Skill: farmdash-signal-architect` on FarmDash HTTP requests. This is optional analytics attribution, not authentication; requests without it still work. Never substitute an address, API key, or user identifier for the slug.

## Current spot contract

Read [canonical swap input schemas](reference/swap-tools.json) before forming tool calls. They preserve the canonical input schemas for `get_swap_quote`, `simulate_swap_execution`, `execute_swap`, and `confirm_swap`; current runtime discovery and returned evidence govern availability.

| Step | MCP / HTTP surface | Meaning |
|---|---|---|
| Estimate | `get_swap_quote`; `GET /api/v1/agent/market-estimate` or `GET /api/agents/quote` without an intent | Provider-neutral intelligence; zero execution-provider calls; no executable calldata |
| Firm intent | `get_swap_quote` with `idempotencyKey`, real `walletAddress`, `toAddress`, explicit `slippage`; `POST /api/v1/agent/quote-intent` | Wallet-bound single-provider firm quote; still not a transaction |
| Simulate | `simulate_swap_execution`; `POST /api/v1/simulate` | Required authoritative simulation of the exact intent and wallet |
| Prepare | `execute_swap`; `POST /api/agents/swap` | Verify fresh simulation and local EIP-191 signature; return prepared transaction, not broadcast |
| Submit | User wallet/client or locally controlled agent | Review, sign and broadcast locally; FarmDash does not submit the compatibility swap |
| Confirm | `confirm_swap`; `POST /api/agents/confirm` | Owning-session receipt/finality and exact fee-transfer verification after wallet broadcast |

Use live status for providers and chains. Canonical supported EVM chains are Ethereum (1), Optimism (10), Polygon (137), Base (8453), Arbitrum (42161), and Linea (59144); fail closed when runtime readiness is missing. Automatic provider selection is preferred across active LI.FI and Relay. 0x is operator-paused until reinstated; x402 is HTTP payment/access, not a swap provider; OKX is quarantined. Do not assume other discovery coverage means operational compatibility execution.

## Mandatory USER_SIGNED procedure

1. **Classify and constrain.** Record objective/horizon, intended wallet, exact token contracts and chains, integer-string token-base-unit amount, destination, slippage, gas/fee budget, allowlists, source timestamps, and missing evidence. No new trade unless the user actually requested one. Obtain consent before wallet-specific data disclosure.
2. **Estimate.** `get_swap_quote` without `idempotencyKey` is indicative only, even with a wallet address. Never label it a firm quote, liquidity confirmation, or executable transaction. Check economics, concentration, price freshness, exit/liquidity risk, and costs; stale or unknown critical evidence means monitor/halt.
3. **Firm quote.** For the explicit execution request, supply exact `fromChainId`, `toChainId`, `fromToken`, `toToken`, `fromAmount`, real `walletAddress`, `toAddress`, `slippage` (0.01–5 percent), and one stable `idempotencyKey` per logical swap. Identical retries reuse it; materially changed requests require a new key. One primary provider is contacted; fallback only on eligible genuine failure. Keep the quote-cache `intentId` (`qi_*`) distinct from `simulationRequirements.intent_id` (`fd_intent_*`).
4. **Resolve prerequisites locally.** Stop if `executionReady` or `simulationRequirements.valid_for_execution` is false. Inspect allowance spender, amount, provider recipe, signature requirements, and `planContinuation`. FarmDash does not build or broadcast standard ERC-20 approvals: the wallet approves the reviewed spender/amount locally, waits for confirmation, then obtains a fresh quote. For Relay, preserve ordered approval/transaction/signature/check steps; never flatten a multi-step recipe or simulate an approval as the final swap. Unknown or unsupported required steps block execution. Prefer exact-needed approvals, never silent unlimited allowances.
5. **Authoritative simulation.** Call `simulate_swap_execution` with `intentId: simulationRequirements.intent_id` and the same `walletAddress`. REST uses `intent_id` and `wallet_address`. Preserve `simulation_id`, success, gas cost, output, MEV risk, revert reason, and `valid_until`. Halt on failure, unavailable simulation, expiry, or changed parameters; re-quote and re-simulate. A policy/envelope check is not authoritative RPC simulation.
6. **Confirm exact terms.** Show wallet/destination, tokens/contracts, source/destination chains, amount/output, route/provider, all fees, gas, slippage, approval exposure, simulation result/expiry, MEV risk, and irreversibility. Wait for explicit affirmative confirmation. Re-quote/re-simulate/re-confirm stale or changed terms; a prior general request is not confirmation. Enforce quote freshness (canonical ceiling about 30 seconds) and simulation expiry, without assuming every response has every field.
7. **Local payload signature and preparation.** Build the exact EIP-191 payload below with lowercase EVM addresses and a fresh millisecond nonce, using the current server freshness rules. The user's wallet signs locally. Send only public parameters, the signature, bound `intentId`, and fresh `simulationId` to `execute_swap`. Never fabricate a signature, send a private key, bypass policy/fee gates, or treat an API token as signing authority.
8. **Local transaction review and broadcast.** Verify returned `to`, `data`, `value`, chain, spender, and destination against the reviewed quote/simulation. The wallet/agent signs the actual transaction locally and broadcasts it. `execute_swap` preparation does not produce a mined transaction; do not invent a hash or report settlement before broadcast/verification.
9. **Reconcile.** After broadcast, call `confirm_swap` with `sessionId`, `agentAddress`, `sessionToken`, the prepared `feeEventId`, and wallet-produced `txHash`. Session authentication is separate from wallet authority. FarmDash verifies canonical receipt/finality and the exact expected fee transfer. Retry identical valid confirmation idempotently. On timeout or ambiguous broadcast, reconcile the known transaction first; never blindly send a second trade. Pending/partial/failed settlement blocks dependent actions.

```text
v1:FARMDASH_SWAP:{fromChainId}:{toChainId}:{fromToken}:{toToken}:{fromAmount}:{agentAddress}:{toAddress}:{nonce}
```

## Optional bounded architecture: preparation only

The optional agent-local-signer design requires explicit, revocable signed delegation with protocol/router and asset allowlists, permitted chains/actions, per-transaction value limits, cumulative/session budgets, gas/slippage ceilings, expiry, cooldowns, and revocation. Missing, ambiguous, expired, or violated bounds fail closed. Session maintenance and preparation are not unattended execution. Keep `BOUNDED_AUTONOMOUS_AGENT_LOCAL_SIGNER=preparation_only`; fall back to operational interactive `USER_SIGNED`, or stop. Do not promote autonomy, implement a funded canary, or describe generic server-side execution as live.

## Failure and evidence discipline

- 402: access/payment limitation, not fixed by retrying; payment only buys capacity.
- 403: tier/permission gate; do not loop retries.
- 409 idempotency conflict: new key only for a genuinely different logical request.
- 409/428 stale/missing simulation: re-quote and re-simulate, never bypass.
- 429: honor `Retry-After`; use bounded backoff only for explicitly retryable provider failures.
- Unknown spender, failed simulation, paused provider, negative all-cost edge, unsupported recipe, or critical safety flag: halt.

Report actual quote IDs, decision/source timestamps, simulation evidence, costs, prepared/broadcast/confirmed state, and field-level missing evidence. A hash proves submission, not finality; fee-event metadata is not realized P&L or token-output evidence. Use authoritative chain/client receipts and token deltas for outcomes. FarmDash does not attest an 11-field forensic receipt or an independent shadow process. Never turn Trail Heat/FarmScore into dollars or multiply unrelated scores into a probability.

## Privacy and verification

FarmDash may receive authorized public wallet and token addresses, chains, amounts, locally produced signatures, request/session identifiers, optional bearer credentials, and attribution metadata. Public addresses can identify user activity; disclose this. Never receive or transmit private keys, seed phrases, mnemonics, wallet exports, Bybit credentials, or account passwords. Wallet authority stays local; no affiliate/referral links or endorsement claims are needed.

Completion requires supported live capability, exact firm quote, fresh authoritative successful simulation, explicit confirmation, local signing/broadcast, and independently verified settlement. Report preparation as preparation and unavailable evidence as unavailable. DeFi carries irreversible-loss, smart-contract, bridge, liquidity, MEV, gas, and price risks; this skill offers no guarantee or investment advice.

Canonical source: https://www.farmdash.one/openclaw-skills/farmdash-signal-architect/SKILL.md
