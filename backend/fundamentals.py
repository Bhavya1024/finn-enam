"""
Company fundamentals for the Pull side.

Two kinds of input, kept separate and labelled separately in the output:

  PRIMARY (company documents)        annual reports, concall transcripts, results filings
  STRUCTURED SECONDARY (screener.in) standardised P&L / balance-sheet / cash-flow tables

Screener is a convenience for discovery and for multi-period tables; it is a
restatement of the filings, not a filing. Every number that comes from it is
tagged `kind: "screener_table"`, and where the original results filing is
available, headline numbers are re-extracted from it and reconciled
(see reconcile_with_filing). No news, broker notes or research reports — see
config.PULL_BANNED.
"""
from __future__ import annotations
import re, json, time, pathlib, hashlib
from urllib.parse import urljoin
from dataclasses import dataclass, field
import config
from fiscal import period_from_column, fy_label_from_column, now_ist

SCREENER = "https://www.screener.in/company/{symbol}/consolidated/"
_CACHE = pathlib.Path(config.CACHE_DIR) / "docs"
_CACHE.mkdir(parents=True, exist_ok=True)


@dataclass
class Fundamentals:
    ticker: str
    url: str = ""
    retrieved_at: str = ""
    financials: dict = field(default_factory=dict)       # standardised tables, by section id
    annual_reports: list = field(default_factory=list)   # [{label, url}]
    transcripts: list = field(default_factory=list)      # [{label, url}]


# ---- fetching with a version-aware cache ---------------------------------------
def _cached_get(url: str, ttl_s: int | None = None) -> tuple[bytes, dict]:
    """GET with an on-disk cache keyed by URL but *versioned by content*.

    Each entry stores the body plus metadata: url, fetched_at, sha256 of the body,
    ETag / Last-Modified. After `ttl_s` the entry is revalidated with a conditional
    request (If-None-Match / If-Modified-Since); a 304 keeps the body, a 200 replaces
    it and the new content hash shows the document changed. If revalidation fails
    on the network, the stale copy is served and flagged `stale: True`.
    """
    ttl_s = config.HTML_TTL_S if ttl_s is None else ttl_s
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    body_p, meta_p = _CACHE / key, _CACHE / f"{key}.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() and body_p.exists() else None
    if meta and time.time() - meta.get("fetched_ts", 0) < ttl_s:
        return body_p.read_bytes(), {**meta, "cache": "hit"}

    import requests
    headers = {"User-Agent": "Mozilla/5.0"}
    if meta and meta.get("etag"):
        headers["If-None-Match"] = meta["etag"]
    if meta and meta.get("last_modified"):
        headers["If-Modified-Since"] = meta["last_modified"]
    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 304 and meta:
            meta.update(fetched_ts=time.time(), fetched_at=now_ist().isoformat())
            meta_p.write_text(json.dumps(meta))
            return body_p.read_bytes(), {**meta, "cache": "revalidated"}
        r.raise_for_status()
    except Exception:
        if meta:
            return body_p.read_bytes(), {**meta, "cache": "stale", "stale": True}
        raise
    digest = hashlib.sha256(r.content).hexdigest()
    new = {"url": url, "fetched_ts": time.time(), "fetched_at": now_ist().isoformat(),
           "sha256": digest, "bytes": len(r.content),
           "etag": r.headers.get("ETag"), "last_modified": r.headers.get("Last-Modified"),
           "changed": bool(meta and meta.get("sha256") != digest)}
    body_p.write_bytes(r.content)
    meta_p.write_text(json.dumps(new))
    return r.content, {**new, "cache": "miss"}


def fetch_fundamentals(symbol: str) -> Fundamentals:
    """Scrape the screener page for the standardised tables + document links.
       Tries the consolidated view first, then standalone."""
    from bs4 import BeautifulSoup
    for url in (SCREENER.format(symbol=symbol), SCREENER.format(symbol=symbol).replace("/consolidated/", "/")):
        body, meta = _cached_get(url)
        soup = BeautifulSoup(body.decode("utf-8", "ignore"), "html.parser")
        tables = _parse_tables(soup)
        if tables.get("quarters", {}).get("rows"):
            break
    else:
        raise ValueError(f"no screener data for {symbol}")
    f = Fundamentals(ticker=symbol, url=url, retrieved_at=meta.get("fetched_at", ""), financials=tables)
    h1 = soup.select_one("h1")
    f.financials["_name"] = h1.get_text(strip=True) if h1 else symbol
    docs = soup.select_one("section#documents") or soup
    for box in docs.select("div"):
        head = box.find(["h3", "h4"], recursive=False)
        if not head:
            continue
        kind = head.get_text(" ", strip=True).lower()
        for li in box.select("li"):
            for a in li.select("a[href]"):
                href, txt = urljoin(url, a["href"]), a.get_text(" ", strip=True)
                label = (li.get_text(" ", strip=True) or txt)[:60]
                if "annual" in kind:
                    f.annual_reports.append({"label": label, "url": href})
                elif "concall" in kind and re.search(r"transcript", txt, re.I):
                    f.transcripts.append({"label": label, "url": href})
    return f


def _parse_tables(soup) -> dict:
    """Pull every titled table (quarters, profit-loss, balance-sheet, cash-flow, ratios)
    into {"columns": [...], "rows": {name: [values...]}}."""
    tables = {}
    for section in soup.select("section[id]"):
        sid = section.get("id", "")
        tbl = section.select_one("table")
        if not tbl:
            continue
        rows = {}
        header = [th.get_text(strip=True) for th in tbl.select("thead th")][1:]
        for tr in tbl.select("tbody tr"):
            cells = tr.select("td")
            if not cells:
                continue
            name = cells[0].get_text(strip=True).rstrip("\xa0 +")
            rows[name] = [_num(c.get_text(strip=True)) for c in cells[1:]]
        tables[sid] = {"columns": header, "rows": rows}
    return tables


def _num(s: str):
    s = s.replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def row(tbl: dict, *names) -> list:
    """First row whose label starts with any of `names` (case-insensitive); [] if absent."""
    for n in names:
        for k, v in tbl.get("rows", {}).items():
            if k.lower().startswith(n.lower()):
                return v
    return []


_row = row   # backwards-compatible alias


def quarter_labels(tbl: dict) -> list[str]:
    """Screener 'Sep 2026' -> 'Q2 FY27' (April–March fiscal year)."""
    out = []
    for c in tbl.get("columns", []):
        p = period_from_column(c)
        out.append(p.label if p else c)
    return out


def year_labels(tbl: dict) -> list[str]:
    return [fy_label_from_column(c) for c in tbl.get("columns", [])]


def screener_source(f: Fundamentals, table: str) -> dict:
    return {"kind": "screener_table", "label": f"Screener.in standardised {table} table",
            "note": "secondary restatement of company filings", "url": f.url,
            "retrieved_at": f.retrieved_at}


# ---- documents ----------------------------------------------------------------
def download_pdf_text(url: str) -> tuple[str, dict]:
    """Fetch a PDF (AR, transcript, results filing) and return (text, fetch-metadata).
    Text keeps page markers ("[p.12]") so quotes can be cited by page."""
    import io
    from pypdf import PdfReader
    data, meta = _cached_get(url, ttl_s=config.DOC_TTL_S)
    reader = PdfReader(io.BytesIO(data))
    pages = [f"[p.{i}]\n{pg.extract_text() or ''}" for i, pg in enumerate(reader.pages, 1)]
    return "\n".join(pages), meta


def latest_transcripts(f: Fundamentals, n: int = 4) -> list[dict]:
    """Text of the last n concall transcripts (newest first), with provenance."""
    out = []
    for t in f.transcripts[:n]:
        try:
            text, meta = download_pdf_text(t["url"])
            out.append({"label": t["label"], "url": t["url"], "text": text,
                        "sha256": meta.get("sha256"), "retrieved_at": meta.get("fetched_at")})
        except Exception as e:
            print(f"  ! transcript {t['label']}: {e}")
    return out


# ---- results-filing table (push side) -------------------------------------------
def results_from_screener(symbol: str, filing_url: str | None = None):
    """Headline Revenue/EBITDA/PBT/PAT for the latest quarter, the prior quarter and
    the year-ago quarter, from Screener's standardised table. If the original results
    filing is available, the latest-quarter numbers are reconciled against it.
    Lenders get NII / financing profit instead of EBITDA."""
    f = fetch_fundamentals(symbol); q = f.financials["quarters"]; cols = q["columns"]
    if len(cols) < 5:
        return None
    labels = quarter_labels(q)
    idx = [-5, -2, -1]
    lender = is_lender(symbol, f)
    spec = (("Revenue", ("Revenue", "Sales")), ("Net interest income", None),
            ("Financing profit", ("Financing Profit",)), ("PBT", ("Profit before tax",)),
            ("PAT", ("Net Profit",))) if lender else \
           (("Revenue", ("Sales", "Revenue")), ("EBITDA", ("Operating Profit",)),
            ("PBT", ("Profit before tax",)), ("PAT", ("Net Profit",)))
    rows = []
    for label, keys in spec:
        if keys is None:   # NII = interest earned − interest expended
            rev, intr = row(q, "Revenue"), row(q, "Interest")
            v = [None if a is None or b is None else a - b for a, b in zip(rev, intr)]
        else:
            v = row(q, *keys)
        if len(v) == len(cols) and all(v[i] is not None for i in idx):
            rows.append({"metric": label, "values": [v[i] for i in idx]})
    if not rows:
        return None
    out = {"quarters": [labels[i] for i in idx], "rows": rows,
           "basis": "lender" if lender else "operating",
           "source": screener_source(f, "quarterly results")}
    if not lender:
        opm = row(q, "OPM")
        if len(opm) == len(cols) and all(opm[i] is not None for i in idx):
            out["ebitda_margin"] = [opm[i] for i in idx]
    if filing_url:
        out["reconciliation"] = reconcile_with_filing(filing_url, labels[-1], rows)
    return out


def reconcile_with_filing(filing_url: str, quarter: str, rows: list[dict], tol_pct: float = 1.0) -> dict:
    """Re-extract headline numbers from the company's own results filing and compare
    them to the structured table. Status per metric: matched / mismatch / unverified."""
    from llm import complete_json
    try:
        text, meta = download_pdf_text(filing_url)
        got = complete_json(
            "From this Indian listed-company results filing, extract CONSOLIDATED figures for "
            f"the quarter {quarter}, in Rs crore. Keys: revenue, ebitda, pbt, pat. Use null "
            "for anything not stated. Also return 'page' for where you found revenue.\n\n"
            + text[:12000], route="extract", max_tokens=1024)
    except Exception as e:
        return {"status": "unverified", "reason": f"filing not parsed: {str(e)[:120]}",
                "filing_url": filing_url}
    keymap = {"Revenue": "revenue", "EBITDA": "ebitda", "PBT": "pbt", "PAT": "pat"}
    checks = []
    for r in rows:
        k = keymap.get(r["metric"])
        filed, table = (got.get(k) if k else None), r["values"][-1]
        if not isinstance(filed, (int, float)):
            checks.append({"metric": r["metric"], "status": "unverified"})
            continue
        diff = abs(filed - table) / abs(filed) * 100 if filed else None
        checks.append({"metric": r["metric"], "filing": filed, "table": table,
                       "status": "matched" if diff is not None and diff <= tol_pct else "mismatch"})
    statuses = {c["status"] for c in checks}
    return {"status": "mismatch" if "mismatch" in statuses else
                      "matched" if statuses == {"matched"} else "partial",
            "checks": checks, "filing_url": filing_url, "filing_sha256": meta.get("sha256"),
            "page": got.get("page")}


def is_lender(symbol: str, f: Fundamentals | None = None) -> bool:
    if symbol in config.LENDERS:
        return True
    if f is not None:
        q = f.financials.get("quarters", {})
        return bool(row(q, "Financing Profit") or row(q, "Financing Margin"))
    return False


if __name__ == "__main__":
    f = fetch_fundamentals("DIXON")
    print("financial sections:", list(f.financials.keys()))
    print("annual reports:", len(f.annual_reports), "| transcripts:", len(f.transcripts))
