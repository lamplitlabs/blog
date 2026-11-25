#!/usr/bin/env python3
"""Build the two webp images for the "Unicode tricks vs keyword guardrails" post.

Usage: python3 scripts/guardrail-unicode/gen_images.py

Reads scripts/data/guardrail-unicode.json (written by bench.py). Every number
drawn comes from that file; nothing is typed in by hand.
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

DATA = "scripts/data/guardrail-unicode.json"
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
GREEN = (63, 185, 80)
RED = (248, 81, 73)
YELLOW = (210, 153, 34)
BLUE = (88, 166, 255)

D = json.load(open(DATA))
COLS = [g["name"] for g in D["guards"]] + ["suspicious"]
COL_LABEL = {
    "raw": ["regex", "on raw text"],
    "nfkc": ["NFKC", "then regex"],
    "nfkc_cf": ["NFKC + casefold", "+ drop Cf"],
    "fold_late": ["+ marks, tags,", "fold after casefold"],
    "fold": ["+ marks, tags,", "fold before casefold"],
    "suspicious": ["detector:", "odd characters"],
}
ROW_LABEL = {
    "plain": "plain text (control)",
    "zero_width": "zero-width space U+200B",
    "soft_hyphen": "soft hyphen U+00AD",
    "fullwidth": "fullwidth forms",
    "math_bold": "math sans-serif bold",
    "combining": "combining accent U+0301",
    "cyrillic": "Cyrillic look-alikes",
    "greek_zwnj": "Greek look-alikes + ZWNJ",
    "tag_chars": "invisible tag characters",
    "small_caps": "phonetic small capitals",
}


def font(path, size):
    return ImageFont.truetype(path, size)


def save(img, path, quality=88):
    img.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    print("wrote", path, img.size, os.path.getsize(path), "bytes")


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def cell_colour(n, total=20):
    t = n / total
    return mix((96, 30, 30), (30, 100, 48), t)


def totals():
    tricks = [t["name"] for t in D["tricks"] if t["name"] != "plain"]
    return {c: sum(D["grid"][t][c] for t in tricks) for c in COLS}, len(tricks) * 20


def header():
    W, H = 1600, 840
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((20, 20, W - 20, H - 20), radius=18, fill=PANEL, outline=BORDER, width=2)
    d.text((70, 62), "Unicode tricks vs keyword guardrails, measured", font=font(F_BOLD, 52), fill=FG)
    d.text((70, 134), "20 prompt-injection lines x 9 Unicode rewrites = 180 lines. How many does each guard catch?",
           font=font(F_REG, 28), fill=MUTED)
    tot, n = totals()
    labels = {
        "raw": "regex on the raw text",
        "nfkc": "NFKC first",
        "nfkc_cf": "NFKC + casefold + drop format chars",
        "fold_late": "+ tags, marks, look-alikes (folded late)",
        "fold": "+ tags, marks, look-alikes (folded early)",
        "suspicious": "detector: format chars / non-Latin letters",
    }
    x0, x1 = 760, 1420
    y = 220
    for c in COLS:
        v = tot[c]
        d.text((70, y + 8), labels[c], font=font(F_REG, 30), fill=FG)
        d.rectangle((x0, y, x1, y + 56), fill=(33, 38, 45))
        w = int((x1 - x0) * v / n)
        colour = GREEN if v == n else (YELLOW if v >= n / 2 else RED)
        if w:
            d.rectangle((x0, y, x0 + w, y + 56), fill=colour)
        d.text((x1 + 20, y + 8), f"{v}/{n}", font=font(F_BOLD, 32), fill=FG)
        y += 82
    note = (f"Best guard still missed {n - tot['fold']} lines (phonetic small capitals). "
            f"Benign: {D['benign_corpus']['lines']:,} lines of this blog, "
            f"{D['benign_corpus']['guards']['fold']['flagged_lines']} flagged by every guard.")
    d.text((70, y + 22), note, font=font(F_REG, 26), fill=MUTED)
    d.text((70, H - 78), f"Python {D['python']} re + unicodedata {D['unicodedata']}, scripts/guardrail-unicode/bench.py",
           font=font(F_MONO, 22), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, "ai-security-guardrail-unicode-obfuscation.webp"))


def grid():
    rows = [t["name"] for t in D["tricks"]]
    lw, cw, ch = 400, 200, 58
    top = 190
    W = 40 + lw + cw * len(COLS) + 40
    H = top + ch * len(rows) + 110
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((40, 30), "Lines flagged out of 20, per Unicode trick and guard", font=font(F_BOLD, 34), fill=FG)
    d.text((40, 78), "Same five keyword regexes in every column; only the text normalisation before them changes.",
           font=font(F_REG, 22), fill=MUTED)
    for j, c in enumerate(COLS):
        x = 40 + lw + j * cw
        for k, part in enumerate(COL_LABEL[c]):
            f = font(F_BOLD if k == 0 else F_REG, 20)
            tw = d.textlength(part, font=f)
            d.text((x + cw / 2 - tw / 2, 120 + k * 26), part, font=f, fill=BLUE if c == "suspicious" else FG)
    for i, r in enumerate(rows):
        y = top + i * ch
        d.text((40, y + 16), ROW_LABEL[r], font=font(F_REG, 24), fill=FG)
        for j, c in enumerate(COLS):
            x = 40 + lw + j * cw
            v = D["grid"][r][c]
            col = cell_colour(v)
            if c == "suspicious" and r == "plain":
                col = cell_colour(20)  # 0 on clean text is the right answer for a detector
            d.rectangle((x + 3, y + 3, x + cw - 3, y + ch - 3), fill=col)
            s = str(v)
            f = font(F_BOLD, 26)
            tw = d.textlength(s, font=f)
            d.text((x + cw / 2 - tw / 2, y + 14), s, font=f, fill=FG)
    bc = D["benign_corpus"]
    yb = top + ch * len(rows) + 22
    d.text((40, yb), f"Benign text, {bc['lines']:,} body lines of this blog: every regex column flags "
                     f"{bc['guards']['raw']['flagged_lines']} lines (both quote an attack); the detector flags "
                     f"{bc['guards']['suspicious']['flagged_lines']} lines in {len(bc['guards']['suspicious']['flagged_files'])} posts.",
           font=font(F_REG, 22), fill=MUTED)
    d.text((40, yb + 36), f"Python {D['python']}, unicodedata {D['unicodedata']}. Data: scripts/data/guardrail-unicode.json",
           font=font(F_MONO, 18), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "guardrail-unicode-grid.webp"))


if __name__ == "__main__":
    header()
    grid()
