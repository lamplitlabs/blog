#!/usr/bin/env python3
"""Write an HTML page that shows where the model's tokenizer splits one invoice record per format.

Each token from llama-server's POST /tokenize (with_pieces) gets its own coloured box, so the
reader can see which tokens carry data and which only repeat keys, quotes and tags.

    python3 scripts/enterprise-ai-prompt-formats/token_view.py --port 8093 --out .tmp/token-view.html

The page is then screenshotted with a headless browser for the post. Standard library only.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from measure import FIELDS, LABEL, post, records, serialise  # noqa: E402

SHOW = ["json_pretty", "yaml", "csv"]
COLS = ["#1f3a5f", "#3b2a4f", "#1f4a3a", "#4a3a1f"]


def pieces(port: int, text: str) -> list[str]:
    toks = post(port, "/tokenize", {"content": text, "add_special": False, "with_pieces": True})["tokens"]
    return [t["piece"] if isinstance(t["piece"], str) else bytes(t["piece"]).decode("utf-8", "replace") for t in toks]


def value_mask(text: str, row: dict, fmt: str) -> list[bool]:
    """True for every character of text that belongs to a field value (found in field order)."""
    mask = [False] * len(text)
    cur = text.index("\n") + 1 if fmt in ("csv", "markdown") else 0  # skip the header line
    for k in FIELDS:
        v = str(row[k])
        if fmt == "xml":
            v = escape(v)
        i = text.index(v, cur)
        for j in range(i, i + len(v)):
            mask[j] = True
        cur = i + len(v)
    return mask


def block(port: int, fmt: str, text: str, row: dict) -> str:
    ps = pieces(port, text)
    assert "".join(ps) == text, "pieces do not rebuild the text"
    mask = value_mask(text, row, fmt)
    out, pos, n_data = [], 0, 0
    for i, p in enumerate(ps):
        is_data = sum(mask[pos:pos + len(p)]) * 2 > len(p)
        pos += len(p)
        n_data += is_data
        esc = html.escape(p).replace("\n", "&#8629;<br>").replace(" ", "&nbsp;")
        cls = "d" if is_data else "s"
        out.append(f'<span class="t {cls}" style="background:{COLS[i % len(COLS)]}">{esc}</span>')
    print(f"{fmt}: {len(ps)} tokens, {n_data} value, {len(ps) - n_data} structure")
    return (f'<section><h2>{html.escape(LABEL[fmt])} <em>{len(ps)} tokens: {n_data} carry values, '
            f'{len(ps) - n_data} are keys, quotes, indentation and separators</em></h2>'
            f'<div class="code">{"".join(out)}</div></section>')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8093)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = records(1)
    secs = []
    for fmt in SHOW:
        text = serialise(rows, fmt)
        secs.append(block(a.port, fmt, text, rows[0]))
    page = f"""<!doctype html><meta charset="utf-8"><title>Token view</title>
<style>
body {{ background:#0d1117; color:#e6edf3; font:15px Menlo, monospace; margin:24px; }}
h1 {{ font:bold 24px Arial, sans-serif; margin:0 0 4px; }}
p.sub {{ font:15px Arial, sans-serif; color:#8b949e; margin:0 0 18px; }}
section {{ border:1px solid #30363d; border-radius:8px; padding:12px 14px; margin-bottom:14px; background:#161b22; }}
h2 {{ font:bold 17px Arial, sans-serif; margin:0 0 8px; color:#58a6ff; }}
h2 em {{ font-style:normal; font-weight:normal; color:#8b949e; margin-left:10px; }}
.code {{ line-height:1.9; }}
.t {{ border-radius:3px; padding:1px 0; margin-right:1px; }}
.t.s {{ color:#8b949e; }}
.t.d {{ color:#ffffff; font-weight:bold; }}
</style>
<h1>One vendor invoice, three formats, split by the model's tokenizer</h1>
<p class="sub">Each box is one token from llama-server /tokenize (SmolLM2-135M-Instruct). Bold white = part of a field value;
grey = keys, quotes, indentation, separators.</p>
{"".join(secs)}
"""
    with open(a.out, "w") as f:
        f.write(page)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
