"""
FINN — central configuration.

Portfolio universe, alert defaults, and the model-routing table.
The routing table is the whole point of the "efficiency" instinct the brief rewards:
cheap models do bulk extraction, a stronger model is used only where reasoning demands it.
"""
from __future__ import annotations
import os

# ---- Portfolio (15–20 NSE names across sectors & sizes) ------------------------
PORTFOLIO = [
    "RELIANCE", "HDFCBANK", "TCS", "INFY", "ITC", "LT", "TATAMOTORS", "SUNPHARMA",
    "ASIANPAINT", "BAJFINANCE", "ADANIPORTS", "TITAN", "TATASTEEL", "POWERGRID",
    "DMART", "DIXON", "POLYCAB", "VBL",
]

# Ad-hoc research universe (can be outside the portfolio) — proves generalisation
ADHOC = ["KPITTECH", "JUBLFOOD", "IEX", "CDSL"]

YF_SUFFIX = ".NS"  # NSE; use ".BO" for BSE

# ---- Alert defaults (user-configurable in the app) -----------------------------
DEFAULT_THRESHOLDS = {
    "vol_ratio": 2.0,         # volume > 2x its 20-day average
    "price_move_pct": 4.0,    # |daily close-to-close| > 4%
    "watched_categories": ["results", "M&A", "management_change",
                            "fund_raise", "credit_rating", "litigation"],
}

# ---- Announcement taxonomy (from the reference doc) ----------------------------
CATEGORIES = [
    "results", "M&A", "fund_raise", "management_change", "litigation",
    "insider_trading", "earnings_call", "investor_meetings", "credit_rating",
    "dividend", "bonus_split", "capex", "press_release", "postal_ballot",
    "agm_egm", "pledging", "unclassified",
]

# ---- Sector-aware analysis -----------------------------------------------------
# Lenders (banks, NBFCs) are analysed on NII / financing margin / asset quality,
# not on EBITDA and CFO÷EBITDA, which are meaningless for a balance-sheet business.
# analyze.sector_profile() also auto-detects lenders from the statement layout.
LENDERS = {"HDFCBANK", "BAJFINANCE", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK",
           "CHOLAFIN", "SHRIRAMFIN", "MUTHOOTFIN", "BAJAJFINSV"}

# ---- Model routing -------------------------------------------------------------
# The instinct the brief asks for: right tool per step, cheap where possible.
#   tier "nano"  -> keyword/regex rules, zero-cost (handles ~80% of classification)
#   tier "cheap" -> small LLM for bulk extraction (numbers out of filings/transcripts)
#   tier "smart" -> stronger LLM ONLY for interpretation (narrative, bull/bear)
# Note: the promised-vs-delivered *verdicts* are not produced by any model — the LLM
# extracts commitments, and commitments.evaluate() scores them deterministically.
# IDs are overridable by env; run `python backend/llm.py --smoke` to verify them.
MODELS = {
    "classify":  {"tier": "cheap", "effort": "low",
                  "model": os.getenv("FINN_CLASSIFY_MODEL", "claude-haiku-5-5")},
    "extract":   {"tier": "cheap", "effort": "low",
                  "model": os.getenv("FINN_EXTRACT_MODEL",  "claude-haiku-5-5")},
    "reason":    {"tier": "smart", "effort": "medium",
                  "model": os.getenv("FINN_REASON_MODEL",   "claude-sonnet-5-5")},
}

# ---- Storage -------------------------------------------------------------------
# Cache and data live OUTSIDE anything the HTTP server exposes (serve.py only serves
# index.html and /api/*). Documents are cached with content hashes + fetch metadata;
# HTML pages expire after HTML_TTL_S. See fundamentals._cached_get().
CACHE_DIR = os.getenv("FINN_CACHE_DIR", os.path.join(os.path.dirname(__file__), "..", ".cache"))
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
HTML_TTL_S = int(os.getenv("FINN_HTML_TTL_S", 6 * 3600))
DOC_TTL_S = int(os.getenv("FINN_DOC_TTL_S", 7 * 86400))   # PDFs: revalidate weekly

# ---- Server --------------------------------------------------------------------
# Loopback by default. Set FINN_HOST=0.0.0.0 only on a trusted LAN (e.g. phone demo).
HOST = os.getenv("FINN_HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", 8000))
# A data source older than this is reported as "stale" rather than "live".
STALE_AFTER_S = {"prices": 15 * 60, "announcements": 60 * 60}

# NSE symbols: letters, digits, '&' and '-' (e.g. M&M, BAJAJ-AUTO).
TICKER_RE = r"^[A-Z0-9][A-Z0-9&\-]{0,19}$"

# Hard discipline for the Pull side: primary sources only.
# Every number and quote in research output carries a `source` whose `kind` is one of
# PULL_ALLOWED_SOURCES (company documents) or STRUCTURED_SECONDARY (an aggregator's
# standardised restatement of those documents, shown as such — never as a filing).
PULL_ALLOWED_SOURCES = {"annual_report", "quarterly_results", "concall_transcript", "investor_presentation"}
STRUCTURED_SECONDARY = {"screener_table"}
PULL_BANNED = {"news", "broker_note", "research_report", "model_prior_knowledge"}
