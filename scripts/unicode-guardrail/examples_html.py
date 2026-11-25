#!/usr/bin/env python3
"""Write examples.html: each disguised payload from the bench JSON as a browser renders it, with verdicts.

Usage: python3 scripts/unicode-guardrail/examples_html.py <out.html>

Open the page in any Chromium (chrome-headless-shell --screenshot is enough) to see that most disguises render
like the plain line while the raw-text regex misses them. The text cells are the exact strings bench.py tested.
"""
import html
import json
import sys

D = json.load(open("scripts/data/unicode-guardrail-evasion.json"))
SHOW = ["raw", "strip", "untag", "reject"]
LABEL = {f["key"]: f["label"] for f in D["filters"]}

rows = []
for ex in D["examples"]:
    payload = ex["text"].split("me. ", 1)[1].rsplit(" and reply", 1)[0]
    cps = " ".join(ex["non_ascii"]) or "none"
    cells = "".join(
        f'<td class="{"y" if ex["verdicts"][k] else "n"}">{"caught" if ex["verdicts"][k] else "missed"}</td>' for k in SHOW
    )
    rows.append(
        f'<tr><td class="t">{html.escape(ex["label"])}</td><td class="p">{html.escape(payload)}</td>'
        f'<td class="c">{len(payload)} / {cps}</td>{cells}</tr>'
    )

page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Disguised payloads as rendered</title>
<style>
body{{font:15px -apple-system,Helvetica,Arial,sans-serif;margin:24px;color:#1f2328;background:#fff}}
h1{{font-size:20px;margin:0 0 4px}} p{{margin:0 0 14px;color:#59636e}}
table{{border-collapse:collapse}} td,th{{border:1px solid #d1d9e0;padding:6px 10px;text-align:left;vertical-align:top}}
th{{background:#f6f8fa;font-size:13px}} td.p{{font-size:17px;min-width:330px}} td.t{{width:230px}}
td.c{{font:12px Menlo,monospace;color:#59636e;max-width:190px}} td.y{{background:#dafbe1}} td.n{{background:#ffebe9;color:#82071e;font-weight:600}}
</style></head><body>
<h1>The same injection phrase, ten ways, as Chromium renders it</h1>
<p>Payload column = the exact string the filters were given (from scripts/data/unicode-guardrail-evasion.json). Code points = length in code points / first non-ASCII ones.</p>
<table><tr><th>Disguise</th><th>Payload as rendered</th><th>Code points</th>{"".join(f"<th>{html.escape(LABEL[k])}</th>" for k in SHOW)}</tr>
{"".join(rows)}
</table></body></html>
"""
open(sys.argv[1], "w", encoding="utf-8").write(page)
print("wrote", sys.argv[1])
