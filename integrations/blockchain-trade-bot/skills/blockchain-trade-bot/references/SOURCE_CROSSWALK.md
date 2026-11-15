# SOURCE CROSSWALK (reviewed 2026-11-15 UTC reference)

| Repository / branch | Examined commit | Observed supported facts | License and constraint |
|---|---|---|---|
| https://github.com/nautechsystems/nautilus_trader `develop` | `12982032fb970cabc085f00169c720792c3edecf` | README: event-driven Rust-native core, Python orchestration, backtest/live conceptual separation, venue adapters and documented migration to v2 | LGPL-3.0; optional external dependency, no code copied |
| https://github.com/erenuludemir/hypergrok-trading-desk `main` | `e5c5d55b8cbba39a20f297d72e6ea3981de233d1` | README/SETUP/plugin.json: fork of Galleon Labs HyperGrok 1.7.2 with 7 roles, 17 skills, Hyperliquid-only execution-ticket approval | MIT / attribution Galleon Labs; workflow concepts adapted, not code copied |
| https://github.com/erenuludemir/skills `main` | `d59805503396547363ff0079c436b1cae496e1af` | README: fork of NVIDIA Agent Skills catalogue, portable skills, governance, multi-domain catalogue | Apache-2.0 and CC BY 4.0; no new NVIDIA certification |

## Derived design, not a verified upstream capability
User's six roles, overnight stocks/crypto scanning, 0.60 scoring, 10% notional cap, 8% stop, +15% trailing activation, $50 starting virtual cash and the specific risk thresholds are design specifications for **this plugin**, not upstream validation results. This plugin does not certify alpha, venue availability, regulatory permission, price history coverage or backtest accuracy.

## Provider constraints
The installed Binance ChatGPT connector is public and read-only; it cannot place orders, retrieve user account balances or stay on 24/7 through a chat. The included independent script can read public Binance Spot REST endpoints on a computer that can reach them, but it does not inherit ChatGPT's connector authorization or financial execution tools. Blockscout tools are research/observation for EVM chains, not an execution authority. A successful public read or sample/test pass does not mean real trading is ready.

## Analysis warnings
- A 30-day volume threshold requires 30 complete daily intervals; a single `ticker/24hr` figure cannot establish the same baseline.
- A -8% software stop is not a fill guarantee; exchange-native bracket mechanics must be inspected before any live use.
- $50 × 10% = $5 max *notional*. Example Binance BTCUSDT Spot minimum notional observed as 5 USDT on 2026-11-15; rounding quantity to allowed lot steps can push the order below minimum. This is not universal to stocks, futures or all exchanges; re-query filters at decision time.
- Earnings/news providers, brokerage permissions, US holiday/extended-hours schedule, funding period normalization, slippage model and account connectivity are **not verified** here.
