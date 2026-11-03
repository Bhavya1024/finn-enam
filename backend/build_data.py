"""
Orchestrator — runs the three data sources and writes data/finn_data.json,
which the mobile app consumes. Run this nightly (push side) or on demand (pull).

    python backend/build_data.py --prices --announcements
    python backend/build_data.py --research DIXON ASIANPAINT

With no live network / API key, the repo ships a pre-built sample data/finn_data.json
so the app runs offline for the demo. This script is what regenerates it for real.
"""
from __future__ import annotations
import argparse, json, os, datetime as dt
import config
from fiscal import now_ist


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", action="store_true", help="refresh EOD price/volume + price alerts")
    ap.add_argument("--announcements", action="store_true", help="refresh the filings feed (push digest)")
    ap.add_argument("--research", nargs="*", default=None, help="(re)build pull analysis for these tickers")
    ap.add_argument("--window", type=int, default=72, help="announcement look-back hours")
    args = ap.parse_args()

    out_path = os.path.join(config.DATA_DIR, "finn_data.json")
    data = _load(out_path)
    meta = data.setdefault("meta", {})
    sources = meta.setdefault("sources", {})
    now = now_ist().isoformat()

    if args.prices:
        import ingest_prices
        print("» prices …")
        res = ingest_prices.ingest_portfolio()
        if res["prices"]:
            data["portfolio"] = _merge_prices(data.get("portfolio", []), res["prices"])
            data.setdefault("alerts", {})["price"] = res["price_alerts"]
        n_ok, n_req = len(res["prices"]), len(res["requested"])
        sources["prices"] = {"state": "failed" if not n_ok else "live" if n_ok == n_req else "partial",
                             "as_of": now if n_ok else sources.get("prices", {}).get("as_of"),
                             "coverage": f"{n_ok}/{n_req}", "failed": sorted(res["failed"])}

    if args.announcements:
        import fetch_announcements
        print("» announcements …")
        report = {}
        items = fetch_announcements.fetch_portfolio(window_hours=args.window, report=report)
        if report.get("ok"):
            data["announcements"] = items
        n_ok, n_req = len(report.get("ok", [])), len(report.get("requested", []))
        sources["announcements"] = {"state": "failed" if not n_ok else "live" if n_ok == n_req else "partial",
                                    "as_of": now if n_ok else sources.get("announcements", {}).get("as_of"),
                                    "coverage": f"{n_ok}/{n_req}", "count": len(items),
                                    "failed": sorted(report.get("failed", {}))}

    if args.research is not None:
        import analyze
        targets = args.research or config.PORTFOLIO
        data.setdefault("research", {})
        for sym in targets:
            print(f"» research {sym} …")
            try:
                data["research"][sym] = analyze.build_research(sym)
            except Exception as e:
                print(f"  ! {sym}: {e}")

    if args.prices or args.announcements or args.research is not None:
        meta["generated_at"] = now   # only when something was actually rebuilt

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    print(f"✓ wrote {out_path}")
    print("  → rebuild the app with:  python web/build.py")


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def _merge_prices(existing, fresh):
    """Keep static fields (name, sector, mcap) from existing rows; update the live ones."""
    by = {p["ticker"]: p for p in existing}
    for p in fresh:
        base = by.get(p["ticker"], {})
        base.update(p)
        by[p["ticker"]] = base
    return list(by.values())


if __name__ == "__main__":
    main()
