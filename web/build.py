#!/usr/bin/env python3
"""Inject data/finn_data.json into the app template -> self-contained index.html.

Research entries that carry raw `commitments` + a quarterly `series` are scored by
backend/commitments.py here, so every verdict in the shipped app is the output of
the deterministic engine, never hand-written."""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import commitments  # noqa: E402  (pure Python, no third-party deps)

data = commitments.attach_ledgers(json.loads((ROOT / "data" / "finn_data.json").read_text(encoding="utf-8")))

tpl = (ROOT / "web" / "app_template.html").read_text(encoding="utf-8")
start, end = "/*__FINN_DATA__*/", "/*__END__*/"
i, j = tpl.index(start), tpl.index(end) + len(end)
# "</" is escaped so no string in the data can close the <script> element early.
blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
out = tpl[:i] + start + blob + end + tpl[j:]

(ROOT / "index.html").write_text(out, encoding="utf-8")
print(f"Built index.html ({len(out):,} bytes) with {len(data['portfolio'])} holdings, "
      f"{len(data['announcements'])} announcements, {len(data['research'])} full research views.")
