# How to submit — step by step

Everything ENAM asked for, and exactly how to send it. Budget ~20 minutes.

> ⚠️ **Deadline check first.** The brief's deadline was **Sun, Nov 1 2026**. Today is
> past that. Before anything else, send a one-line email to `assessment@enam.com`
> asking whether a late submission is accepted (IIT-screening tracks often allow a
> short grace). If yes, proceed below.

---

## 1. Put it on GitHub (~5 min)

```bash
cd finn-enam
git init
git add .
git commit -m "FINN — mobile-first financial investment agent (ENAM build challenge)"
# create an empty repo named finn-enam on github.com first, then:
git branch -M main
git remote add origin https://github.com/<your-username>/finn-enam.git
git push -u origin main
```

Keep the repo **public** (or add `assessment@enam.com`'s GitHub as a collaborator if private).

## 2. Deploy the prototype so they can try it on a phone (~5 min)

The app is a single static file, so any static host works. Easiest: **GitHub Pages**.

1. Repo → **Settings → Pages**.
2. Source: **Deploy from a branch** → `main` → `/ (root)` → **Save**.
3. Wait ~1 min. Your live link is: `https://<your-username>.github.io/finn-enam/`

*(Alternatives: drag the folder onto [netlify.com/drop](https://app.netlify.com/drop),
or `npx vercel` in the folder. Any of them gives a phone-openable URL.)*

Open the link on your phone to confirm it looks right before sending.

## 3. Export your AI build history (~3 min)

ENAM explicitly wants to see how you worked with the tools.
- **This Claude session** is itself part of that history — use the share/export option
  in your Claude client to get a link or a PDF/markdown export.
- Add any other coding-agent / ChatGPT / Cursor sessions you used.
- Either paste share links in the email, or drop exports into a `build-history/` folder
  in the repo and link it.

## 4. Send the email

- **To:** `assessment@enam.com`
- **Subject:** `ENAM - IIT screening - 2027`
- **Body:** use the draft in [`EMAIL_DRAFT.md`](EMAIL_DRAFT.md) — fill in the three
  `<...>` links, attach `COVERING_NOTE.md` (or paste it), and send.

## Final checklist

- [ ] Asked about / confirmed late-submission is OK
- [ ] GitHub repo pushed and accessible
- [ ] Live prototype URL opens on a phone
- [ ] AI build-history link(s) included
- [ ] Covering note included (what you built, decisions, trade-offs, what's left out, next)
- [ ] Email subject is exactly `ENAM - IIT screening - 2027`
- [ ] Sent to `assessment@enam.com`
