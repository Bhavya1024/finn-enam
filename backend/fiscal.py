"""
Indian fiscal-calendar helpers (April–March financial year) and IST timestamps.

  Apr–Jun 2026 -> Q1 FY27      Jul–Sep 2026 -> Q2 FY27
  Oct–Dec 2026 -> Q3 FY27      Jan–Mar 2027 -> Q4 FY27

Every period the app shows is derived here, so labels and year-on-year
comparisons can't drift between modules.
"""
from __future__ import annotations
import re
import datetime as dt
from dataclasses import dataclass
from typing import Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


@dataclass(frozen=True, order=True)
class Period:
    """A fiscal quarter. `fy` is the year the FY *ends* in (FY27 = Apr 2026–Mar 2027)."""
    fy: int
    q: int

    @property
    def label(self) -> str:
        return f"Q{self.q} FY{self.fy % 100:02d}"

    @property
    def index(self) -> int:
        """Monotonic integer, handy for 'how many quarters later' arithmetic."""
        return self.fy * 4 + (self.q - 1)

    def shift(self, quarters: int) -> "Period":
        i = self.index + quarters
        return Period(i // 4, i % 4 + 1)

    @property
    def year_ago(self) -> "Period":
        return self.shift(-4)


def period_of(d: dt.date) -> Period:
    """Fiscal quarter containing a calendar date."""
    fy = d.year + 1 if d.month >= 4 else d.year
    q = ((d.month - 4) % 12) // 3 + 1
    return Period(fy, q)


def period_from_column(col: str) -> Optional[Period]:
    """Screener column headers look like 'Sep 2026' (quarter-end month)."""
    m = re.match(r"\s*([A-Za-z]{3})[a-z]*\s+(\d{4})", col or "")
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    return period_of(dt.date(int(m.group(2)), _MONTHS[m.group(1).lower()], 1))


def fy_label_from_column(col: str) -> str:
    """Annual columns ('Mar 2026') -> 'FY26'; anything else passes through."""
    m = re.match(r"\s*Mar[a-z]*\s+(\d{4})", col or "")
    return f"FY{int(m.group(1)) % 100:02d}" if m else (col or "")


def parse_period(label: str) -> Optional[Period]:
    """'Q2 FY27' / 'Q2FY27' / '2QFY27' -> Period."""
    m = re.search(r"Q\s*([1-4])\s*FY\s*'?(\d{2,4})", label or "", re.I) or \
        re.search(r"([1-4])\s*Q\s*FY\s*'?(\d{2,4})", label or "", re.I)
    if not m:
        return None
    return Period(_fy4(m.group(2)), int(m.group(1)))


def horizon_end(horizon: str, said_in: Optional[Period] = None) -> Optional[Period]:
    """The last quarter whose reported numbers settle a commitment.

    'FY27' / 'FY27 exit' -> Q4 FY27 · 'H1 FY27' -> Q2 · 'H2 FY27' -> Q4 ·
    'Q3 FY27' -> Q3 FY27 · 'next quarter' -> said_in + 1 · 'next year' -> Q4 of the next FY.
    """
    h = (horizon or "").strip()
    if not h:
        return None
    p = parse_period(h)
    if p:
        return p
    m = re.search(r"H\s*([12])\s*FY\s*'?(\d{2,4})", h, re.I)
    if m:
        return Period(_fy4(m.group(2)), 2 if m.group(1) == "1" else 4)
    m = re.search(r"FY\s*'?(\d{2,4})", h, re.I)
    if m:
        return Period(_fy4(m.group(1)), 4)
    if said_in:
        low = h.lower()
        if "next quarter" in low:
            return said_in.shift(1)
        if "next year" in low or "next fiscal" in low:
            return Period(said_in.fy + 1, 4)
        if "this year" in low or "current year" in low or "full year" in low:
            return Period(said_in.fy, 4)
    return None


def _fy4(s: str) -> int:
    y = int(s)
    return y if y > 100 else 2000 + y


# ---- timestamps --------------------------------------------------------------
def parse_exchange_time(s: Optional[str]) -> Optional[dt.datetime]:
    """NSE/BSE timestamps are IST wall-clock with no offset. Attach IST explicitly
    instead of relying on the server's local timezone."""
    if not s:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def now_ist() -> dt.datetime:
    return dt.datetime.now(IST)
