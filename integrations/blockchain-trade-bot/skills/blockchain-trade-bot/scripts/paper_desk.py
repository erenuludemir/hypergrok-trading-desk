#!/usr/bin/env python3
"""Deterministic PAPER-ONLY six-agent simulation. Never places a real order."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

D = lambda value: Decimal(str(value))
MAX_TRADE = D("0.10")
MAX_BOOK_EXPOSURE = D("0.20")
MAX_STRESSED_RISK = D("0.01")
MAX_DRAWDOWN = D("0.02")
STOP_PCT = D("0.08")
TRAIL_ACTIVATION = D("0.15")
STRESS_COST_PCT = D("0.004")
PAPER_FEE_PCT = D("0.001")
MAX_SPREAD_PCT = D("0.0025")
MAX_FUNDING_ABS = D("0.001")
SCORE_FLOOR = D("0.60")
MAX_SNAPSHOT_AGE_SECONDS = 300


def utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def verify_audit(path: Path) -> bool:
    previous = "0" * 64
    for line in path.read_text(encoding="utf-8").splitlines():
        data = json.loads(line)
        checksum = data.pop("sha256")
        if data.pop("prev_sha256") != previous:
            return False
        actual = hashlib.sha256((previous + canonical(data)).encode()).hexdigest()
        if actual != checksum:
            return False
        previous = actual
    return True


class PaperDesk:
    def __init__(self, out: Path, cash: Decimal = D("50")) -> None:
        if cash <= 0:
            raise ValueError("Paper cash must be positive")
        out.mkdir(parents=True, exist_ok=False)  # refuse overwrite existing state
        self.out = out
        self.cash = cash
        self.opening_equity = cash
        self.realized_pnl = D("0")
        self.positions: dict[str, dict[str, Decimal | bool]] = {}
        self.latest_marks: dict[str, Decimal] = {}
        self.unverified_marks: set[str] = set()
        self.ledger: list[dict[str, Any]] = []
        self.prev_hash = "0" * 64
        self.events_path = self.out / "events.jsonl"
        self.event("SUPERVISOR", "START", "DESK", {"mode": "PAPER_ONLY", "starting_virtual_equity": str(cash)})

    def event(self, stage: str, action: str, symbol: str, detail: dict[str, Any]) -> None:
        payload = {"time_utc": utc(), "stage": stage, "action": action,
                   "symbol": symbol, "detail": detail}
        digest = hashlib.sha256((self.prev_hash + canonical(payload)).encode()).hexdigest()
        row = {**payload, "prev_sha256": self.prev_hash, "sha256": digest}
        with self.events_path.open("a", encoding="utf-8") as fp:
            fp.write(canonical(row) + "\n")
            fp.flush()
            os.fsync(fp.fileno())
        self.prev_hash = digest
        self.ledger.append(row)

    def reject(self, stage: str, symbol: str, reasons: list[str], evidence: dict[str, Any] | None = None) -> None:
        payload = {"reason_codes": reasons, "evidence": evidence or {}}
        self.event(stage, "REJECT", symbol, payload)
        self.event("LOGGER", "KILL", symbol, {"rejected_at": stage, **payload})

    def marked_equity(self, marks: dict[str, Decimal] | None = None) -> Decimal:
        marks = marks or {}
        return self.cash + sum((D(p["qty"]) * marks.get(symbol, D(p["entry"]))) for symbol, p in self.positions.items())

    def gross_exposure(self, marks: dict[str, Decimal] | None = None) -> Decimal:
        marks = marks or {}
        return sum((D(p["qty"]) * marks.get(symbol, D(p["entry"]))) for symbol, p in self.positions.items())

    def update_positions(self, markets: list[dict[str, Any]], mode: str = "SYNTHETIC_FIXTURE") -> None:
        prices = {}
        for m in markets:
            # Existing paper positions must never be exited or trail-adjusted by
            # stale, future, or timezone-naive PUBLIC_MARKET_READ_ONLY marks.
            # Record the rejection, and leave the prior audited state unchanged.
            if mode != "SYNTHETIC_FIXTURE":
                try:
                    asof = datetime.fromisoformat(str(m["source_time_utc"]).replace("Z", "+00:00"))
                    if asof.tzinfo is None:
                        self.event("RISK", "UNVERIFIED_POSITION_MARK", str(m.get("symbol", "UNKNOWN")), {"reason": "NAIVE_SOURCE_TIME"})
                        continue
                    age = (datetime.now(timezone.utc) - asof).total_seconds()
                    if age < -30 or age > MAX_SNAPSHOT_AGE_SECONDS:
                        self.event("RISK", "UNVERIFIED_POSITION_MARK", str(m.get("symbol", "UNKNOWN")), {"reason": "STALE_OR_FUTURE_DATA"})
                        continue
                except (KeyError, TypeError, ValueError):
                    self.event("RISK", "UNVERIFIED_POSITION_MARK", str(m.get("symbol", "UNKNOWN")), {"reason": "INVALID_SOURCE_TIME"})
                    continue
            try:
                value = D(m.get("price"))
                if value.is_finite() and value > 0:
                    prices[str(m["symbol"])] = value
            except (KeyError, TypeError, ValueError, ArithmeticError):
                continue
        self.unverified_marks = set(self.positions).difference(prices)
        self.latest_marks = prices
        for symbol, p in list(self.positions.items()):
            if symbol not in prices or prices[symbol] <= 0:
                self.event("RISK", "MARK_MISSING", symbol, {"mode": "PAPER_ONLY"})
                continue
            price = prices[symbol]
            if price > D(p["high"]):
                p["high"] = price
            if D(p["high"]) >= D(p["entry"]) * (1 + TRAIL_ACTIVATION):
                p["trailing_active"] = True
                tighter = D(p["high"]) * (1 - STOP_PCT)
                if tighter > D(p["stop"]):
                    p["stop"] = tighter
                    self.event("RISK", "TRAIL_TIGHTEN", symbol, {"stop": str(tighter), "high": str(p["high"])})
            if price <= D(p["stop"]):
                qty = D(p["qty"])
                proceeds = qty * price * (1 - PAPER_FEE_PCT)
                self.cash += proceeds
                pnl = proceeds - qty * D(p["entry"]) * (1 + PAPER_FEE_PCT)
                self.realized_pnl += pnl
                self.event("EXECUTOR", "PAPER_EXIT", symbol, {"price": str(price), "stop": str(p["stop"]), "pnl": str(pnl), "gap_risk": "stop execution is NOT guaranteed in live markets"})
                del self.positions[symbol]
                self.event("LOGGER", "CLOSE", symbol, {"realized_pnl": str(pnl)})

    def process(self, data: dict[str, Any]) -> None:
        mode = data.get("mode")
        if mode not in ("SYNTHETIC_FIXTURE", "PUBLIC_MARKET_READ_ONLY"):
            raise ValueError("Unsupported input provenance; only synthetic or public read-only")
        markets = data.get("markets")
        if not isinstance(markets, list):
            raise ValueError("Input markets must be a list")
        self.event("SUPERVISOR", "SOURCE", "DESK", {"mode": mode, "source": data.get("source", "UNKNOWN"), "count": len(markets)})
        self.update_positions(markets, mode)
        for m in markets:
            self.process_one(m, mode)
        self.save_summary()

    def process_one(self, m: dict[str, Any], mode: str) -> None:
        symbol = str(m.get("symbol", "UNKNOWN"))
        asset = m.get("asset_class")
        self.event("SCOUT", "OBSERVED", symbol, {"asset_class": asset, "source": mode, "source_time_utc": m.get("source_time_utc")})
        reasons: list[str] = []
        try:
            price, bid, ask = (D(m.get(k)) for k in ("price", "bid", "ask"))
            daily = D(m.get("daily_volume"))
            avg30 = D(m.get("avg_daily_volume_30d"))
            depth = D(m.get("depth_usd_10bps"))
        except (ValueError, TypeError, ArithmeticError):
            self.reject("FILTER", symbol, ["MISSING_MARKET_NUMERIC_DATA"])
            return
        if asset not in ("crypto_spot", "crypto_perp", "us_equity"):
            reasons.append("UNSUPPORTED_ASSET_CLASS")
        if min(price, bid, ask) <= 0 or ask < bid:
            reasons.append("INVALID_QUOTE")
        spread = (ask - bid) / ((ask + bid) / 2) if bid > 0 and ask >= bid else D("999")
        if spread > MAX_SPREAD_PCT:
            reasons.append("WIDE_SPREAD")
        if avg30 <= 0 or daily < avg30:
            reasons.append("BELOW_30D_AVG_DAILY_VOLUME")
        if depth < D("100"):
            reasons.append("THIN_BOOK_DEPTH")
        if m.get("news_risk") is not False:
            reasons.append("NEWS_RISK_OR_UNVERIFIED")
        if asset == "us_equity" and m.get("earnings_tomorrow") is not False:
            reasons.append("EARNINGS_CALENDAR_OR_UNVERIFIED")
        if asset == "crypto_perp":
            try:
                funding = D(m.get("funding_rate"))
                if abs(funding) > MAX_FUNDING_ABS:
                    reasons.append("EXTREME_FUNDING")
            except (TypeError, ValueError, ArithmeticError):
                reasons.append("FUNDING_UNVERIFIED")
        if mode != "SYNTHETIC_FIXTURE":
            try:
                asof = datetime.fromisoformat(str(m["source_time_utc"]).replace("Z", "+00:00"))
                if asof.tzinfo is None:
                    reasons.append("TIME_UNVERIFIED")
                else:
                    age = (datetime.now(timezone.utc) - asof).total_seconds()
                    if age < -30 or age > MAX_SNAPSHOT_AGE_SECONDS:
                        reasons.append("STALE_OR_FUTURE_DATA")
            except (KeyError, ValueError, TypeError):
                reasons.append("TIME_UNVERIFIED")
        if reasons:
            self.reject("FILTER", symbol, reasons, {"spread_fraction": str(spread), "depth_usd": str(depth), "daily_volume": str(daily), "avg30": str(avg30)})
            return
        self.event("FILTER", "PASS", symbol, {"spread_fraction": str(spread)})
        try:
            momentum, trend = D(m.get("momentum")), D(m.get("trend"))
            if any(x < 0 or x > 1 for x in (momentum, trend)):
                raise ValueError("Feature out of bounds")
        except (ValueError, TypeError, ArithmeticError):
            self.reject("ANALYST", symbol, ["INVALID_OR_MISSING_FEATURES"])
            return
        score = (momentum + trend) / 2
        if score < SCORE_FLOOR:
            self.reject("ANALYST", symbol, ["SCORE_LT_0_60"], {"score": str(score)})
            return
        self.event("ANALYST", "PASS", symbol, {"score": str(score), "model": "transparent_heuristic_not_calibrated"})
        if asset != "crypto_spot":
            self.reject("RISK", symbol, ["RESEARCH_ONLY_NON_SPOT_ASSET"])
            return
        if symbol in self.positions:
            self.reject("RISK", symbol, ["ALREADY_OPEN_NO_DUPLICATE"])
            return
        if len(self.positions) >= 2:
            self.reject("RISK", symbol, ["MAX_TWO_POSITIONS"])
            return
        if self.unverified_marks:
            self.reject("RISK", symbol, ["EXISTING_POSITION_MARK_MISSING"], {"unverified_symbols": sorted(self.unverified_marks)})
            return
        equity = self.marked_equity(self.latest_marks)
        if equity < self.opening_equity * (1 - MAX_DRAWDOWN):
            self.reject("RISK", symbol, ["DRAWDOWN_KILL_SWITCH"])
            return
        if D("1") * (STOP_PCT + STRESS_COST_PCT) > 1:
            raise AssertionError("Broken risk parameters")
        desired_notional = min(equity * MAX_TRADE,
                               equity * MAX_STRESSED_RISK / (STOP_PCT + STRESS_COST_PCT),
                               equity * MAX_BOOK_EXPOSURE - self.gross_exposure(self.latest_marks),
                               self.cash / (1 + PAPER_FEE_PCT))
        try:
            step, minimum = D(m.get("qty_step")), D(m.get("min_notional"))
            if step <= 0 or minimum <= 0:
                raise ValueError("Invalid venue rules")
        except (ValueError, TypeError, ArithmeticError):
            self.reject("RISK", symbol, ["VENUE_RULES_UNVERIFIED"])
            return
        qty = (desired_notional / ask / step).to_integral_value(rounding=ROUND_DOWN) * step
        notional = qty * ask
        if notional < minimum or qty <= 0:
            self.reject("RISK", symbol, ["MIN_NOTIONAL_OR_STEP_FAILURE"], {"notional": str(notional), "minimum": str(minimum), "max_trade": str(equity * MAX_TRADE)})
            return
        if notional > equity * MAX_TRADE or notional * (STOP_PCT + STRESS_COST_PCT) > equity * MAX_STRESSED_RISK:
            self.reject("RISK", symbol, ["INVARIANT_MAX_RISK_EXCEEDED"])
            return
        stop = ask * (1 - STOP_PCT)
        ticket = hashlib.sha256(canonical({"symbol": symbol, "snapshot": m, "mode": mode}).encode()).hexdigest()[:16]
        # Simulated protective stop MUST be staged and audited BEFORE the simulated fill.
        self.event("RISK", "PAPER_STOP_STAGED", symbol, {"ticket": ticket, "stop_price": str(stop), "qty": str(qty), "notional": str(notional)})
        cost = notional * (1 + PAPER_FEE_PCT)
        self.cash -= cost
        self.positions[symbol] = {"qty": qty, "entry": ask, "stop": stop, "high": ask, "trailing_active": False}
        self.event("EXECUTOR", "PAPER_ENTRY", symbol, {"ticket": ticket, "qty": str(qty), "ask": str(ask), "notional": str(notional), "mode": "PAPER_ONLY"})
        self.event("LOGGER", "PAPER_OPEN", symbol, {"ticket": ticket, "initial_stop": str(stop)})

    def save_summary(self) -> None:
        summary = {"mode": "PAPER_ONLY", "time_utc": utc(), "starting_virtual_equity": str(self.opening_equity),
                   "current_virtual_cash": str(self.cash), "marked_virtual_equity": str(self.marked_equity(self.latest_marks)),
                   "realized_pnl": str(self.realized_pnl),
                   "open_positions": {s: {k: str(v) if isinstance(v, Decimal) else v for k, v in p.items()} for s, p in self.positions.items()},
                   "kills": sum(e["stage"] == "LOGGER" and e["action"] == "KILL" for e in self.ledger),
                   "paper_entries": sum(e["stage"] == "EXECUTOR" and e["action"] == "PAPER_ENTRY" for e in self.ledger),
                   "audit_chain_valid": verify_audit(self.events_path),
                   "real_order_capability": False, "live_readiness": "BLOCKED"}
        with (self.out / "summary.json").open("w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
            f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="JSON market snapshot, synthetic or read-only")
    parser.add_argument("--out", required=True, type=Path, help="NEW output directory, never overwritten")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--interval", type=int, default=300, help="Foreground seconds between cycles")
    args = parser.parse_args()
    if args.cycles < 1 or args.cycles > 100000 or args.interval < 0:
        parser.error("Invalid cycles or interval")
    desk = PaperDesk(args.out)
    for cycle in range(args.cycles):
        with args.input.open("r", encoding="utf-8") as f:
            data = json.load(f)
        desk.process(data)
        if cycle < args.cycles - 1:
            time.sleep(args.interval)
    print(canonical(json.loads((desk.out / "summary.json").read_text(encoding="utf-8"))))


if __name__ == "__main__":
    main()
