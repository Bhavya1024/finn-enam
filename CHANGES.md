# Changes in response to the project audit

Each audit finding, what changed, and where to find it.

| # | Finding | Resolution |
|---|---|---|
| A | Research tabs stuck on Business (two `setMod` functions) | One module selector (`setMod`) and one state field (`state.mod`). The stock page links into research instead of re-rendering it. All 7 modules verified in the browser. |
| B | Sample data reported as live | `serve.py` tracks prices and filings separately as `live / partial / stale / failed / sample`, with coverage (e.g. `14/18`), failed tickers, last error and `as_of`. Zero filings counts as a live answer. `served_at` is kept apart from data freshness. Partial rows are marked stale in the holdings table. |
| C | Watched categories ignored unless `priority === 'high'` | The user's watched categories decide corporate-event alerts; priority only informs the explanation. Sliders update the readout while dragging and recompute on release. Preferences and alert states (read / snoozed / dismissed) persist. |
| D | Unstable `hash()` IDs | `fetch_announcements.stable_id()` uses SHA-256 over symbol, IST timestamp, description and attachment. Tested across `PYTHONHASHSEED` values. |
| E | Screener numbers presented as primary-source | Every figure carries a `source` with `kind`. Screener is labelled "secondary restatement". `fundamentals.reconcile_with_filing()` re-extracts headline numbers from the original results filing and marks each matched / mismatch / unverified. |
| F | LLM-assigned promised-vs-delivered verdicts | New `commitments.py`. The model extracts commitments and verbatim quotes. Code validates them (metric, target, horizon, quote-in-transcript with page) and scores them against the correct fiscal window (full year, exit, quarter, half, YoY on the same window). Unscoreable items are shown as "not scored" with the reason. |
| G | Financial calculation problems | `finmath.py`: `None` stays `n/a`, no % change from a zero or negative base, margin moves in pp, D/E on share capital + reserves, working-capital cycle includes payables. Lenders get NII, financing margin and NPA, with no EBITDA or CFO ÷ EBITDA. Bajaj Finance's sample results now use the lender basis. |
| H | URL-keyed cache | `_cached_get()` stores per-entry metadata (fetched_at, SHA-256, ETag, Last-Modified), expires HTML after 6h and PDFs after 7 days, and revalidates with conditional requests. If the network fails it serves the stale copy and flags it. |
| I | Naive timestamps | `fiscal.parse_exchange_time()` attaches `Asia/Kolkata` explicitly. Tested under UTC, New York and IST server timezones. |
| J | `innerHTML` injection; server exposed repo root on 0.0.0.0 | All external strings go through `esc()`. Event delegation via `data-*` attributes means no data reaches inline JS. Ticker regex on client and server. Document links restricted to https exchange hosts. CSP meta tag. Data embedded with `</` escaped. The server binds to 127.0.0.1 by default, serves only `index.html` and `/api/*`, and validates `range`. Verified with an injected hostile filing (nothing executes). |
| K | Sep-2026 quarter labelled Q2 FY26 | All sample labels shifted to the April–March year (Jul–Sep 2026 = **Q2 FY27**). Screener columns are converted by `fiscal.period_from_column()`. |
| L | Model IDs and `temperature` | **Partly disagree.** `claude-haiku-5-5` and `claude-sonnet-5-5` are current, valid model IDs, so they are kept (env-overridable). The `temperature` concern was right: current models reject sampling parameters, so `llm.py` no longer sends them and uses `effort`. Added typed error handling, refusal and truncation checks, and `python backend/llm.py --smoke`. |

## Product and UI

- Restrained institutional design: graphite dark and warm off-white light themes, one
  accent colour, flat surfaces, 4–6px corners, tabular numerals, quiet charts with axes.
  Removed gradients, glow, rings and pill clutter.
- Proper desktop layout (sidebar, wide tables, two-column views); mobile keeps the bottom tab bar.
- Today: factual brief with per-source freshness, new-since-last-visit, and an explainable materiality score.
- Portfolio: sortable holdings table. The heatmap is labelled "size = company market cap, not your position".
- Research: opens on the Commitment Ledger, with an evidence-coverage strip and a source on every figure.
- Settings: data-source status panel and a reset for on-device data.

## Verified

- 27 backend tests pass (`python -m unittest discover -s tests`).
- App built and exercised in a browser at desktop and 375px width, in light and dark themes.
- Live NSE announcements fetched end to end through `serve.py` (18/18 tickers, IST times, SHA IDs).

## Not verified here

- Live prices: `yfinance` was not installed in the test environment, so the server correctly reported prices as `failed` and kept the sample.
- Anthropic API calls (no key in the test environment). Run `python backend/llm.py --smoke` before a live demo.
- Screener.in scraping and filing reconciliation against real PDFs.
