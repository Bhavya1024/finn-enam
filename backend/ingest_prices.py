"""
Price & volume ingestion (end-of-day) + unusual-move detection.

Source: Yahoo Finance via the `yfinance` library (free, EOD, public).
Indian tickers take a .NS (NSE) / .BO (BSE) suffix.

This is deliberately thin — the brief calls the backend "plumbing, not the point."
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional
import config


@dataclass
class PriceSnapshot:
    ticker: str
    price: float
    prev_close: float
    chg_pct: float
    volume: int
    avg_vol_20d: float
    vol_ratio: float
    spark: list          # last ~8 closes for the sparkline
    as_of: str = ""      # trading date of `price` (YYYY-MM-DD)


def fetch_prices(ticker: str, lookback_days: int = 40) -> Optional[PriceSnapshot]:
    """Pull EOD OHLCV and derive the two signals the push side watches:
       (1) daily close-to-close % move, (2) volume vs its 20-day average."""
    import yfinance as yf  # imported lazily so the module imports without the dep

    sym = ticker + config.YF_SUFFIX
    hist = yf.Ticker(sym).history(period=f"{lookback_days}d", interval="1d", auto_adjust=False)
    if hist is None or len(hist) < 2:
        return None

    closes = hist["Close"].dropna()
    vols = hist["Volume"].dropna()
    price, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
    # 20 sessions *before* today, so today's spike doesn't inflate its own baseline
    avg20 = float(vols.iloc[-21:-1].mean()) if len(vols) > 21 else float(vols.iloc[:-1].mean())
    vol_today = int(vols.iloc[-1])

    return PriceSnapshot(
        ticker=ticker,
        price=round(price, 2),
        prev_close=round(prev, 2),
        chg_pct=round((price - prev) / prev * 100, 2) if prev else 0.0,
        volume=vol_today,
        avg_vol_20d=round(avg20, 0),
        vol_ratio=round(vol_today / avg20, 2) if avg20 else 0.0,
        spark=[round(float(c), 2) for c in closes.iloc[-8:]],
        as_of=closes.index[-1].strftime("%Y-%m-%d"),
    )


def flag_unusual(snap: PriceSnapshot, thresholds: dict) -> list[dict]:
    """Return triggered alerts for one stock given the user's thresholds.
       The user decides what 'unusual' means — this just applies it."""
    out = []
    if snap.vol_ratio >= thresholds["vol_ratio"]:
        out.append({"type": "vol", "ticker": snap.ticker,
                    "reason": f"Volume {snap.vol_ratio:.1f}x its 20-day average",
                    "value": snap.vol_ratio})
    if abs(snap.chg_pct) >= thresholds["price_move_pct"]:
        out.append({"type": "price", "ticker": snap.ticker,
                    "reason": f"Closed {snap.chg_pct:+.1f}% today",
                    "value": snap.chg_pct})
    return out


def ingest_portfolio(tickers=None, thresholds=None) -> dict:
    tickers = tickers or config.PORTFOLIO
    thresholds = thresholds or config.DEFAULT_THRESHOLDS
    snaps, alerts, failed = [], [], {}
    for t in tickers:
        try:
            snap = fetch_prices(t)
        except Exception as e:          # one bad ticker must not sink the batch
            snap, failed[t] = None, str(e)[:200]
        if not snap:
            failed.setdefault(t, "no price data")
            print(f"  ! {t}: {failed[t]}")
            continue
        d = asdict(snap)
        d["as_of"] = snap.as_of
        snaps.append(d)
        alerts += flag_unusual(snap, thresholds)
    # Coverage lets callers say "14/18 live" instead of calling the whole portfolio live.
    return {"prices": snaps, "price_alerts": alerts,
            "requested": list(tickers), "failed": failed}


if __name__ == "__main__":
    import json
    print(json.dumps(ingest_portfolio(config.PORTFOLIO[:3]), indent=2))
