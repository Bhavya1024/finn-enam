"""
Pull-side analysis pipeline — turns company documents + structured tables into the
research JSON the app renders.

  NUMBERS     deterministic, from Screener's standardised tables (labelled as a
              secondary source), with explicit missing-data and denominator rules
              (finmath) and sector-specific metrics (lenders vs operating companies).
  COMMITMENTS cheap model extracts quantified guidance + verbatim quotes from each
              concall transcript; commitments.evaluate() scores them against the
              reported figures for the stated horizon. No model writes a verdict.
  NARRATIVE   one cheap call for the business description / reads / bull-bear,
              given ONLY the extracted facts and an annual-report excerpt.

Every number carries a `source`; every quote carries transcript + page.
"""
from __future__ import annotations
import json
import config
import finmath as fm
from fiscal import parse_period


def sector_profile(symbol: str, f) -> str:
    import fundamentals as fu
    return "lender" if fu.is_lender(symbol, f) else "operating"


def _metric(k, v, sub, source, basis=""):
    return {"k": k, "v": v, "sub": sub, "source": source, **({"basis": basis} if basis else {})}


def build_research(symbol: str) -> dict:
    import fundamentals as fu
    import commitments as cm
    f = fu.fetch_fundamentals(symbol); T = f.financials
    q, pl, bs, cf, ra = (T.get(k, {}) for k in ("quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios"))
    profile = sector_profile(symbol, f)
    qlab = fu.quarter_labels(q)[-8:]
    src_q, src_bs = fu.screener_source(f, "quarterly results"), fu.screener_source(f, "balance sheet")
    src_cf, src_ra = fu.screener_source(f, "cash flow"), fu.screener_source(f, "ratios")
    L = lambda tbl, *n: fu.row(tbl, *n)[-8:]

    rev, pat = L(q, "Sales", "Revenue"), L(q, "Net Profit")
    metrics, points = [], []
    latest = qlab[-1] if qlab else "latest"

    rev_yoy = fm.pct_change(fm.at(rev, -1), fm.at(rev, -5)) if len(rev) >= 5 else None
    pat_yoy = fm.pct_change(fm.at(pat, -1), fm.at(pat, -5)) if len(pat) >= 5 else None
    metrics.append(_metric(f"Revenue ({latest})", "₹" + fm.fmt_num(fm.at(rev, -1)) + " cr",
                           fm.fmt_pct_change(rev_yoy) + " YoY", src_q))
    metrics.append(_metric(f"PAT ({latest})", "₹" + fm.fmt_num(fm.at(pat, -1)) + " cr",
                           fm.fmt_pct_change(pat_yoy) + " YoY", src_q))

    if profile == "lender":
        # NII = interest earned − interest expended; financing margin as reported.
        intr = L(q, "Interest")
        nii = [None if a is None or b is None else a - b for a, b in zip(rev, intr)]
        fmargin = L(q, "Financing Margin")
        gnpa, nnpa = L(q, "Gross NPA"), L(q, "Net NPA")
        metrics.insert(1, _metric(f"Net interest income ({latest})", "₹" + fm.fmt_num(fm.at(nii, -1)) + " cr",
                                  fm.fmt_pct_change(fm.pct_change(fm.at(nii, -1), fm.at(nii, -5))) + " YoY",
                                  src_q, "interest earned − interest expended"))
        if fm.at(fmargin, -1) is not None:
            metrics.append(_metric("Financing margin", f"{fmargin[-1]:.1f}%",
                                   "financing profit ÷ revenue", src_q))
        for k, s in (("Gross NPA", gnpa), ("Net NPA", nnpa)):
            if fm.at(s, -1) is not None:
                points.append({"k": k, "v": f"{s[-1]:.2f}%", "read": "Asset quality, latest quarter.", "source": src_q})
        trajectory = {"series_label": "Revenue (₹ cr) & financing margin (%)", "quarters": qlab,
                      "revenue": rev, "margin": fmargin, "margin_label": "Financing margin", "pat": pat,
                      "source": src_q}
        cash_quality = {"applicable": False, "quarters": [], "cfo_ebitda": [],
                        "reason": "Cash conversion (CFO ÷ EBITDA) is not meaningful for a lender: "
                                  "loan growth flows through operating cash flow."}
        series = None
    else:
        opm, ebitda = L(q, "OPM"), L(q, "Operating Profit")
        opm_pp = fm.pp_change(fm.at(opm, -1), fm.at(opm, -5)) if len(opm) >= 5 else None
        metrics.insert(1, _metric("EBITDA margin", "n/a" if fm.at(opm, -1) is None else f"{opm[-1]:.1f}%",
                                  ("n.m." if opm_pp is None else f"{opm_pp:+.1f} pp YoY"), src_q,
                                  "EBITDA = revenue − operating expenses, before other income"))
        trajectory = {"series_label": "Revenue (₹ cr) & EBITDA margin (%)", "quarters": qlab,
                      "revenue": rev, "margin": opm, "margin_label": "EBITDA margin", "pat": pat,
                      "source": src_q}
        # Cash conversion on annual numbers (CFO is only reported annually).
        cfo, op_p = fu.row(cf, "Cash from Operating"), fu.row(pl, "Operating Profit")
        n = min(len(cfo), len(op_p), 6)
        conv = [fm.cash_conversion(c, o) for c, o in zip(cfo[-n:], op_p[-n:])] if n else []
        conv = [None if c is None else round(c, 2) for c in conv]
        yrs = fu.year_labels(pl)[-n:] if n else []
        if conv and conv[-1] is not None:
            metrics.append(_metric(f"CFO ÷ EBITDA ({yrs[-1]})", f"{conv[-1]:.2f}", "1.0 = all EBITDA became cash",
                                   src_cf, "annual; EBITDA as above"))
        cash_quality = {"applicable": True, "cfo_ebitda": conv, "quarters": yrs, "source": src_cf}
        dep = L(q, "Depreciation")
        ebit = [None if a is None or d is None else a - d for a, d in zip(ebitda, dep)] if dep else []
        series = {"periods": qlab, "revenue": rev, "ebitda": ebitda, "ebit": ebit, "pat": pat, "source": src_q}

        # Working-capital cycle from Screener's ratio table: debtor + inventory − payable days.
        dd, idays, pdays = (fm.at(fu.row(ra, n_), -1) for n_ in ("Debtor Days", "Inventory Days", "Days Payable"))
        ccc = fm.net_working_capital(dd, idays, pdays)
        if ccc is not None:
            points.append({"k": "Cash conversion cycle", "v": f"{ccc:.0f} days",
                           "read": f"Receivable {dd:.0f} + inventory {idays:.0f} − payable {pdays:.0f} days (latest year).",
                           "source": src_ra})

    # Leverage: borrowings over shareholders' equity (share capital + reserves).
    borrow = fu.row(bs, "Borrowings")
    eq = fm.total_equity(fm.at(fu.row(bs, "Equity Capital"), -1), fm.at(fu.row(bs, "Reserves"), -1))
    de = fm.debt_to_equity(fm.at(borrow, -1), eq)
    if de is not None and profile != "lender":
        metrics.append(_metric("Debt ÷ equity", f"{de:.2f}×", "latest balance sheet", src_bs,
                               "borrowings ÷ (share capital + reserves); excludes minority interest"))
        ch = fm.pct_change(fm.at(borrow, -1), fm.at(borrow, -2))
        points.insert(0, {"k": "Leverage", "v": f"D/E {de:.2f}×",
                          "read": f"Borrowings ₹{fm.fmt_num(borrow[-1])} cr"
                                  + (f", {ch:+.0f}% vs prior year." if ch is not None else "."),
                          "source": src_bs})

    # ---- commitments: cheap extraction, deterministic evaluation ----
    transcripts = fu.latest_transcripts(f, n=4)
    extracted = []
    for t in transcripts:
        said_in = _quarter_from_label(t["label"])
        if not said_in:
            print(f"  ! cannot date transcript {t['label']!r}; skipped")
            continue
        src = {"kind": "concall_transcript", "label": f"{said_in} earnings-call transcript",
               "url": t["url"], "sha256": t.get("sha256"), "retrieved_at": t.get("retrieved_at")}
        try:
            extracted += [c.to_dict() for c in cm.extract(t["text"], said_in, src)]
        except Exception as e:
            print(f"  ! commitments {t['label']}: {e}")
    ledger = cm.build_ledger(extracted, series) if series else \
        {"rows": [], "counts": {}, "unsupported": "Lender commitments (AUM, NIM, credit cost) need "
                                                  "disclosures beyond the standard tables; not scored."}

    # ---- narrative: one cheap call, grounded in the facts above ----
    from llm import complete_json
    ar_text, ar_src = "", None
    if f.annual_reports:
        try:
            ar_text, meta = fu.download_pdf_text(f.annual_reports[0]["url"])
            ar_text = ar_text[:7000]
            ar_src = {"kind": "annual_report", "label": f.annual_reports[0]["label"],
                      "url": f.annual_reports[0]["url"], "sha256": meta.get("sha256")}
        except Exception as e:
            print("  ! annual report:", e)
    facts = json.dumps({"profile": profile, "quarters": qlab, "revenue": rev, "pat": pat,
                        "margin": trajectory["margin"], "metrics": [(m["k"], m["v"], m["sub"]) for m in metrics],
                        "commitments": [{k: r[k] for k in ("said_in", "metric_label", "target_text", "horizon_end")}
                                        | {"status": r["evaluation"]["status"]} for r in ledger["rows"]]},
                       default=str)
    nar = {}
    try:
        nar = complete_json(
            "Using ONLY these facts (no outside knowledge), return JSON: "
            '{"what":"2 sentences on what the company does","model":"1 sentence on how it earns",'
            '"segments":[{"name","rev_share":number,"note"}] (only if the annual report excerpt states them, else []),'
            '"trajectory_read":"1-2 sentences","cash_read":"1-2 sentences",'
            '"ledger_read":"2 sentences on management delivery, citing the statuses given",'
            '"bull":["3 short points"],"bear":["3 short points"]}\n'
            f"FACTS: {facts}\nANNUAL REPORT EXCERPT: {ar_text}", route="extract", max_tokens=3000)
    except Exception as e:
        print("  ! narrative:", e)
    trajectory["read"], cash_quality["read"] = nar.get("trajectory_read", ""), \
        cash_quality.get("reason") or nar.get("cash_read", "")
    ledger["read"] = nar.get("ledger_read", "")

    sources = [s for s in [ar_src] if s] + [
        {"kind": "concall_transcript", "label": t["label"], "url": t["url"]} for t in transcripts] + [src_q]
    return {
        "ticker": symbol, "name": T.get("_name", symbol), "sector": "", "profile": profile,
        "as_of": latest, "sources": sources,
        "grounding_note": "Quotes and guidance come from the company's own concall transcripts and annual report. "
                          "Financial figures come from Screener.in's standardised tables (a secondary restatement "
                          "of the filings) and are labelled as such.",
        "business_snapshot": {"what": nar.get("what", ""), "segments": nar.get("segments", []),
                              "model": nar.get("model", ""), "source": ar_src},
        "financial_snapshot": {"metrics": metrics}, "trajectory": trajectory,
        "balance_sheet": {"points": points or [{"k": "Balance sheet", "v": "n/a",
                                                "read": "Not available for this company.", "source": src_bs}]},
        "cash_quality": cash_quality, "ledger": ledger,
        "bull_bear": {"bull": nar.get("bull", []), "bear": nar.get("bear", [])},
        "coverage": {"transcripts": len(transcripts), "annual_report": bool(ar_src),
                     "quarters": len(qlab), "commitments": len(ledger["rows"])},
    }


def _quarter_from_label(label: str) -> str | None:
    """Screener transcript labels vary ('Transcript Q2FY27', 'Oct 2026 Transcript').
    Calls happen in the month(s) after the quarter ends."""
    p = parse_period(label or "")
    if p:
        return p.label
    from fiscal import period_from_column
    p = period_from_column(label or "")
    return p.shift(-1).label if p else None


if __name__ == "__main__":
    print(_quarter_from_label("Transcript Q2FY27"), _quarter_from_label("Nov 2026 Transcript"))
