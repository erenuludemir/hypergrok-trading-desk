# Blockchain-Trade-Bot v0.1.1

**Private skills-only ChatGPT plugin** including six-agent, deterministic paper-only reference code. It is not a hosted bot or always-on daemon.

## Run locally (macOS or Linux; Python 3.10+)

```bash
cd blockchain-trade-bot/skills/blockchain-trade-bot
python3 -m unittest discover -s tests -v
python3 scripts/paper_desk.py --input fixtures/demo.json --out "$HOME/blockchain-trade-bot-paper-example"
python3 scripts/binance_readonly.py --perps --output "$HOME/blockchain-trade-bot-binance-readonly.json"
python3 scripts/overnight_monitor.py --perps --cycles 12 --interval 300 --out "$HOME/blockchain-trade-bot-night-$(date +%Y%m%dT%H%M%S)"
```

The output path must **not exist** at the start of each `paper_desk.py` run (no overwrite by default). `binance_readonly.py` refuses to overwrite an existing file. `--cycles` and `--interval` are foreground-only and replay a static source unless a separate authorized producer updates the snapshot file. Public reads require network access and may be inaccessible in your region.

**Design, not a trading guarantee:** `PAPER_ONLY` $50, max order $5 at opening equity, score >=0.6, stop 8%, trailing stop enabled only after +15%, risk cap 1% per ticket, equity drawdown ceiling 2% per session. The synthetic fixture is NOT real historical performance.

Source review: see `skills/blockchain-trade-bot/references/SOURCE_CROSSWALK.md`. No live trading credentials, position broadcaster, broker APIs, on-chain signing, or financial return promises are included.

US equities: the skill defines a fail-closed data contract, but **no verified US equities extended-hours broker or earnings/calendar/news provider** is wired into the runnable collector. Such instruments cannot be cleared for paper entries from incomplete data. Live broker connectivity is deliberately absent.

## v0.1.1 safety patch

Public market marks are now timestamp-validated **before** changing the paper positions, trailing stops, or simulated exits. Stale, future, missing, and timezone-naive marks are rejected and chained into the audit trail. No existing files were removed. This patch does not start a host daemon or connect live execution.
