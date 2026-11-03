"""
Corporate announcements / filings for the portfolio.

Primary feed: NSE corporate-announcements API (public JSON).
BSE has an equivalent (api.bseindia.com). Both are EOD-friendly.

Each raw filing is passed through classify.classify() + classify.priority(),
then a cheap model writes a one-line "why you should care" summary for the
material ones (routine filings get no LLM call — cost discipline).
"""
from __future__ import annotations
import re, hashlib
import datetime as dt
from urllib.parse import urlparse
import config, classify
from fiscal import parse_exchange_time, now_ist, IST

NSE_ANN_URL = "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={symbol}"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0", "Accept": "application/json",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
}


def _session():
    """NSE requires a cookie primed from the homepage before the API responds."""
    import requests
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    s.get("https://www.nseindia.com", timeout=10)  # prime cookies
    return s


# Filings link only to the exchanges' own archives; anything else is dropped.
ALLOWED_DOC_HOSTS = {"nsearchives.nseindia.com", "archives.nseindia.com", "www.nseindia.com",
                     "www.bseindia.com", "bseindia.com"}


def stable_id(symbol: str, when_iso: str, desc: str, attachment: str) -> str:
    """Deterministic across processes and restarts (unlike Python's salted hash())."""
    raw = "\x1f".join((symbol, when_iso or "", (desc or "").strip().lower(), attachment or ""))
    return f"{symbol}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def safe_doc_url(att: str | None) -> str | None:
    """Resolve an NSE attachment to an absolute https URL on an exchange host, or None."""
    if not att:
        return None
    if not att.startswith("http"):
        if not re.fullmatch(r"[\w./-]+", att) or ".." in att:   # plain archive path only
            return None
        att = "https://nsearchives.nseindia.com/corporate/" + att.lstrip("/")
    url = att
    u = urlparse(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_DOC_HOSTS:
        return None
    return url


def fetch_raw(symbol: str, since: dt.datetime, sess=None) -> list[dict]:
    sess = sess or _session()
    r = sess.get(NSE_ANN_URL.format(symbol=symbol), timeout=15)
    r.raise_for_status()
    items = r.json()
    items = items.get("data", []) if isinstance(items, dict) else items
    out, seen = [], set()
    for it in items:
        ts = it.get("an_dt") or it.get("sort_date")  # NSE field names vary
        when = parse_exchange_time(ts)                 # IST, explicitly
        if not when or when < since:
            continue
        aid = stable_id(symbol, when.isoformat(), it.get("desc"), it.get("attchmntFile"))
        if aid in seen:
            continue
        seen.add(aid)
        out.append({
            "id": aid,
            "ticker": symbol,
            "title": ((it.get("desc") or "") + " — " + (it.get("attchmntText") or "")).strip(" —")[:300],
            "body": (it.get("attchmntText") or "").strip(),
            "attachment": safe_doc_url(it.get("attchmntFile")),
            "time": when.isoformat(),
        })
    return out


def summarise(item: dict) -> str:
    """One-line 'why you should care' — only called for material (non-routine) filings."""
    from llm import complete
    prompt = (
        "In <=22 words, tell an investor why this filing matters. No fluff.\n"
        f"Company: {item['ticker']}  Category: {item['category']}\n"
        f"Filing: {item['title']}\n{item['body'][:800]}"
    )
    return complete(prompt, route="extract", max_tokens=80).strip()


def process(symbol: str, since: dt.datetime, sess=None) -> list[dict]:
    out = []
    for raw in fetch_raw(symbol, since, sess):
        cat = classify.classify(raw["title"], raw["body"])
        prio = classify.priority(cat, raw["title"])
        raw["category"], raw["priority"] = cat, prio
        try:
            raw["summary"] = summarise(raw) if prio != "routine" else "Routine filing."
        except Exception as e:   # no API key / rate limit: still surface the filing
            raw["summary"] = raw["title"][:140]
        if cat == "results":
            try:
                import fundamentals
                raw["results"] = fundamentals.results_from_screener(symbol, filing_url=raw.get("attachment"))
            except Exception as e:
                print(f"  ! results table {symbol}: {e}")
        out.append(raw)
    return out


def fetch_portfolio(tickers=None, window_hours: int = 72, report: dict | None = None) -> list[dict]:
    """Fetch + classify filings. If `report` is given it is filled with per-ticker
    coverage so callers can tell "no filings" apart from "fetch failed"."""
    tickers = tickers or config.PORTFOLIO
    since = now_ist() - dt.timedelta(hours=window_hours)
    sess = _session()
    all_items, ok, failed = [], [], {}
    for t in tickers:
        try:
            all_items += process(t, since, sess)
            ok.append(t)
        except Exception as e:
            failed[t] = str(e)[:200]
            print(f"  ! {t}: {e}")
    if report is not None:
        report.update({"requested": list(tickers), "ok": ok, "failed": failed})
    all_items.sort(key=lambda a: a["time"], reverse=True)   # the app sorts by priority itself
    return all_items


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_portfolio(config.PORTFOLIO[:2], 72), indent=2)[:2000])
