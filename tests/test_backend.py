"""Backend tests — no network, no API key, no third-party packages.

    python -m unittest discover -s tests -v
"""
import datetime as dt
import json, os, pathlib, subprocess, sys, threading, types, unittest, urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("FINN_CACHE_DIR", str(ROOT / ".cache-test"))

import fiscal, finmath, commitments, fetch_announcements  # noqa: E402
from fiscal import Period  # noqa: E402


class Fiscal(unittest.TestCase):
    def test_quarter_mapping(self):
        self.assertEqual(fiscal.period_of(dt.date(2026, 9, 30)).label, "Q2 FY27")
        self.assertEqual(fiscal.period_of(dt.date(2026, 4, 1)).label, "Q1 FY27")
        self.assertEqual(fiscal.period_of(dt.date(2027, 3, 31)).label, "Q4 FY27")
        self.assertEqual(fiscal.period_of(dt.date(2026, 12, 31)).label, "Q3 FY27")

    def test_screener_columns(self):
        self.assertEqual(fiscal.period_from_column("Sep 2026").label, "Q2 FY27")
        self.assertEqual(fiscal.period_from_column("Mar 2026").label, "Q4 FY26")
        self.assertEqual(fiscal.fy_label_from_column("Mar 2026"), "FY26")

    def test_year_ago_and_shift(self):
        p = Period(2027, 1)
        self.assertEqual(p.year_ago.label, "Q1 FY26")
        self.assertEqual(p.shift(-1).label, "Q4 FY26")

    def test_horizons(self):
        said = Period(2027, 1)
        self.assertEqual(fiscal.horizon_end("FY27", said).label, "Q4 FY27")
        self.assertEqual(fiscal.horizon_end("FY27 exit", said).label, "Q4 FY27")
        self.assertEqual(fiscal.horizon_end("H1 FY27", said).label, "Q2 FY27")
        self.assertEqual(fiscal.horizon_end("next quarter", said).label, "Q2 FY27")
        self.assertEqual(fiscal.horizon_end("next year", said).label, "Q4 FY28")
        self.assertIsNone(fiscal.horizon_end("soon", said))

    def test_exchange_time_is_ist_regardless_of_server_tz(self):
        code = ("import sys; sys.path.insert(0,'backend'); import fiscal;"
                "print(fiscal.parse_exchange_time('02-Nov-2026 18:30:00').isoformat())")
        for tz in ("UTC", "America/New_York", "Asia/Kolkata"):
            out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                                 env={**os.environ, "TZ": tz}).stdout.strip()
            self.assertEqual(out, "2026-11-02T18:30:00+05:30", tz)


class FinMath(unittest.TestCase):
    def test_pct_change_denominators(self):
        self.assertAlmostEqual(finmath.pct_change(110, 100), 10)
        self.assertIsNone(finmath.pct_change(50, 0))
        self.assertIsNone(finmath.pct_change(50, -20))      # recovery from a loss is not a %
        self.assertIsNone(finmath.pct_change(None, 100))

    def test_missing_stays_missing(self):
        self.assertIsNone(finmath.cash_conversion(None, 100))
        self.assertIsNone(finmath.cash_conversion(80, 0))
        self.assertIsNone(finmath.cash_conversion(80, -5))
        self.assertEqual(finmath.fmt_num(None), "n/a")
        self.assertEqual(finmath.fmt_pct_change(None), "n.m.")

    def test_leverage_and_working_capital(self):
        eq = finmath.total_equity(100, 900)
        self.assertEqual(eq, 1000)
        self.assertAlmostEqual(finmath.debt_to_equity(500, eq), 0.5)
        self.assertIsNone(finmath.debt_to_equity(500, -10))
        self.assertEqual(finmath.net_working_capital(60, 40, 70), 30)   # payables included
        self.assertIsNone(finmath.net_working_capital(60, 40, None))


class Announcements(unittest.TestCase):
    def test_stable_id_survives_hash_randomisation(self):
        code = ("import sys; sys.path.insert(0,'backend'); import fetch_announcements as f;"
                "print(f.stable_id('DIXON','2026-11-02T07:55:00+05:30','Outcome of board meeting','a.pdf'))")
        ids = {subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                              env={**os.environ, "PYTHONHASHSEED": seed}).stdout.strip() for seed in ("1", "2", "99")}
        self.assertEqual(len(ids), 1)
        self.assertTrue(next(iter(ids)).startswith("DIXON-"))

    def test_doc_urls_restricted_to_exchanges(self):
        f = fetch_announcements.safe_doc_url
        self.assertEqual(f("abc.pdf"), "https://nsearchives.nseindia.com/corporate/abc.pdf")
        self.assertIsNone(f("https://evil.example.com/x.pdf"))
        self.assertIsNone(f("javascript:alert(1)"))
        self.assertIsNone(f("http://nsearchives.nseindia.com/x.pdf"))


SERIES = {"periods": ["Q3 FY25", "Q4 FY25", "Q1 FY26", "Q2 FY26", "Q3 FY26", "Q4 FY26", "Q1 FY27", "Q2 FY27"],
          "revenue": [100, 100, 100, 100, 110, 120, 130, 140],
          "ebitda": [10, 10, 10, 10, 11, 12, 13, 14],
          "pat": [5, 5, 5, 5, 6, 6, 7, 8]}


def c(**kw):
    base = dict(metric="revenue", direction="at_least", target_low=None, target_high=None,
                horizon="Q4 FY26", said_in="Q3 FY26", quote="Management said something specific here.")
    base.update(kw)
    return commitments.normalize(base, base["said_in"], {"kind": "concall_transcript"})


class Ledger(unittest.TestCase):
    def ev(self, com):
        return commitments.evaluate(com, commitments.Series(SERIES))

    def test_quarter_target_achieved_and_exceeded(self):
        self.assertEqual(self.ev(c(target_low=118))["status"], "achieved")
        self.assertEqual(self.ev(c(target_low=100))["status"], "exceeded")
        self.assertEqual(self.ev(c(target_low=125))["status"], "missed")

    def test_full_year_uses_all_four_quarters(self):
        r = self.ev(c(horizon="FY26", said_in="Q1 FY26", target_low=430))   # FY26 = 100+100+110+120
        self.assertEqual(r["actual_period"], "FY26")
        self.assertEqual(r["actual"], 430)
        self.assertEqual(r["status"], "achieved")

    def test_future_horizon_is_in_progress_never_scored(self):
        r = self.ev(c(horizon="FY27", said_in="Q1 FY27", target_low=600))
        self.assertEqual(r["status"], "in_progress")
        self.assertEqual(r["interim"]["value"], 270)        # YTD Q1+Q2
        self.assertEqual(r["interim"]["run_rate"], 540)

    def test_exit_rate_uses_final_quarter(self):
        com = c(metric="ebitda_margin", horizon="FY26 exit", said_in="Q1 FY26", target_low=10)
        self.assertEqual(com.basis, "exit")
        self.assertEqual(self.ev(com)["actual"], 10.0)

    def test_growth_compares_same_window_a_year_earlier(self):
        r = self.ev(c(metric="revenue_growth_yoy", horizon="H1 FY27", said_in="Q4 FY26", target_low=30))
        self.assertAlmostEqual(r["actual"], 35.0)            # (130+140)/(100+100)
        self.assertEqual(r["status"], "exceeded")

    def test_unscoreable_commitments_are_flagged(self):
        self.assertEqual(self.ev(c(metric="other", target_low=5))["status"], "not_evaluable")
        self.assertEqual(self.ev(c(horizon="someday", target_low=5))["status"], "not_evaluable")
        self.assertEqual(self.ev(c(direction="at_least"))["status"], "not_evaluable")   # no target

    def test_incomplete_data_is_pending(self):
        r = self.ev(c(metric="revenue_growth_yoy", horizon="FY26", said_in="Q1 FY26", target_low=5))
        self.assertEqual(r["status"], "pending")             # FY25 Q1/Q2 missing

    def test_quote_located_by_page(self):
        text = "[p.1]\nIntro.\n[p.2]\nWe expect EBITDA margins to reach 4.5% by FY27 exit.\n"
        self.assertEqual(commitments.locate_quote("We expect EBITDA margins to reach 4.5% by FY27 exit.", text), 2)
        self.assertIsNone(commitments.locate_quote("We expect margins of 9%.", text))


class SampleData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = json.loads((ROOT / "data" / "finn_data.json").read_text(encoding="utf-8"))

    def test_fiscal_labels_match_calendar(self):
        blob = json.dumps(self.d)
        self.assertNotIn("Q2 FY26 (quarter ended Sep 2026)", blob)
        self.assertIn("Q2 FY27", self.d["research"]["DIXON"]["as_of"])

    def test_lender_not_shown_on_ebitda(self):
        b = next(a for a in self.d["announcements"] if a["ticker"] == "BAJFINANCE" and a.get("results"))
        self.assertEqual(b["results"]["basis"], "lender")
        self.assertNotIn("ebitda_margin", b["results"])
        self.assertNotIn("EBITDA", [r["metric"] for r in b["results"]["rows"]])

    def test_sample_ledgers_are_engine_scored(self):
        counts = {tk: commitments.build_ledger(r["commitments"], r["series"])["counts"]
                  for tk, r in self.d["research"].items()}
        self.assertEqual(counts["ASIANPAINT"]["missed"], 3)
        self.assertEqual(counts["DIXON"]["missed"], 0)
        self.assertGreaterEqual(counts["INFY"]["not_evaluable"], 1)   # constant-currency guidance

    def test_every_source_starts_as_sample(self):
        self.assertEqual({v["state"] for v in self.d["meta"]["sources"].values()}, {"sample"})


class Server(unittest.TestCase):
    """Runs serve.py's handler on an ephemeral port with fake data sources."""

    @classmethod
    def setUpClass(cls):
        import serve
        cls.serve = serve
        cls.httpd = serve.Server(("127.0.0.1", 0), serve.H)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, path):
        try:
            with self.OPENER.open(self.base + path) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def fake(self, prices, failed, anns, ann_report):
        sys.modules["ingest_prices"] = types.SimpleNamespace(ingest_portfolio=lambda: {
            "prices": prices, "price_alerts": [], "requested": ["AAA", "BBB"], "failed": failed})
        def fetch_portfolio(window_hours=72, report=None):
            report.update(ann_report)
            return anns
        sys.modules["fetch_announcements"] = types.SimpleNamespace(fetch_portfolio=fetch_portfolio)
        self.serve.STATE["next"] = {"prices": 0, "announcements": 0}

    def tearDown(self):
        sys.modules["fetch_announcements"] = fetch_announcements
        sys.modules.pop("ingest_prices", None)

    def test_only_app_and_api_are_served(self):
        for p in ("/data/finn_data.json", "/backend/config.py", "/.cache/x", "/README.md", "/../etc/passwd"):
            self.assertEqual(self.get(p)[0], 404, p)

    def test_ticker_validation(self):
        self.assertEqual(self.get("/api/research/%3Cscript%3E")[0], 400)
        self.assertEqual(self.get("/api/history/..%2F..%2Fetc")[0], 400)
        self.assertEqual(self.get("/api/history/DIXON?range=10y")[0], 400)

    def test_partial_prices_and_empty_announcements(self):
        self.fake(prices=[{"ticker": "AAA", "price": 1.0, "chg_pct": 0.1}], failed={"BBB": "timeout"},
                  anns=[], ann_report={"requested": ["AAA", "BBB"], "ok": ["AAA", "BBB"], "failed": {}})
        d = json.loads(self.get("/api/data")[1])
        self.assertEqual(d["meta"]["sources"]["prices"]["state"], "partial")
        self.assertEqual(d["meta"]["sources"]["prices"]["coverage"], "1/2")
        self.assertEqual(d["meta"]["sources"]["announcements"]["state"], "live")   # zero filings is still live
        self.assertEqual(d["announcements"], [])

    def test_research_includes_scored_ledger(self):
        r = json.loads(self.get("/api/research/ASIANPAINT")[1])
        self.assertEqual(r["ledger"]["counts"]["missed"], 3)

    def test_total_failure_is_not_live(self):
        self.fake(prices=[], failed={"AAA": "x", "BBB": "y"}, anns=[],
                  ann_report={"requested": ["AAA"], "ok": [], "failed": {"AAA": "blocked"}})
        self.serve.STATE["data"]["meta"]["sources"] = {}
        d = json.loads(self.get("/api/data")[1])
        self.assertEqual(d["meta"]["sources"]["prices"]["state"], "failed")
        self.assertEqual(d["meta"]["sources"]["announcements"]["state"], "failed")
        self.assertNotEqual(d["meta"].get("generated_at"), d["meta"].get("served_at"))


if __name__ == "__main__":
    unittest.main()
