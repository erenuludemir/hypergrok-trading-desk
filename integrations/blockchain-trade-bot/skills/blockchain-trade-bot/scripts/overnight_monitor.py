#!/usr/bin/env python3
"""Foreground public crypto research watcher; simulated paper ledger only; no live orders."""
from __future__ import annotations
import argparse
import importlib.util
import json
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Explicit imports of our own adjacent scripts; never execute untrusted plugins.
import sys
sys.path.insert(0, str(HERE))
from binance_readonly import WATCHLIST, snapshot, future_snapshot
from paper_desk import PaperDesk


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True, type=Path, help="NEW directory; no overwrite")
    p.add_argument("--cycles", type=int, default=12, help="Number of read cycles; 12 at 300 seconds is about 1h")
    p.add_argument("--interval", type=int, default=300, help="Seconds between reads, foreground")
    p.add_argument("--perps", action="store_true", help="Also monitor futures funding; never paper-fill futures")
    args = p.parse_args()
    if args.cycles < 1 or args.cycles > 100000 or args.interval < 10:
        p.error("Require cycles 1..100000 and interval >=10 seconds")
    desk = PaperDesk(args.out)
    for i in range(args.cycles):
        markets, errors = [], {}
        for sym in WATCHLIST:
            try:
                markets.append(snapshot(sym))
            except Exception as exc:
                errors[sym] = f"{type(exc).__name__}: {exc}"
            if args.perps:
                try:
                    markets.append(future_snapshot(sym))
                except Exception as exc:
                    errors[sym + "-PERP"] = f"{type(exc).__name__}: {exc}"
        desk.event("SCOUT", "PUBLIC_DATA_HEALTH", "WATCHLIST", {"cycle":i+1,"returned":len(markets),"errors":errors,"time_utc":datetime.now(timezone.utc).isoformat()})
        desk.process({"mode":"PUBLIC_MARKET_READ_ONLY","source":"Binance public spot/futures GET APIs", "markets":markets})
        if i + 1 < args.cycles:
            time.sleep(args.interval)
    print(json.dumps({"receipt":str(desk.out / "summary.json"), "events":str(desk.events_path),"mode":"PAPER_ONLY", "live_orders":False}))


if __name__ == "__main__":
    main()
