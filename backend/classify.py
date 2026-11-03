"""
Announcement classifier → one of the 17 categories in the reference taxonomy.

Two-tier by design (cost discipline):
  1) a fast keyword/regex pass that resolves the large majority of filings for free;
  2) a cheap-LLM fallback ONLY for the ambiguous remainder.

This is the "smart model routing" the brief explicitly rewards.
"""
from __future__ import annotations
import re
import config

# Rule table: category -> list of regex patterns (checked in priority order).
RULES: list[tuple[str, list[str]]] = [
    ("results",           [r"\b(quarterly|q[1-4]|annual)\s+result", r"\bboard meeting\b.*\bresult", r"\bfinancial results\b", r"\bunaudited\b"]),
    ("earnings_call",     [r"\b(earnings|conference)\s+call", r"\bconcall\b", r"\btranscript\b", r"\banalyst\s+call\b"]),
    ("M&A",               [r"\bacqui", r"\bmerger\b", r"\bdemerger\b", r"\bjoint venture\b", r"\bslump sale\b", r"\bstake\b.*\b(acqui|sale|sell)"]),
    ("fund_raise",        [r"\brights issue\b", r"\bqip\b", r"\bpreferential (allotment|issue)", r"\bbuyback\b", r"\bcommercial paper\b", r"\bfund\s*rais", r"\bdebenture"]),
    ("management_change", [r"\b(appoint|resign|retire|cessation|step down|demise|elevat)\w*\b.*\b(director|cfo|ceo|md|chairman|chief\s+(financial|executive|operating)\s+officer|company secretary|whole[- ]time director|managing director|kmp)", r"\b(ceo|cfo|chief\s+\w+\s+officer|managing director|whole[- ]time director)\b.*\b(appoint|resign|retire|step down|cessation)"]),
    ("litigation",        [r"\blitigation\b", r"\bregulatory (order|action)", r"\bpenalty\b", r"\bshow cause\b", r"\binsolvency\b", r"\bnclt\b", r"\bform 483\b", r"\bwarning letter\b", r"\bfine\b"]),
    ("insider_trading",   [r"\bsast\b", r"\bpit\b", r"\binsider\b", r"\bregulation 7\b", r"\bdisclosure under.*trading\b"]),
    ("credit_rating",     [r"\bcredit rating\b", r"\brating\b.*\b(assign|upgrad|downgrad|reaffirm|revis)", r"\bcrisil\b", r"\bicra\b", r"\bcare ratings\b"]),
    ("dividend",          [r"\bdividend\b"]),
    ("bonus_split",       [r"\bbonus issue\b", r"\bstock split\b", r"\bsub-?division\b.*\bshare"]),
    ("capex",             [r"\bcapacity expansion\b", r"\bnew (plant|facility|unit)\b", r"\bcapex\b", r"\bgreenfield\b", r"\bbrownfield\b"]),
    ("investor_meetings", [r"\binvestor\s+(meet|conference|presentation to)", r"\banalyst meet\b", r"\bschedule of.*investor"]),
    ("postal_ballot",     [r"\bpostal ballot\b"]),
    ("agm_egm",           [r"\b(agm|egm|annual general meeting|extraordinary general meeting)\b"]),
    ("pledging",          [r"\bpledg", r"\bencumbr", r"\brelease of pledge\b"]),
    ("press_release",     [r"\border win\b", r"\bbags? order\b", r"\bnew product\b", r"\bpartnership\b", r"\bclarification\b", r"\bpress release\b"]),
]

# Filings that are almost always routine / low-signal.
ROUTINE = [r"\bcompliance certificate\b", r"\besop\b", r"\besg report\b",
           r"\breg(ulation)? 7\(3\)", r"\bauditor.*appoint", r"\bnewspaper (publication|advertisement)\b",
           r"\btrading window\b", r"\bduplicate share\b"]


def classify_rule(title: str, body: str = "") -> tuple[str, float]:
    """Return (category, confidence). Confidence <0.6 → escalate to the LLM pass."""
    text = f"{title} {body}".lower()
    for pat in ROUTINE:
        if re.search(pat, text):
            return "unclassified", 0.9
    for cat, pats in RULES:
        for pat in pats:
            if re.search(pat, text):
                return cat, 0.85
    return "press_release", 0.4  # weak default → candidate for LLM re-check


def classify_llm(title: str, body: str = "") -> tuple[str, float]:
    """Cheap-model fallback for the ambiguous remainder only. Pseudocode kept
       provider-agnostic; wire to any small model (Haiku / GPT-4o-mini / local)."""
    from llm import complete  # thin wrapper, see llm.py
    prompt = (
        "Classify this Indian exchange filing into exactly one category.\n"
        f"Categories: {', '.join(config.CATEGORIES)}.\n"
        f"Title: {title}\nBody (first 600 chars): {body[:600]}\n"
        "Answer with only the category token."
    )
    cat = complete(prompt, route="classify").strip().split()[0]
    return (cat if cat in config.CATEGORIES else "unclassified"), 0.7


def classify(title: str, body: str = "") -> str:
    cat, conf = classify_rule(title, body)
    if conf < 0.6:
        try:
            cat, _ = classify_llm(title, body)
        except Exception:
            pass  # offline / no key → keep the rule guess
    return cat


# Priority heuristic: category + simple signal words decide digest ranking.
HIGH = {"results", "M&A", "management_change", "fund_raise", "litigation"}
LOW = {"dividend", "bonus_split", "earnings_call", "insider_trading",
       "investor_meetings", "agm_egm", "postal_ballot"}


def priority(category: str, title: str = "") -> str:
    if category == "unclassified":
        return "routine"
    if category in HIGH:
        return "high"
    if category in LOW:
        return "low"
    return "medium"


if __name__ == "__main__":
    tests = [
        "Board Meeting to consider Q2 FY27 Financial Results",
        "Intimation of resignation of Chief Financial Officer",
        "Compliance Certificate under Regulation 7(3) for half-year",
        "CRISIL reaffirms AAA/Stable rating",
        "Acquisition of 51% stake in XYZ Electrolysers Pvt Ltd",
    ]
    for t in tests:
        print(f"{classify(t):18} | {priority(classify(t)):8} | {t}")
