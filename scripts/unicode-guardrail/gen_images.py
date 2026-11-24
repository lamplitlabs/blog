#!/usr/bin/env python3
"""Build the webp images for the "Unicode tricks vs keyword guardrails, measured" post.

Usage: python3 scripts/unicode-guardrail/gen_images.py [browser-shot.png]

Reads scripts/data/unicode-guardrail-evasion.json (written by bench.py). Every number drawn comes from that
file. With a browser screenshot of examples.html (see README in the post), it also writes the screenshot as
webp, cropped to the page content.
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

DATA = "scripts/data/unicode-guardrail-evasion.json"
OUT_POSTS = "assets/img/posts/ai"
OUT_HEADER = "assets/img/headers/ai"
F_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
F_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
F_MONO = "/System/Library/Fonts/Menlo.ttc"

BG = (13, 17, 23)
PANEL = (22, 27, 34)
BORDER = (48, 54, 61)
FG = (230, 237, 243)
MUTED = (139, 148, 158)
BLUE = (88, 166, 255)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
ORANGE = (240, 136, 62)

D = json.load(open(DATA))
FILTERS = [f["key"] for f in D["filters"]]
FLABEL = {f["key"]: f["label"] for f in D["filters"]}
TRANS = D["transforms"]


def font(path, size):
    return ImageFont.truetype(path, size)


def save(img, path, quality=88):
    img.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    print("wrote", path, img.size, os.path.getsize(path), "bytes")


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def heat_colour(frac):
    # red (missed everything) -> amber -> green (caught everything)
    if frac < 0.5:
        return mix((122, 28, 28), (125, 90, 20), frac * 2)
    return mix((125, 90, 20), (26, 110, 50), (frac - 0.5) * 2)


def centred(d, x, y, text, f, fill):
    w = d.textlength(text, font=f)
    d.text((x - w / 2, y), text, font=f, fill=fill)


def heatmap():
    W, H = 1600, 900
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((40, 28), "Disguised injection phrases caught, per input filter", font=font(F_BOLD, 34), fill=FG)
    d.text((40, 74), f"12 phrases x 10 disguises, seeded; cell = caught / variants. Python {D['env']['python']}, "
           f"Unicode {D['env']['unicodedata']} tables. Each column adds one step to the one before it, except the last.",
           font=font(F_REG, 19), fill=MUTED)
    left, top = 430, 200
    cw, ch = (W - left - 30) // len(FILTERS), 58
    hf = font(F_BOLD, 17)
    for j, k in enumerate(FILTERS):
        words = FLABEL[k].split(" ")
        # two-line column heads
        l1, l2 = [], []
        for wd in words:
            (l1 if d.textlength(" ".join(l1 + [wd]), font=hf) < cw - 12 and not l2 else l2).append(wd)
        cx = left + j * cw + cw / 2
        centred(d, cx, top - 62, " ".join(l1), hf, FG)
        centred(d, cx, top - 38, " ".join(l2), hf, FG)
    cf = font(F_BOLD, 22)
    for i, t in enumerate(TRANS):
        y = top + i * ch
        d.text((40, y + 17), t["label"], font=font(F_REG, 19), fill=FG)
        n = t["variants"]
        for j, k in enumerate(FILTERS):
            c = D["caught"][t["key"]][k]
            x = left + j * cw
            d.rectangle((x + 3, y + 3, x + cw - 3, y + ch - 3), fill=heat_colour(c / n))
            centred(d, x + cw / 2, y + 16, f"{c}/{n}", cf, FG)
    y = top + len(TRANS) * ch + 22
    fp = D["benign"]["false_positives"]
    us = {k: D["timing"][k]["median_us_per_line"] for k in FILTERS}
    d.text((40, y + 4), f"False positives, {D['benign']['lines']:,} benign lines", font=font(F_REG, 19), fill=FG)
    d.text((40, y + 34), "Median µs per benign line", font=font(F_REG, 19), fill=FG)
    for j, k in enumerate(FILTERS):
        cx = left + j * cw + cw / 2
        centred(d, cx, y + 2, f"{fp[k]:,}", font(F_BOLD, 21), RED if fp[k] else GREEN)
        centred(d, cx, y + 32, f"{us[k]:.0f}", font(F_BOLD, 21), MUTED)
    save(img, os.path.join(OUT_POSTS, "unicode-guardrail-heatmap.webp"))


def cost_chart():
    W, H = 1600, 760
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    b = D["benign"]
    d.text((40, 28), "What each filter costs on real English and German text", font=font(F_BOLD, 34), fill=FG)
    d.text((40, 74), f"{b['lines']:,} distinct lines ({b['lines_by_lang']['en']:,} English, {b['lines_by_lang']['de']:,} German) "
           f"from Belebele, GSM8K-X and TruthfulQA-X; none is an attack.", font=font(F_REG, 19), fill=MUTED)
    rows = FILTERS
    left, top, rh = 420, 150, 74
    maxus = max(D["timing"][k]["median_us_per_line"] for k in rows)
    barw = 560
    d.text((left, top - 34), "Median µs per line (5 passes)", font=font(F_BOLD, 18), fill=BLUE)
    fx = left + barw + 140
    d.text((fx, top - 34), "Benign lines flagged (false positives)", font=font(F_BOLD, 18), fill=RED)
    for i, k in enumerate(rows):
        y = top + i * rh
        d.text((40, y + 18), FLABEL[k], font=font(F_REG, 21), fill=FG)
        us = D["timing"][k]["median_us_per_line"]
        w = max(4, int(barw * us / maxus))
        d.rectangle((left, y + 14, left + w, y + 50), fill=BLUE)
        d.text((left + w + 10, y + 19), f"{us:.1f} µs", font=font(F_BOLD, 20), fill=FG)
        fp = b["false_positives"][k]
        frac = fp / b["lines"]
        fw = int(barw * 0.75 * frac)
        if fw:
            d.rectangle((fx, y + 14, fx + fw, y + 50), fill=RED)
        en, de = b["false_positives_by_lang"][k]["en"], b["false_positives_by_lang"][k]["de"]
        label = f"{fp:,}  ({frac:.0%}: {en:,} EN, {de:,} DE)" if fp else "0"
        d.text((fx + fw + 10, y + 19), label, font=font(F_BOLD, 20), fill=RED if fp else GREEN)
    y = top + len(rows) * rh + 10
    cf = ", ".join(f"{k.split(' ', 1)[1].title()} x{v}" for k, v in b["cf_chars"].items())
    d.text((40, y), f"Invisible format characters already in the benign text: {b['lines_with_cf']} lines ({cf}).",
           font=font(F_REG, 19), fill=MUTED)
    d.text((40, y + 30), f"{b['lines_non_ascii']:,} of {b['lines']:,} lines hold at least one non-ASCII character "
           "(umlauts, ß, dashes, curly quotes, accented names).", font=font(F_REG, 19), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "unicode-guardrail-cost.webp"))


def header():
    W, H = 1600, 840
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((24, 24, W - 24, H - 24), radius=22, fill=PANEL, outline=BORDER, width=2)
    d.text((80, 80), "AI SECURITY · MEASURED", font=font(F_BOLD, 26), fill=ORANGE)
    d.text((80, 124), "Unicode tricks vs keyword guardrails", font=font(F_BOLD, 64), fill=FG)
    d.text((80, 206), "One invisible character, one look-alike letter: how many disguised", font=font(F_REG, 30), fill=MUTED)
    d.text((80, 244), "prompt injections a regex input filter still catches.", font=font(F_REG, 30), fill=MUTED)
    rows = [("invisible", "One zero-width char"), ("homoglyph", "One look-alike letter"), ("tags", "Unicode tag smuggling"),
            ("bidi", "Bidi override")]
    cols = [("raw", "Regex on raw text"), ("strip", "NFKC + strip Cf"), ("reject", "Full pipeline")]
    left, top, cw, ch = 520, 360, 330, 82
    for j, (k, lab) in enumerate(cols):
        centred(d, left + j * cw + cw / 2, top - 44, lab, font(F_BOLD, 26), FG)
    for i, (tk, lab) in enumerate(rows):
        y = top + i * ch
        d.text((80, y + 22), lab, font=font(F_REG, 30), fill=FG)
        n = next(t["variants"] for t in TRANS if t["key"] == tk)
        for j, (fk, _) in enumerate(cols):
            c = D["caught"][tk][fk]
            x = left + j * cw
            d.rounded_rectangle((x + 8, y + 6, x + cw - 8, y + ch - 6), radius=10, fill=heat_colour(c / n))
            centred(d, x + cw / 2, y + 22, f"{c / n:.0%} caught", font(F_BOLD, 30), FG)
    save(img, os.path.join(OUT_HEADER, "ai-security-unicode-guardrail-evasion.webp"), quality=90)


def browser_shot(png):
    im = Image.open(png).convert("RGB")
    # crop the white page margin below the table: last row that is not pure white
    px = im.load()
    W, H = im.size
    bottom = H - 1
    while bottom > 0 and all(px[x, bottom] == (255, 255, 255) for x in range(0, W, 7)):
        bottom -= 1
    im = im.crop((0, 0, W, min(H, bottom + 24)))
    save(im, os.path.join(OUT_POSTS, "unicode-guardrail-browser-view.webp"), quality=90)


if __name__ == "__main__":
    os.makedirs(OUT_POSTS, exist_ok=True)
    os.makedirs(OUT_HEADER, exist_ok=True)
    heatmap()
    cost_chart()
    header()
    if len(sys.argv) > 1:
        browser_shot(sys.argv[1])
