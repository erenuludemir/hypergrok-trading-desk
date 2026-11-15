import copy
import importlib.util
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("paper_desk", ROOT / "scripts" / "paper_desk.py")
paper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paper)


class PaperDeskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.desk = paper.PaperDesk(Path(self.tmp.name) / "receipt")
        self.data = json.loads((ROOT / "fixtures" / "demo.json").read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def test_six_stages_and_kills(self):
        self.desk.process(self.data)
        s = json.loads((self.desk.out / "summary.json").read_text())
        self.assertEqual(s["paper_entries"], 1)
        self.assertEqual(s["kills"], 4)
        self.assertTrue(s["audit_chain_valid"])
        self.assertFalse(s["real_order_capability"])
        self.assertEqual(set(s["open_positions"]), {"BTCUSDT"})
        events = self.desk.ledger
        i_stop = next(i for i,e in enumerate(events) if e["action"] == "PAPER_STOP_STAGED")
        i_fill = next(i for i,e in enumerate(events) if e["action"] == "PAPER_ENTRY")
        self.assertLess(i_stop, i_fill)
        kills = [e for e in events if e["action"] == "KILL"]
        self.assertTrue(any("WIDE_SPREAD" in e["detail"]["reason_codes"] for e in kills))
        self.assertTrue(any("EXTREME_FUNDING" in e["detail"]["reason_codes"] for e in kills))
        self.assertTrue(any("SCORE_LT_0_60" in e["detail"]["reason_codes"] for e in kills))

    def test_trailing_only_activates_after_fifteen_percent(self):
        self.desk.process({**self.data, "markets": [self.data["markets"][0]]})
        before = self.desk.positions["BTCUSDT"]
        self.assertFalse(before["trailing_active"])
        original = Decimal(before["stop"])
        self.desk.update_positions([{"symbol":"BTCUSDT", "price":57499}])
        self.assertFalse(self.desk.positions["BTCUSDT"]["trailing_active"])
        self.assertEqual(Decimal(self.desk.positions["BTCUSDT"]["stop"]), original)
        self.desk.update_positions([{"symbol":"BTCUSDT", "price":57500}])
        self.assertTrue(self.desk.positions["BTCUSDT"]["trailing_active"])
        tightened = Decimal(self.desk.positions["BTCUSDT"]["stop"])
        self.assertGreater(tightened, original)
        self.desk.update_positions([{"symbol":"BTCUSDT", "price":52900}])
        self.assertNotIn("BTCUSDT", self.desk.positions)

    def test_unknown_news_fails_closed(self):
        row = copy.deepcopy(self.data["markets"][0])
        row["news_risk"] = None
        self.desk.process({**self.data, "markets": [row]})
        self.assertEqual(len(self.desk.positions), 0)
        self.assertTrue(any("NEWS_RISK_OR_UNVERIFIED" in e["detail"].get("reason_codes", []) for e in self.desk.ledger))

    def test_min_notional_after_step_does_not_bypass(self):
        row = copy.deepcopy(self.data["markets"][0])
        row["qty_step"] = "0.0002"
        self.desk.process({**self.data, "markets": [row]})
        self.assertFalse(self.desk.positions)
        self.assertTrue(any("MIN_NOTIONAL_OR_STEP_FAILURE" in e["detail"].get("reason_codes", []) for e in self.desk.ledger))

    def test_reject_preexisting_output(self):
        with self.assertRaises(FileExistsError):
            paper.PaperDesk(self.desk.out)

    def test_audit_tamper_detected(self):
        self.desk.process(self.data)
        self.assertTrue(paper.verify_audit(self.desk.events_path))
        content = self.desk.events_path.read_text()
        self.desk.events_path.write_text(content.replace('"START"', '"ALTER"', 1))
        self.assertFalse(paper.verify_audit(self.desk.events_path))

    def test_stale_readonly_rejected(self):
        row = copy.deepcopy(self.data["markets"][0])
        row["source_time_utc"] = "2020-01-01T00:00:00+00:00"
        self.desk.process({"mode":"PUBLIC_MARKET_READ_ONLY","markets":[row]})
        self.assertFalse(self.desk.positions)
        self.assertTrue(any("STALE_OR_FUTURE_DATA" in e["detail"].get("reason_codes", []) for e in self.desk.ledger))


if __name__ == "__main__":
    unittest.main()

# Supplemental regression checks for hard-stop time validation and missing existing marks.
class AdditionalGateTests(unittest.TestCase):
    def test_naive_public_snapshot_timestamp_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            desk = paper.PaperDesk(Path(tmp) / "receipt")
            data = json.loads((ROOT / "fixtures" / "demo.json").read_text())
            row = copy.deepcopy(data["markets"][0])
            row["source_time_utc"] = "2026-11-15T10:00:00"
            desk.process({"mode":"PUBLIC_MARKET_READ_ONLY","markets":[row]})
            self.assertFalse(desk.positions)
            self.assertTrue(any("TIME_UNVERIFIED" in e["detail"].get("reason_codes", []) for e in desk.ledger))

    def test_missing_mark_on_existing_position_disallows_new_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            desk = paper.PaperDesk(Path(tmp) / "receipt")
            data = json.loads((ROOT / "fixtures" / "demo.json").read_text())
            desk.process({**data, "markets": [data["markets"][0]]})
            row = copy.deepcopy(data["markets"][0]); row["symbol"] = "ALTUSDT"; row["qty_step"] = "0.00001"
            desk.process({**data, "markets": [row]})
            self.assertNotIn("ALTUSDT", desk.positions)
            self.assertTrue(any("EXISTING_POSITION_MARK_MISSING" in e["detail"].get("reason_codes", []) for e in desk.ledger))


class PublicMarkIntegrityTests(unittest.TestCase):
    def test_stale_public_mark_cannot_trigger_exit_or_trailing(self):
        with tempfile.TemporaryDirectory() as tmp:
            desk = paper.PaperDesk(Path(tmp) / "receipt")
            data = json.loads((ROOT / "fixtures" / "demo.json").read_text())
            desk.process({**data, "markets": [data["markets"][0]]})
            before = copy.deepcopy(desk.positions["BTCUSDT"])
            stale = {"symbol": "BTCUSDT", "price": "1", "source_time_utc": "2020-01-01T00:00:00+00:00"}
            desk.update_positions([stale], "PUBLIC_MARKET_READ_ONLY")
            self.assertEqual(desk.positions["BTCUSDT"], before)
            self.assertIn("BTCUSDT", desk.unverified_marks)
            self.assertTrue(any(e["action"] == "UNVERIFIED_POSITION_MARK" for e in desk.ledger))
            self.assertTrue(paper.verify_audit(desk.events_path))

    def test_naive_public_mark_cannot_activate_trailing(self):
        with tempfile.TemporaryDirectory() as tmp:
            desk = paper.PaperDesk(Path(tmp) / "receipt")
            data = json.loads((ROOT / "fixtures" / "demo.json").read_text())
            desk.process({**data, "markets": [data["markets"][0]]})
            old = copy.deepcopy(desk.positions["BTCUSDT"])
            bad = {"symbol": "BTCUSDT", "price": "90000", "source_time_utc": "2026-11-15T16:00:00"}
            desk.update_positions([bad], "PUBLIC_MARKET_READ_ONLY")
            self.assertEqual(desk.positions["BTCUSDT"], old)
            self.assertIn("BTCUSDT", desk.unverified_marks)
