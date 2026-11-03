# FINN — Covering Note

*Mobile-first financial investment agent · ENAM AI Engineer Build Challenge*

## What I built

A working, mobile-first prototype of **FINN** that delivers both modes the brief asks for:

- **Push** — a daily brief and a windowed digest of portfolio filings, ranked by an
  **explainable materiality score**, with "new since last visit" and routine paperwork
  collapsed. Alerts are split into price, volume and corporate events, each explaining
  why it fired, with read / snooze / dismiss. Results filings render a QoQ/YoY table
  (NII instead of EBITDA for lenders); management changes render the incoming person's bio.
- **Pull** — on-demand, evidence-linked research on any NSE ticker, centred on a
  **Management Commitment Ledger**: a model extracts quantified guidance and verbatim
  quotes from concall transcripts, and a deterministic engine scores each commitment
  against reported figures for the stated horizon.
- A **generalisable backend engine** (yfinance + NSE/BSE filings + screener.in
  fundamentals) with a two-tier classifier and tiered model routing.

The frontend is a single self-contained `index.html` (vanilla JS, no framework, no
build, no server) so it runs instantly on a phone — the brief's "a demo that doesn't
run is the worst outcome" drove that choice hard.

## Key decisions & trade-offs

1. **Thin-but-working, offline-first.** I shipped a self-contained app on a curated
   sample dataset rather than a live-but-fragile one. The real engine lives in
   `/backend` and is wired to generalise; the app renders whatever `finn_data.json`
   the engine produces. This guarantees the demo always runs.
2. **One lens, done deeply, not eight done shallowly.** I invested in promised vs
   delivered because the brief flagged it as what they value most, and made it
   auditable. The model only extracts. Verdicts come from code that maps each
   commitment to its fiscal horizon (full year, exit rate, quarter, half) and compares
   it with reported numbers. `DIXON` (every due commitment met) vs `ASIANPAINT` (three
   straight misses) shows the lens discriminating.
3. **Model routing as a first-class design choice.** Rules handle ~80% of
   classification for free; a cheap model does bulk extraction on pre-filtered chunks;
   the scoring step needs no model at all. LLM calls are cached by prompt hash and
   documents by URL with content hashes and revalidation. Efficiency was a design input.
4. **Source honesty.** Quotes and guidance come from company documents with page
   references. Multi-period figures come from Screener.in's standardised tables, labelled
   as a secondary source and reconciled to the results filing where available. No news
   or broker notes (`PULL_BANNED`). Push-side enrichment (a new CFO's background) is
   kept separate, as the brief permits.
5. **Restrained, institutional design.** Table-led, flat surfaces, tabular numerals,
   one accent colour, quiet charts. Mobile-first with a proper desktop layout.
6. **Honest data states.** Prices and filings report live / partial / stale / failed
   separately, with coverage. Sample data is always labelled as such.

## What I deliberately left out

- **Live data wired to a key** — the engine is complete and runnable, but the shipped
  demo uses sample data so it needs no network or API key to try.
- **Background push notifications / schedulers** — the digest and alerts are modelled
  and computed; actually delivering an OS notification is productionisation, not signal.
- **Auth, multi-user, persistence** — single-user prototype by design.
- **The other 7 pull modules at full depth for *every* ticker** — three companies ship
  with a complete worked analysis; the engine generalises to the rest.

## Where I'd take it next

1. **Wire the engine to live data** on a nightly job + an on-demand pull queue, with
   the LLM key server-side.
2. **Persist the ledger across quarters.** Each in-progress commitment is re-scored
   automatically as filings land, building a long-run delivery record per management
   team. Add lender metrics (AUM, NIM, credit cost) from investor presentations.
3. **A conversational layer over the same grounded data** — ask "did Dixon deliver on
   its margin guidance?" and get the answer with the quarter-by-quarter receipts.
4. **Alert learning** — nudge thresholds from which alerts the user actually acts on.

## How to run

Open `index.html` (works on a phone). To regenerate data from live sources, see the
README — `pip install -r requirements.txt`, set a provider key, run
`backend/build_data.py`, then `web/build.py`.
