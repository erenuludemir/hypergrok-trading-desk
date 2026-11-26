#!/usr/bin/env python3
"""Public market data acquisition only. No credentials, trading or orders."""
from __future__ import annotations
import argparse
import json
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal

BASE = "https://api.binance.com"
FUTURES_BASE = "https://fapi.binance.com"
WATCHLIST = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def fetch(path: str, params: dict, *, futures: bool = False) -> object:
    url = (FUTURES_BASE if futures else BASE) + path + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "Blockchain-Trade-Bot-ReadOnly/0.1"}, method="GET")
    with urllib.request.urlopen(request, timeout=12, context=ssl.create_default_context()) as response:
        return json.load(response)


def snapshot(symbol: str) -> dict:
    if symbol not in WATCHLIST:
        raise ValueError("Symbol not in reviewed read-only watchlist")
    exchange = fetch("/api/v3/exchangeInfo", {"symbol": symbol})
    filters = {f["filterType"]: f for f in exchange["symbols"][0]["filters"]}
    book = fetch("/api/v3/depth", {"symbol": symbol, "limit": 100})
    # 32 daily bars include today's incomplete bar; discard today's bar explicitly.
    klines = fetch("/api/v3/klines", {"symbol": symbol, "interval": "1d", "limit": 32})
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    complete = [bar for bar in klines if int(bar[6]) < now_ms]
    if len(complete) < 30:
        raise ValueError("Insufficient 30 complete daily bars")
    daily = [Decimal(str(bar[7])) for bar in complete[-30:]]  # quote volume, USD-equivalent USDT
    bid = Decimal(str(book["bids"][0][0])); ask = Decimal(str(book["asks"][0][0]))
    mid = (bid + ask) / 2
    bid_depth = sum(Decimal(str(p))*Decimal(str(q)) for p, q in book["bids"] if Decimal(str(p)) >= mid * Decimal("0.999"))
    ask_depth = sum(Decimal(str(p))*Decimal(str(q)) for p, q in book["asks"] if Decimal(str(p)) <= mid * Decimal("1.001"))
    # partial order book: depth is a lower bound only; never use it to claim a full book.
    return {
        "symbol": symbol, "asset_class": "crypto_spot", "price": str(mid), "bid": str(bid), "ask": str(ask),
        "daily_volume": str(daily[-1]), "avg_daily_volume_30d": str(sum(daily) / 30),
        "depth_usd_10bps": str(min(bid_depth, ask_depth)),
        "depth_caveat": "Top 100 levels only; 10bp depth is a lower bound if book truncated",
        "news_risk": None, "earnings_tomorrow": None, "funding_rate": None,
        "momentum": None, "trend": None,  # must come from independently tested signal model
        "qty_step": filters["LOT_SIZE"]["stepSize"],
        "min_notional": filters.get("NOTIONAL", filters.get("MIN_NOTIONAL", {})).get("minNotional"),
        "source_time_utc": datetime.now(timezone.utc).isoformat(),
        "provenance": ["Binance Spot exchangeInfo", "Binance Spot depth", "Binance Spot klines"],
    }


def future_snapshot(symbol: str) -> dict:
    """Futures are classified/reported but NEVER entered by this paper-only desk."""
    if symbol not in WATCHLIST:
        raise ValueError("Symbol not in reviewed public-futures watchlist")
    future = True
    book = fetch("/fapi/v1/depth", {"symbol": symbol, "limit": 100}, futures=future)
    premium = fetch("/fapi/v1/premiumIndex", {"symbol": symbol}, futures=future)
    klines = fetch("/fapi/v1/klines", {"symbol": symbol, "interval": "1d", "limit": 32}, futures=future)
    exchange = fetch("/fapi/v1/exchangeInfo", {}, futures=future)
    info = next((s for s in exchange.get("symbols", []) if s.get("symbol") == symbol), None)
    if info is None:
        raise ValueError("Missing Futures symbol filters")
    filters = {f["filterType"]: f for f in info["filters"]}
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    complete = [bar for bar in klines if int(bar[6]) < now_ms]
    if len(complete) < 30:
        raise ValueError("Insufficient 30 complete futures daily bars")
    volumes = [Decimal(str(bar[7])) for bar in complete[-30:]]
    bid = Decimal(str(book["bids"][0][0])); ask = Decimal(str(book["asks"][0][0]))
    mid = (bid + ask)/2
    bd = sum(Decimal(str(p))*Decimal(str(q)) for p,q in book["bids"] if Decimal(str(p)) >= mid * Decimal("0.999"))
    ad = sum(Decimal(str(p))*Decimal(str(q)) for p,q in book["asks"] if Decimal(str(p)) <= mid * Decimal("1.001"))
    return {
        "symbol":symbol+"-PERP", "venue_symbol":symbol, "asset_class":"crypto_perp",
        "price":str(mid), "bid":str(bid), "ask":str(ask),
        "daily_volume":str(volumes[-1]), "avg_daily_volume_30d":str(sum(volumes)/30),
        "depth_usd_10bps":str(min(bd,ad)), "news_risk":None, "earnings_tomorrow":None,
        "funding_rate":premium.get("lastFundingRate"), "momentum":None, "trend":None,
        "qty_step":filters.get("LOT_SIZE",{}).get("stepSize"),
        "min_notional":filters.get("MIN_NOTIONAL",{}).get("notional"),
        "source_time_utc":datetime.now(timezone.utc).isoformat(),
        "provenance":["Binance USD-M futures premiumIndex", "Binance Futures depth", "Binance Futures klines", "Binance Futures exchangeInfo"],
        "research_only":True, "live_perp_execution_supported":False
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--perps", action="store_true", help="Include public USD-M perpetual funding/depth research (never trade)")
    args = p.parse_args()
    if args.output.exists():
        p.error("Refuse to overwrite output file; choose a new path")
    records = []
    errors = {}
    for symbol in WATCHLIST:
        try:
            records.append(snapshot(symbol))
        except Exception as exc:
            errors[symbol] = f"{type(exc).__name__}: {exc}"
    if args.perps:
        for symbol in WATCHLIST:
            try:
                records.append(future_snapshot(symbol))
            except Exception as exc:
                errors[symbol + "-PERP"] = f"{type(exc).__name__}: {exc}"
    if not records:
        raise SystemExit("No public snapshots obtained: " + json.dumps(errors))
    payload = {"mode":"PUBLIC_MARKET_READ_ONLY","source":"Binance public Spot REST (not an account connector)",
               "time_utc":datetime.now(timezone.utc).isoformat(),"markets":records,"unavailable_symbols":errors,
               "limitations":"Missing independently sourced earnings/news and validated scoring; unsafe to paper-fill or trade real orders"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(json.dumps({"file":str(args.output),"symbols":len(records),"errors":errors,"real_orders":False}))


if __name__ == "__main__":
    main()
