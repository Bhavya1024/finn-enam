"""
Financial arithmetic with explicit rules for missing data and awkward denominators.

Principles:
  • Missing stays missing — every function returns None rather than 0 when an
    input is unavailable, and the UI renders None as "n/a".
  • A percentage change is only meaningful against a positive base. From a zero
    or negative base we return None (the UI says "n.m." — not meaningful) instead
    of printing something like "+340%" off a loss.
  • Margin moves are reported in percentage points, never as % of a %.
"""
from __future__ import annotations
from typing import Optional, Sequence

Num = Optional[float]


def pct_change(cur: Num, base: Num) -> Num:
    if cur is None or base is None or base <= 0:
        return None
    return (cur - base) / base * 100


def pp_change(cur: Num, base: Num) -> Num:
    """Difference of two percentages, in percentage points."""
    if cur is None or base is None:
        return None
    return cur - base


def ratio(num: Num, den: Num) -> Num:
    if num is None or den is None or den == 0:
        return None
    return num / den


def margin(part: Num, whole: Num) -> Num:
    if part is None or whole is None or whole <= 0:
        return None
    return part / whole * 100


def at(seq: Sequence, i: int):
    """Safe index: None when out of range."""
    try:
        return seq[i]
    except (IndexError, TypeError):
        return None


def total_equity(equity_capital: Num, reserves: Num) -> Num:
    """Shareholders' equity attributable to owners = share capital + other equity
    (reserves & surplus). Minority interest is excluded on purpose."""
    if equity_capital is None or reserves is None:
        return None
    return equity_capital + reserves


def debt_to_equity(borrowings: Num, equity: Num) -> Num:
    if borrowings is None or equity is None or equity <= 0:
        return None   # negative equity -> D/E is not meaningful
    return borrowings / equity


def net_working_capital(receivables: Num, inventory: Num, payables: Num) -> Num:
    """Operating working capital = receivables + inventory − trade payables."""
    if receivables is None or inventory is None or payables is None:
        return None
    return receivables + inventory - payables


def days(amount: Num, annual_flow: Num) -> Num:
    """Convert a balance into days of an annual flow (e.g. receivable days on sales)."""
    if amount is None or annual_flow is None or annual_flow <= 0:
        return None
    return amount / annual_flow * 365


def cash_conversion(cfo: Num, ebitda: Num) -> Num:
    """CFO ÷ EBITDA. Undefined when EBITDA is non-positive."""
    if cfo is None or ebitda is None or ebitda <= 0:
        return None
    return cfo / ebitda


def fmt_num(x: Num, d: int = 0) -> str:
    return "n/a" if x is None else f"{x:,.{d}f}"


def fmt_pct_change(x: Num, unit: str = "%") -> str:
    return "n.m." if x is None else f"{x:+.1f}{unit}"
