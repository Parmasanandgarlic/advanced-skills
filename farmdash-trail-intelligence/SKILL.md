---
name: farmdash-trail-intelligence
description: Read-only DeFi protocol, chain, event, and wallet-risk research using FarmDash.
version: 1.0.0
license: MIT
---

# FarmDash Trail Intelligence

A standalone, third-party research skill for DeFi context alongside Bybit's trading tools. It does not connect to a Bybit account, use Bybit API credentials, place Bybit orders, sign transactions, or execute swaps.

## Availability

Use FarmDash tools only when the user has configured the FarmDash MCP adapter in their agent. FarmDash's published manifest describes a local stdio server; it is not a remote HTTP MCP endpoint. Follow the current setup guidance at https://www.farmdash.one/agents. If the adapter is unavailable, say so rather than inventing results.

## Research workflow

1. Clarify which protocols, chains, addresses, or time window the user wants to examine.
2. Use `get_trail_heat` for current protocol discovery scores and evidence fields. A score is a heuristic, not a prediction of returns.
3. Use `get_chain_breakdown` for descriptive coverage by chain and category.
4. Use `get_agent_events` for reported events; distinguish event data from independently verified facts.
5. Use `get_historical_trailheat` to describe score history and changes. State the period and data timestamp.
6. Use `audit_sybil_risk` only to describe reported wallet-risk signals. Do not suggest methods to evade eligibility rules, detection, or platform controls.
7. If using `simulate_points`, label outputs as hypothetical estimates. Never present simulated points or USD values as guaranteed rewards, realized returns, or investment advice.
8. Summarize evidence, uncertainty, data freshness, and limitations. Do not turn the analysis into a buy/sell recommendation or a call to action.

## Output standards

- Separate reported data from interpretation; include source and observation time when available.
- Explain missing, stale, conflicting, or low-confidence fields instead of filling gaps.
- Do not promise airdrop eligibility, token value, yield, or future performance.
- Do not generate trade instructions or transaction payloads. Bybit trading is outside this skill; any Bybit action must use the relevant Bybit tools and their confirmation safeguards.
- Keep analysis informational and neutral. The user makes all financial decisions.

## References

- FarmDash Agent Hub: https://www.farmdash.one/agents
- OpenAPI contract: https://www.farmdash.one/agents/openapi.yaml
- MCP manifest and tool schemas: https://www.farmdash.one/.well-known/mcp.json