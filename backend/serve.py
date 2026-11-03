#!/usr/bin/env python3
"""FINN live server:  python backend/serve.py  ->  http://127.0.0.1:8000

Serves exactly two things — the built app (index.html) and a JSON API:
  GET /api/data              portfolio + filings, each with an honest per-source status
  GET /api/history/<TKR>     daily close/volume (range=1mo|3mo|6mo|1y)
  GET /api/research/<TKR>    pull-side analysis for any NSE ticker (cached)
Nothing else in the repository (cache, data files, .env) is reachable over HTTP.

Binds to 127.0.0.1 by default. For a phone demo on a trusted LAN:
  FINN_HOST=0.0.0.0 python backend/serve.py
There is no authentication — never expose this to the internet.
"""
from __future__ import annotations
import copy, json, os, re, sys, time, threading, socketserver
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(__file__))
import config, build_data, commitments
from fiscal import now_ist

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INDEX = os.path.join(ROOT, "index.html")
DATA_FILE = os.path.join(config.DATA_DIR, "finn_data.json")
TICKER = re.compile(config.TICKER_RE)
RANGES = {"1mo", "3mo", "6mo", "1y"}
LOCK = threading.Lock()
TTL = {"prices": 60, "announcements": 300}
RETRY_AFTER_FAIL = {"prices": 15, "announcements": 60}

STATE = {"data": commitments.attach_ledgers(build_data._load(DATA_FILE)), "next": {"prices": 0, "announcements": 0}}


def _init_sources(d: dict) -> dict:
    """Every source starts as 'sample' — only a successful refresh can change that."""
    src = d.setdefault("meta", {}).setdefault("sources", {})
    for k in ("prices", "announcements"):
        src.setdefault(k, {"state": "sample", "as_of": d["meta"].get("generated_at"),
                           "detail": "Shipped sample snapshot"})
    return src


def _set_status(src: dict, key: str, ok: list, failed: dict, requested: list, count: int | None = None):
    now = now_ist().isoformat()
    n_ok, n_req = len(ok), len(requested)
    prev = src.get(key, {})
    if n_ok == 0:
        # Nothing fresh: keep whatever we were showing, but say the refresh failed.
        src[key] = {**prev, "state": "failed" if prev.get("state") in (None, "sample", "failed") else "stale",
                    "last_error": next(iter(failed.values()), "no data returned"), "attempted_at": now,
                    "coverage": f"0/{n_req}"}
        return
    src[key] = {"state": "live" if n_ok == n_req else "partial", "as_of": now, "attempted_at": now,
                "coverage": f"{n_ok}/{n_req}", "failed": sorted(failed)[:20],
                **({"count": count} if count is not None else {}),
                "detail": "All tickers refreshed" if n_ok == n_req else f"{n_req - n_ok} ticker(s) failed"}


def _age_out(src: dict):
    """A 'live' source that hasn't refreshed recently is downgraded to 'stale'."""
    import datetime as dt
    for key, s in src.items():
        if s.get("state") in ("live", "partial") and s.get("as_of"):
            age = (now_ist() - dt.datetime.fromisoformat(s["as_of"])).total_seconds()
            if age > config.STALE_AFTER_S.get(key, 3600):
                s["state"] = "stale"


def refresh() -> dict:
    with LOCK:
        now, d = time.time(), STATE["data"]
        src = _init_sources(d)
        if now >= STATE["next"]["prices"]:
            try:
                import ingest_prices
                res = ingest_prices.ingest_portfolio()
                fresh = {p["ticker"] for p in res["prices"]}
                d["portfolio"] = build_data._merge_prices(d.get("portfolio", []), res["prices"])
                for p in d["portfolio"]:   # per-row provenance so the UI can mark stale rows
                    p["live"] = p["ticker"] in fresh
                _set_status(src, "prices", sorted(fresh), res["failed"], res["requested"])
                STATE["next"]["prices"] = now + (TTL["prices"] if fresh else RETRY_AFTER_FAIL["prices"])
            except Exception as e:
                print("prices failed:", e)
                _set_status(src, "prices", [], {"*": str(e)[:200]}, list(config.PORTFOLIO))
                STATE["next"]["prices"] = now + RETRY_AFTER_FAIL["prices"]
        if now >= STATE["next"]["announcements"]:
            try:
                import fetch_announcements
                report = {}
                a = fetch_announcements.fetch_portfolio(window_hours=72, report=report)
                if report.get("ok"):
                    names = {p["ticker"]: p.get("name", p["ticker"]) for p in d.get("portfolio", [])}
                    for x in a:
                        x["name"] = names.get(x["ticker"], x["ticker"])
                    d["announcements"] = a   # zero filings is a valid live answer
                _set_status(src, "announcements", report.get("ok", []), report.get("failed", {}),
                            report.get("requested", []), count=len(a))
                STATE["next"]["announcements"] = now + (TTL["announcements"] if report.get("ok")
                                                        else RETRY_AFTER_FAIL["announcements"])
            except Exception as e:
                print("announcements failed:", e)
                _set_status(src, "announcements", [], {"*": str(e)[:200]}, list(config.PORTFOLIO))
                STATE["next"]["announcements"] = now + RETRY_AFTER_FAIL["announcements"]
        _age_out(src)
        d["meta"]["served_at"] = now_ist().isoformat()   # when this response was built — not data freshness
        return copy.deepcopy(d)


class H(BaseHTTPRequestHandler):
    server_version = "FINN"

    def _send(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", code)

    def do_GET(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        if u.path in ("/", "/index.html"):
            try:
                with open(INDEX, "rb") as fh:
                    return self._send(fh.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                return self._json({"error": "index.html not built — run python web/build.py"}, 500)
        if parts[:2] == ["api", "data"] and len(parts) == 2:
            return self._json(refresh())
        if len(parts) == 3 and parts[0] == "api" and parts[1] in ("history", "research"):
            tk = parts[2].upper()
            if not TICKER.match(tk):
                return self._json({"error": "invalid ticker"}, 400)
            return self._history(tk, parse_qs(u.query)) if parts[1] == "history" else self._research(tk)
        return self._json({"error": "not found"}, 404)

    def _history(self, tk, qs):
        rng = (qs.get("range") or ["3mo"])[0]
        if rng not in RANGES:
            return self._json({"error": "invalid range"}, 400)
        try:
            import yfinance as yf
            h = yf.Ticker(tk + config.YF_SUFFIX).history(period=rng, interval="1d")
            if h is None or h.empty:
                return self._json({"error": "no history"}, 404)
            return self._json({"t": [d.strftime("%Y-%m-%d") for d in h.index],
                               "c": [round(float(x), 2) for x in h["Close"]],
                               "v": [int(x) for x in h["Volume"]], "source": "Yahoo Finance (EOD)"})
        except Exception as e:
            return self._json({"error": str(e)[:200]}, 502)

    def _research(self, tk):
        with LOCK:
            have = STATE["data"].setdefault("research", {}).get(tk)
        if have:
            return self._json(have)
        try:
            import analyze
            r = analyze.build_research(tk)
        except Exception as e:
            return self._json({"error": str(e)[:200]}, 502)
        with LOCK:
            STATE["data"]["research"][tk] = r
        return self._json(r)

    def log_message(self, fmt, *args):   # quieter console
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # HTTPServer.server_bind does a reverse-DNS lookup (socket.getfqdn) that can
        # stall for tens of seconds on some networks; the name is never used here.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = str(self.server_address[0]), self.server_address[1]


def main():
    _init_sources(STATE["data"])
    srv = Server((config.HOST, config.PORT), H)
    print(f"FINN live → http://{config.HOST}:{config.PORT}")
    if config.HOST not in ("127.0.0.1", "localhost", "::1"):
        print("  ! listening beyond loopback without authentication — trusted networks only")
    srv.serve_forever()


if __name__ == "__main__":
    main()
