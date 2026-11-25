#!/usr/bin/env python3
"""Draw the webp images for the "Enterprise AI: what JSON costs in an LLM prompt" post.

    python3 scripts/enterprise-ai-prompt-formats/gen_images.py --term .tmp/formats-term.txt \
        --shot .tmp/token-view-crop.png

Every number comes from scripts/data/enterprise-ai-prompt-formats.json (measure.py). --term is the
captured stdout of measure.py, drawn verbatim. --shot is a headless-browser screenshot of the page
token_view.py writes, re-encoded as webp unchanged.
"""
import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data", "enterprise-ai-prompt-formats.json")
OUT_POSTS = "assets/img/posts/ai"
OUT_HEADER = "assets/img/headers/ai"
SLUG = "enterprise-ai-prompt-data-formats-token-cost"

F_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
F_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
F_MONO = "/System/Library/Fonts/Menlo.ttc"

BG = (13, 17, 23)
PANEL = (22, 27, 34)
BORDER = (48, 54, 61)
GRID = (33, 38, 45)
FG = (230, 237, 243)
MUTED = (139, 148, 158)
BLUE = (88, 166, 255)
GREEN = (63, 185, 80)
ORANGE = (240, 136, 62)
RED = (248, 81, 73)
YELLOW = (210, 168, 70)
PURPLE = (188, 140, 255)

D = json.load(open(DATA))
S = D["setup"]
F = D["formats"]
ORDER = ["xml", "json_pretty", "yaml", "json_min", "markdown", "csv"]
COL = {"xml": RED, "json_pretty": ORANGE, "yaml": YELLOW, "json_min": PURPLE, "markdown": BLUE, "csv": GREEN}


def font(path, size):
    return ImageFont.truetype(path, size)


def save(img, path, quality=88):
    img.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    print("wrote", path, img.size, os.path.getsize(path), "bytes")


class FitDraw(ImageDraw.ImageDraw):
    """ImageDraw that fails loudly when a text line runs past the right frame edge."""

    def text(self, xy, text, *a, **kw):
        f = kw.get("font")
        if f is not None and "\n" not in text:
            right = xy[0] + self.textlength(text, font=f)
            if right > self.im.size[0] - 16:
                raise SystemExit(f"text overflows image ({right:.0f} > {self.im.size[0] - 16}): {text!r}")
        return super().text(xy, text, *a, **kw)


def frame(W, H):
    img = Image.new("RGB", (W, H), BG)
    d = FitDraw(img)
    d.rounded_rectangle((12, 12, W - 12, H - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    return img, d


def setup_line():
    return (f"{len(S['fields'])}-field vendor invoices, seed {S['seed']}  |  {S['model'].replace('.gguf', '')} tokenizer via "
            f"llama-server /tokenize  |  {S['n_ctx']:,}-token context, {S['reserve']:,} reserved")


# ------------------------------------------------------------------ header 40:21
def header():
    W, H = 1600, 840
    img, d = frame(W, H)
    d.text((70, 66), "Enterprise AI  |  prompt cost  |  measured", font=font(F_BOLD, 30), fill=BLUE)
    d.text((70, 116), "What JSON costs", font=font(F_BOLD, 74), fill=FG)
    d.text((70, 200), "in an LLM prompt", font=font(F_BOLD, 74), fill=FG)
    d.text((70, 300), "Tokens per ERP invoice record, same 12 fields, six formats", font=font(F_REG, 28), fill=MUTED)
    left, right, top = 360, W - 200, 356
    vmax = max(F[f]["tokens_per_record"] for f in ORDER)
    bh, gap = 44, 14
    for i, f in enumerate(ORDER):
        y = top + i * (bh + gap)
        r = F[f]
        d.text((70, y + 7), r["label"], font=font(F_BOLD, 26), fill=COL[f])
        x1 = left + (right - left) * r["tokens_per_record"] / vmax
        d.rounded_rectangle((left, y, x1, y + bh), radius=8, fill=COL[f])
        d.text((x1 + 14, y + 6), f"{r['tokens_per_record']:.0f}", font=font(F_BOLD, 28), fill=FG)
    d.text((70, H - 62), setup_line(), font=font(F_REG, 21), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, SLUG + ".webp"))


# ------------------------------------------------------------------ three panels
def panels():
    W, H = 1400, 700
    img, d = frame(W, H)
    d.text((50, 40), "Same records, six formats: token cost, context fit and prefill time", font=font(F_BOLD, 32), fill=FG)
    pre = F["csv"]["prefill"]
    d.text((50, 86), f"Left: tokens per invoice record. Middle: records that fit in {S['n_ctx']:,} tokens with {S['reserve']:,} reserved. "
                     f"Right: prefill ms for {pre['records']} records,", font=font(F_REG, 20), fill=MUTED)
    d.text((50, 114), f"median of {S['reps']} runs, cache_prompt off (Metal, M2 Pro). Longest bar in each panel = 100%.",
           font=font(F_REG, 20), fill=MUTED)
    cols = [("tokens / record", lambda r: r["tokens_per_record"], "{:.0f}"),
            ("records that fit", lambda r: r["records_fit"], "{:d}"),
            (f"prefill ms ({pre['records']} records)", lambda r: r["prefill"]["ms_median"], "{:.0f}")]
    label_w = 230
    top = 190
    bh, gap = 52, 22
    pw = (W - 100 - label_w) // 3
    for i, f in enumerate(ORDER):
        y = top + i * (bh + gap)
        d.text((50, y + 13), F[f]["label"], font=font(F_BOLD, 23), fill=COL[f])
    for c, (title, get, fmt) in enumerate(cols):
        x0 = 50 + label_w + c * pw
        d.text((x0, top - 40), title, font=font(F_BOLD, 22), fill=FG)
        vmax = max(get(F[f]) for f in ORDER)
        for i, f in enumerate(ORDER):
            y = top + i * (bh + gap)
            v = get(F[f])
            x1 = x0 + (pw - 110) * v / vmax
            d.rounded_rectangle((x0, y, max(x1, x0 + 6), y + bh), radius=6, fill=COL[f])
            d.text((x1 + 10, y + 12), fmt.format(v), font=font(F_BOLD, 24), fill=FG)
    d.text((50, H - 56), setup_line(), font=font(F_REG, 19), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, SLUG + "-panels.webp"))


def terminal(path):
    lines = [l.rstrip("\n") for l in open(path)]
    while lines and not lines[-1].strip():
        lines.pop()
    fm = font(F_MONO, 19)
    W = 1400
    H = 110 + 28 * len(lines) + 40
    img, d = frame(W, H)
    for i, c in enumerate((RED, YELLOW, GREEN)):
        d.ellipse((40 + i * 26, 34, 56 + i * 26, 50), fill=c)
    d.text((140, 30), "$ python3 scripts/enterprise-ai-prompt-formats/measure.py --port 8093 --prefill-records 30 --out ...",
           font=font(F_MONO, 17), fill=MUTED)
    y = 86
    for l in lines:
        key = l.split()[0] if l.split() else ""
        d.text((40, y), l, font=fm, fill=COL.get(key, FG if key in ("format", "model", "prefill") else MUTED))
        y += 28
    save(img, os.path.join(OUT_POSTS, SLUG + "-terminal.webp"))


def shot(path):
    im = Image.open(path)
    save(im, os.path.join(OUT_POSTS, SLUG + "-token-view.webp"), quality=90)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--term")
    ap.add_argument("--shot")
    a = ap.parse_args()
    header()
    panels()
    if a.term:
        terminal(a.term)
    if a.shot:
        shot(a.shot)


if __name__ == "__main__":
    main()
