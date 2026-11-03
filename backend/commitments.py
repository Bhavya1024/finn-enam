"""
Management Commitment Ledger — promised vs delivered, evaluated deterministically.

Division of labour:
  • The LLM only EXTRACTS: it reads a concall transcript and returns candidate
    commitments (metric, target, direction, horizon, exact quote).
  • normalize() validates each candidate: known metric, numeric target, a horizon
    that maps to a fiscal quarter, and a quote that really appears in the transcript
    (with its page). Anything that fails is kept but marked not evaluable — never
    silently scored.
  • evaluate() compares the normalised commitment to reported numbers for the
    *right period*: a full-year target is judged on the four quarters of that FY,
    an exit-rate target on the final quarter, a quarterly target on that quarter.
    Before the horizon is reached the commitment is "in_progress" with an interim
    reading (year-to-date), never a verdict.

Statuses:  exceeded · achieved · missed · in_progress · pending · not_evaluable
"""
from __future__ import annotations
import re, hashlib
from dataclasses import dataclass, field, asdict
from typing import Optional
from fiscal import Period, parse_period, horizon_end
from finmath import pct_change, margin

# Metrics the engine can compute from a quarterly revenue / EBITDA / PAT series.
METRICS = {
    "revenue":            {"label": "Revenue",           "unit": "cr", "higher_is_better": True},
    "revenue_growth_yoy": {"label": "Revenue growth YoY", "unit": "%",  "higher_is_better": True},
    "ebitda_margin":      {"label": "EBITDA margin",     "unit": "%",  "higher_is_better": True},
    "ebit_margin":        {"label": "Operating (EBIT) margin", "unit": "%", "higher_is_better": True},
    "pat":                {"label": "PAT",               "unit": "cr", "higher_is_better": True},
    "pat_growth_yoy":     {"label": "PAT growth YoY",    "unit": "%",  "higher_is_better": True},
}
DIRECTIONS = {"at_least", "at_most", "range", "increase", "decrease"}

# "Exceeded" = beat the target by more than this share of its value
# (with a floor in absolute units for percentage metrics: 0.25 pp).
EXCEED_REL, EXCEED_ABS_PCT = 0.05, 0.25


@dataclass
class Commitment:
    metric: str                       # key in METRICS, or free text if not evaluable
    direction: str                    # at_least | at_most | range | increase | decrease
    target_low: Optional[float]
    target_high: Optional[float]
    horizon: str                      # as said: "FY27", "FY27 exit", "Q3 FY27", "H2 FY27"
    said_in: str                      # quarter of the call, e.g. "Q1 FY27"
    quote: str
    source: dict = field(default_factory=dict)   # {kind, label, url, page}
    basis: str = ""                   # quarter | half | full_year | exit (derived)
    horizon_end: str = ""             # derived, e.g. "Q4 FY27"
    quote_verified: Optional[bool] = None
    id: str = ""
    issues: list = field(default_factory=list)
    note: str = ""                    # analyst/extractor note, e.g. why it can't be scored
    label: str = ""                   # human name for metrics outside METRICS ("Volume growth")

    def to_dict(self):
        return asdict(self)


# ---- 1. extraction (cheap model) ------------------------------------------------
EXTRACT_PROMPT = """Extract every QUANTIFIED forward-looking commitment management makes in this
earnings-call transcript chunk (revenue, revenue growth, EBITDA margin, PAT, PAT growth).
Skip vague optimism. For each, return:
  metric: one of revenue | revenue_growth_yoy | ebitda_margin | ebit_margin | pat | pat_growth_yoy | other
          (use ebit_margin when management says "operating margin" or "EBIT margin";
           constant-currency or segment targets are "other")
  direction: at_least | at_most | range | increase | decrease
  target_low, target_high: numbers (Rs crore for amounts, percent for % metrics); null if n/a
  horizon: the period exactly as stated, e.g. "FY27", "FY27 exit", "Q3 FY27", "H2 FY27", "next quarter"
  label: short human name of the metric (e.g. "Volume growth", "Constant-currency revenue growth")
  quote: the exact sentence, copied verbatim
Return {"items": [...]}. Return {"items": []} if there are none.
Call quarter: {said_in}
Transcript chunk:
{chunk}"""


def extract(transcript_text: str, said_in: str, source: dict, chunk_size: int = 6000) -> list[Commitment]:
    from llm import complete_json
    out = []
    for i in range(0, max(len(transcript_text), 1), chunk_size):
        ch = transcript_text[i:i + chunk_size]
        if not _has_guidance_cue(ch):
            continue
        res = complete_json(EXTRACT_PROMPT.replace("{said_in}", said_in).replace("{chunk}", ch),
                            route="extract", max_tokens=2048)
        for it in (res.get("items", []) if isinstance(res, dict) else []):
            out.append(normalize(it, said_in, source, transcript_text))
    return dedupe(out)


_CUES = ("guid", "expect", "target", "we aim", "going forward", "outlook", "by the end of",
         "exit", "margin", "growth", "crore")


def _has_guidance_cue(chunk: str) -> bool:
    c = chunk.lower()
    return any(k in c for k in _CUES)


# ---- 2. normalisation / validation ---------------------------------------------
def normalize(raw: dict, said_in: str, source: dict, transcript_text: str | None = None) -> Commitment:
    c = Commitment(
        metric=str(raw.get("metric") or "other").strip(),
        direction=str(raw.get("direction") or "").strip(),
        target_low=_f(raw.get("target_low")), target_high=_f(raw.get("target_high")),
        horizon=str(raw.get("horizon") or "").strip(), said_in=said_in,
        quote=str(raw.get("quote") or "").strip(), source=dict(source or {}),
        note=str(raw.get("note") or "").strip(), label=str(raw.get("label") or "").strip())
    if c.metric not in METRICS:
        c.issues.append("metric not computable from reported tables")
    if c.direction not in DIRECTIONS:
        c.issues.append("unrecognised direction")
    if c.direction == "range" and c.target_low is not None and c.target_high is not None \
            and c.target_low > c.target_high:
        c.target_low, c.target_high = c.target_high, c.target_low
    if c.direction in ("at_least", "range") and c.target_low is None:
        c.issues.append("no numeric target")
    if c.direction == "at_most" and c.target_high is None and c.target_low is not None:
        c.target_high = c.target_low
    if c.direction == "at_most" and c.target_high is None:
        c.issues.append("no numeric target")

    said = parse_period(said_in)
    end = horizon_end(c.horizon, said)
    if end is None:
        c.issues.append("horizon could not be mapped to a fiscal period")
    else:
        c.horizon_end = end.label
        c.basis = _basis(c.horizon, c.metric)
        if said and end < said:
            c.issues.append("horizon precedes the call")

    if transcript_text is not None:
        page = locate_quote(c.quote, transcript_text)
        c.quote_verified = page is not None
        if page:
            c.source["page"] = page
        else:
            c.issues.append("quote not found verbatim in transcript")
    c.id = _id(c)
    return c


def _basis(horizon: str, metric: str) -> str:
    h = horizon.lower()
    if "exit" in h:
        return "exit"
    if parse_period(horizon) or "quarter" in h:
        return "quarter"
    if re.search(r"\bh[12]\b", h):
        return "half"
    return "full_year"


def locate_quote(quote: str, text: str) -> Optional[int]:
    """Page number where `quote` occurs (whitespace/quote-mark insensitive), else None.
    Expects page markers like "[p.12]" as written by fundamentals.download_pdf_text."""
    def norm(s):
        return re.sub(r"\s+", " ", re.sub(r"[\"'“”‘’]", "", s)).strip().lower()
    q = norm(quote)
    if len(q) < 12:
        return None
    page, buf = 1, []
    for part in re.split(r"(\[p\.\d+\])", text):
        m = re.fullmatch(r"\[p\.(\d+)\]", part)
        if m:
            page = int(m.group(1))
            continue
        buf.append((page, norm(part)))
    # check page by page, then across page boundaries
    for p, t in buf:
        if q in t:
            return p
    joined = " ".join(t for _, t in buf)
    if q in joined:
        return buf[0][0] if buf else 1
    return None


def dedupe(items: list[Commitment]) -> list[Commitment]:
    seen, out = set(), []
    for c in items:
        if c.id not in seen:
            seen.add(c.id)
            out.append(c)
    return out


def _id(c: Commitment) -> str:
    raw = "|".join(map(str, (c.said_in, c.metric, c.direction, c.target_low, c.target_high,
                             c.horizon_end or c.horizon)))
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _f(x):
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


# ---- 3. actuals for a period ---------------------------------------------------
class Series:
    """Quarterly reported numbers keyed by fiscal period.
    `data` = {"periods": ["Q3 FY25", ...], "revenue": [...], "ebitda": [...], "pat": [...]}"""

    def __init__(self, data: dict):
        self.periods = [parse_period(p) for p in data.get("periods", [])]
        self.v = {k: dict(zip(self.periods, data.get(k, []))) for k in ("revenue", "ebitda", "ebit", "pat")}
        self.source = data.get("source", {})

    @property
    def latest(self) -> Optional[Period]:
        ps = [p for p in self.periods if p and self.v["revenue"].get(p) is not None]
        return max(ps) if ps else None

    def total(self, key: str, periods: list[Period]) -> Optional[float]:
        vals = [self.v[key].get(p) for p in periods]
        return None if not vals or any(x is None for x in vals) else sum(vals)

    def value(self, metric: str, periods: list[Period]) -> Optional[float]:
        """Metric over a set of quarters (one quarter, a half, a year or YTD)."""
        if metric == "revenue":
            return self.total("revenue", periods)
        if metric == "pat":
            return self.total("pat", periods)
        if metric in ("ebitda_margin", "ebit_margin"):
            return margin(self.total(metric.split("_")[0], periods), self.total("revenue", periods))
        if metric in ("revenue_growth_yoy", "pat_growth_yoy"):
            key = metric.split("_")[0]
            return pct_change(self.total(key, periods), self.total(key, [p.year_ago for p in periods]))
        return None


def window(basis: str, end: Period) -> list[Period]:
    if basis == "full_year":
        return [Period(end.fy, q) for q in range(1, 5)]
    if basis == "half":
        return [end.shift(-1), end]
    return [end]   # quarter / exit


# ---- 4. evaluation (deterministic) -------------------------------------------
def evaluate(c: Commitment, series: Series, as_of: Optional[Period] = None) -> dict:
    """Return {status, actual, actual_period, interim, reason} for one commitment."""
    meta = METRICS.get(c.metric, {})
    unit = meta.get("unit", "")
    as_of = as_of or series.latest
    res = {"status": "not_evaluable", "actual": None, "actual_period": None,
           "interim": None, "reason": ""}

    if c.issues and any(i in c.issues for i in ("metric not computable from reported tables",
                                                 "unrecognised direction", "no numeric target",
                                                 "horizon could not be mapped to a fiscal period",
                                                 "horizon precedes the call")):
        res["reason"] = "Not scored: " + (c.note or "; ".join(c.issues)) + "."
        return res
    end = parse_period(c.horizon_end)
    win = window(c.basis, end)

    if as_of is None or as_of < end:
        if c.direction in ("increase", "decrease"):
            base = series.value(c.metric, [as_of]) if as_of else None
            res["status"] = "pending"
            res["reason"] = (f"Baseline {as_of.label}: {_fmt(base, unit)}. Scored when {c.horizon_end} is reported."
                             if base is not None else f"Scored when {c.horizon_end} is reported.")
            return res
        res["status"] = "in_progress" if as_of and as_of >= parse_period(c.said_in) else "pending"
        interim = _interim(c, series, as_of, end)
        if interim:
            res["interim"] = interim
            rr = f" (annualised run-rate {_fmt(interim['run_rate'], unit)})" if interim.get("run_rate") else ""
            res["reason"] = (f"Evaluation date {c.horizon_end} not reached. "
                             f"Interim {interim['label']}: {_fmt(interim['value'], unit)}{rr}"
                             f" vs target {_target_text(c, unit)}.")
        else:
            res["status"] = "pending"
            res["reason"] = f"Evaluation date {c.horizon_end} not reached; no interim data yet."
        return res

    actual = series.value(c.metric, win)
    res["actual_period"] = _window_label(c.basis, end)
    if actual is None:
        res["status"] = "pending"
        res["reason"] = f"Reported data for {res['actual_period']} is incomplete."
        return res
    res["actual"] = round(actual, 2)

    if c.direction in ("increase", "decrease"):
        base = series.value(c.metric, [p.shift(-len(win)) for p in win])
        if base is None:
            res["status"] = "pending"
            res["reason"] = "No comparison base for the prior period."
            return res
        moved_up = actual > base
        ok = moved_up if c.direction == "increase" else actual < base
        res["status"] = "achieved" if ok else "missed"
        res["reason"] = (f"{meta['label']} {_fmt(base, unit)} → {_fmt(actual, unit)} "
                         f"({'up' if moved_up else 'down' if actual < base else 'flat'}); "
                         f"management said it would {c.direction}.")
        return res

    lo, hi = c.target_low, c.target_high
    higher_better = meta.get("higher_is_better", True)
    if c.direction == "at_most":
        lo, hi, higher_better = None, hi, False
    if c.direction == "at_least":
        hi = None
    band = lambda t: max(abs(t) * EXCEED_REL, EXCEED_ABS_PCT if unit == "%" else 0)

    if higher_better:
        if lo is not None and actual < lo:
            status = "missed"
        elif (hi is not None and actual > hi) or (hi is None and actual >= lo + band(lo)):
            status = "exceeded"
        else:
            status = "achieved"
    else:
        if hi is not None and actual > hi:
            status = "missed"
        elif actual <= hi - band(hi):
            status = "exceeded"
        else:
            status = "achieved"
    res["status"] = status
    res["reason"] = (f"Reported {meta['label']} for {res['actual_period']}: "
                     f"{_fmt(actual, unit)} vs target {_target_text(c, unit)} → {status}.")
    return res


def _interim(c: Commitment, s: Series, as_of: Optional[Period], end: Period) -> Optional[dict]:
    if as_of is None:
        return None
    if c.basis == "full_year" and as_of.fy == end.fy:
        ytd = [Period(end.fy, q) for q in range(1, as_of.q + 1)]
        v = s.value(c.metric, ytd)
        if v is None:
            return None
        out = {"label": f"YTD Q1–Q{as_of.q} FY{end.fy % 100:02d}", "value": round(v, 2)}
        if c.metric in ("revenue", "pat"):
            out["run_rate"] = round(v * 4 / len(ytd), 2)
        return out
    v = s.value(c.metric, [as_of])
    return None if v is None else {"label": f"latest quarter {as_of.label}", "value": round(v, 2)}


def _window_label(basis: str, end: Period) -> str:
    if basis == "full_year":
        return f"FY{end.fy % 100:02d}"
    if basis == "half":
        return f"H{1 if end.q <= 2 else 2} FY{end.fy % 100:02d}"
    return end.label


def _fmt(x, unit):
    if x is None:
        return "n/a"
    if unit == "cr":
        return f"₹{x:,.0f} cr"
    return f"{x:.2f}%" if unit == "%" else f"{x:g}"


def _target_text(c: Commitment, unit: str) -> str:
    f = lambda x: _fmt(x, unit)
    if c.target_low is None and c.target_high is None and c.direction not in ("increase", "decrease"):
        return "qualitative"
    if c.direction == "range":
        return f"{f(c.target_low)}–{f(c.target_high)}"
    if c.direction == "at_least":
        return f"≥ {f(c.target_low)}"
    if c.direction == "at_most":
        return f"≤ {f(c.target_high)}"
    return c.direction


# ---- 5. the ledger ---------------------------------------------------------------
def build_ledger(commitments: list[dict | Commitment], series_data: dict,
                 as_of: Optional[str] = None) -> dict:
    """Evaluate every commitment and summarise. Accepts already-normalised dicts
    (e.g. from stored JSON) or Commitment objects."""
    s = Series(series_data)
    asof_p = parse_period(as_of) if as_of else s.latest
    rows = []
    for c in commitments:
        if isinstance(c, dict):   # stored/extracted record -> re-validate from its raw fields
            verified = c.get("quote_verified")
            c = normalize(c, c.get("said_in", ""), c.get("source", {}), None)
            c.quote_verified = verified
            if verified is False:
                c.issues.append("quote not found verbatim in transcript")
        ev = evaluate(c, s, asof_p)
        rows.append({**c.to_dict(), "metric_label": METRICS.get(c.metric, {}).get("label") or c.label or c.metric,
                     "target_text": _target_text(c, METRICS.get(c.metric, {}).get("unit", "")),
                     "evaluation": ev})
    rows.sort(key=lambda r: (parse_period(r["said_in"]) or Period(0, 1), r["metric"]))
    counts = {k: 0 for k in ("exceeded", "achieved", "missed", "in_progress", "pending", "not_evaluable")}
    for r in rows:
        counts[r["evaluation"]["status"]] += 1
    resolved = counts["exceeded"] + counts["achieved"] + counts["missed"]
    return {"as_of": asof_p.label if asof_p else None, "rows": rows, "counts": counts,
            "delivery_rate": round((counts["exceeded"] + counts["achieved"]) / resolved * 100)
                             if resolved else None,
            "resolved": resolved, "series_source": s.source,
            "method": "LLM extracts commitments and quotes; verdicts are computed by "
                      "commitments.evaluate() against reported quarterly figures for the stated horizon."}


def attach_ledgers(data: dict) -> dict:
    """Score every research entry that carries raw `commitments` + a quarterly `series`.
    Used by both web/build.py and serve.py so the offline and live app agree."""
    for r in data.get("research", {}).values():
        if r.get("commitments") is not None and r.get("series"):
            r["ledger"] = build_ledger(r["commitments"], r["series"])
            r["ledger"]["read"] = r.get("ledger_read", "")
    return data
