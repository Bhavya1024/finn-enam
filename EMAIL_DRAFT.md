**To:** assessment@enam.com
**Subject:** ENAM - IIT screening - 2027

---

Hi team,

Please find my submission for the AI Engineer Build Challenge — **FINN**, a mobile-first
financial investment agent.

**Try it (mobile-first):** <your GitHub Pages / Netlify / Vercel link>
**GitHub repo:** <your repo link>
**AI build history:** <Claude / Cursor / ChatGPT share link(s)>

**What it is.** FINN filters the investor firehose down to what matters, in two modes:

- **Push** — a windowed, prioritised digest of portfolio filings (routine paperwork
  collapsed), plus triggered alerts where *I* set what "unusual" means (volume ×,
  price move %, watched categories) and they recompute live. Results filings render a
  QoQ/YoY Revenue–EBITDA–PBT–PAT table; management changes pull the incoming person's
  background. Each filing carries an explainable materiality score.
- **Pull** — on-demand research on any NSE ticker, centred on a **Management
  Commitment Ledger**: what management *promised* on each call (verbatim, with source)
  vs what was *delivered*, scored by deterministic code against the right fiscal
  period, not by the model. Compare DIXON vs ASIANPAINT in the app to see the lens discriminate.

**A few deliberate choices:**
- Shipped a self-contained, offline-first prototype (runs instantly on a phone) backed
  by a real, generalisable engine — so the demo always runs, per "a demo that doesn't
  run is the worst outcome."
- Model routing as a design input: rules first, a cheap model for extraction, no model
  for scoring, and everything cached.
- Source honesty: quotes from company documents with page references; structured
  figures labelled as secondary and reconciled to filings; live/sample status per source.

A fuller write-up — decisions, trade-offs, what I left out and where I'd take it next —
is in the attached covering note (and `COVERING_NOTE.md` in the repo).

One note: I saw the stated deadline was Nov 1 — apologies if this is arriving just after.
I'd be grateful if it can still be considered.

Thank you for the thoughtful brief — it was a genuinely fun problem.

Best regards,
<Your name>
<phone / LinkedIn, optional>
