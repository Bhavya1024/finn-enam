# FINN — Financial Investment Agent

A research desk for an Indian equity portfolio, built for the **ENAM AI Engineer Build Challenge**.

FINN answers three questions:

- **Today** — what changed across my holdings, what matters, and *why* does it matter?
- **Research** — what does the evidence say about this company?
- **Commitment ledger** — did management deliver what it promised?

> **Try it:** open [`index.html`](index.html) in any browser. It is self-contained
> (sample data, no server, no network). Mobile gets a bottom tab bar; desktop gets a
> sidebar layout. For live data, run `python backend/serve.py` (see below).

---

## What's in the box

```
finn-enam/
├── index.html              ← the built app (self-contained)
├── web/
│   ├── app_template.html   ← app source (HTML/CSS/vanilla JS, no framework)
│   └── build.py            ← scores sample ledgers, injects data → index.html
├── backend/
│   ├── config.py           · portfolio, thresholds, model routing, server settings
│   ├── serve.py            · local server: index.html + /api/* only, per-source status
│   ├── ingest_prices.py    · EOD price/volume (Yahoo Finance) with per-ticker coverage
│   ├── fetch_announcements.py · NSE filings, IST timestamps, stable SHA-256 IDs
│   ├── classify.py         · 17-category classifier (rules → cheap-model fallback)
│   ├── fundamentals.py     · Screener tables + company PDFs, version-aware cache, reconciliation
│   ├── analyze.py          · research builder (sector-aware: operating companies vs lenders)
│   ├── commitments.py      · commitment ledger: LLM extracts, deterministic engine scores
│   ├── fiscal.py           · April–March fiscal quarters, horizons, IST parsing
│   ├── finmath.py          · % changes, margins, leverage with explicit missing-data rules
│   ├── llm.py              · model routing, disk cache, error handling, API smoke test
│   └── build_data.py       · batch orchestrator → data/finn_data.json
├── tests/test_backend.py   ← 27 tests, no network or API key needed
└── data/finn_data.json     ← illustrative sample data
```

## Push: Today and Alerts

- **Daily brief**: a factual summary (filings needing attention, breadth, largest
  move, unusual volume), what's **new since your last visit**, and open alerts. It also
  states how fresh each data source is.
- **Prioritised feed** (24h / 48h / 7d / all) with an **explainable materiality score**.
  Open any item to see the points behind its score (filing type, watched category,
  price move, volume, profit swing). Routine paperwork is collapsed.
- **Results filings** show a Revenue / EBITDA / PBT / PAT table with QoQ and YoY.
  **Lenders** (banks, NBFCs) show net interest income instead of EBITDA.
  Each table is marked as reconciled, differing, or not reconciled against the
  original filing.
- **Alerts** are split into price moves, unusual volume and corporate events, each
  with the exact reason it fired. You can mark read, snooze for 24h or dismiss.
  Every watched category alerts whatever its priority. Thresholds and alert states
  persist on the device.

## Pull: Research and the Commitment Ledger

Search any NSE symbol. The research view opens on the **Commitment ledger**:

1. A small model reads each concall transcript and extracts **quantified commitments**:
   metric, target, direction, horizon and the **verbatim quote**.
2. `commitments.normalize()` validates each one: a known metric, a numeric target, a
   horizon that maps to a fiscal quarter, and a quote found verbatim in the
   transcript (with its page). Anything that fails is shown as *not scored*, not guessed.
3. `commitments.evaluate()` compares the commitment with reported figures for the
   **right period**. A full-year target uses the four quarters of that fiscal year,
   an exit-rate target uses the final quarter, and growth targets use the same window a
   year earlier. Before the horizon arrives, the status is *in progress*, with a
   year-to-date reading and run-rate.

Statuses: **exceeded · achieved · missed · in progress · pending · not scored**.
No model writes a verdict.

Compare `DIXON` (every due commitment met or beaten), `ASIANPAINT` (three straight
misses on margin and growth recovery) and `INFY` (conservative targets beaten;
constant-currency guidance shown but unscored, because INR tables can't verify it).

The other modules cover business, financials, trajectory, balance sheet, cash
quality and bull/bear. Every figure carries its **source**.

### Sourcing, stated precisely

| Input | Kind | How it's labelled |
|---|---|---|
| Concall transcripts, annual reports, results filings | Company documents (primary) | quote + document + page |
| Screener.in standardised tables | Secondary restatement of filings | "Screener.in table · secondary" |
| News, broker notes, research reports | Not used (`config.PULL_BANNED`) | — |

When the original results filing is available, headline numbers are re-extracted
from it and reconciled against Screener's table (`fundamentals.reconcile_with_filing`).

### Financial rules (`finmath.py`)

- Missing data stays missing (`n/a`). It is never shown as zero.
- A % change is computed only against a positive base. From zero or a loss it shows `n.m.`
- Margin changes are in percentage points.
- Debt ÷ equity uses borrowings over shareholders' equity (share capital + reserves).
- The working-capital cycle is receivable days + inventory days − payable days.
- Lenders get NII, financing margin and asset quality, and no CFO ÷ EBITDA.
- Fiscal quarters follow India's April–March year (Jul–Sep 2026 = **Q2 FY27**).

## Model routing

| Step | Tier | Default model |
|---|---|---|
| Classify filings | rules, then cheap model | `claude-haiku-5-5` (effort `low`) |
| Extract commitments / numbers | cheap model, chunked | `claude-haiku-5-5` (effort `low`) |
| Narrative, bull/bear | cheap model | `claude-haiku-5-5` |
| Scoring commitments | **no model**: deterministic | — |

Model IDs are overridable (`FINN_CLASSIFY_MODEL`, `FINN_EXTRACT_MODEL`,
`FINN_REASON_MODEL`). No sampling parameters are sent, because current models reject
`temperature`. Verify your key and models with:

```bash
python backend/llm.py --smoke
```

## Running the live engine

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...                 # or `ant auth login`
python backend/serve.py                      # http://127.0.0.1:8000
```

The server binds to **127.0.0.1** and serves only `index.html` and `/api/*`, so cache,
data and `.env` files are never exposed. For a phone on a trusted LAN:
`FINN_HOST=0.0.0.0 python backend/serve.py` (there is no authentication).

Each source reports its own state: **live** (every ticker refreshed), **partial**
(some failed; those rows are marked stale), **stale** (no refresh for too long) or
**failed**, plus coverage and the last error. A successful HTTP response is not taken
as proof that the data is live.

Batch rebuild for the static demo:

```bash
python backend/build_data.py --prices --announcements
python backend/build_data.py --research DIXON ASIANPAINT INFY
python web/build.py
```

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests cover fiscal mapping, IST parsing under different server timezones, stable
IDs across hash seeds, denominator rules, ledger evaluation, sample-data integrity,
server path restrictions, ticker validation and source-status reporting.

---
*`data/finn_data.json` is illustrative sample data. It is plausible and internally
consistent, but it is not company data and has not been verified. Not investment advice.*
