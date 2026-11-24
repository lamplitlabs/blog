#!/usr/bin/env python3
"""Draw the webp images for the "Unicode tricks vs prompt-injection blocklists" post
from scripts/data/unicode-injection-filters.json. Run from the repo root."""
import json
import os

from PIL import Image, ImageDraw, ImageFont

DATA = "scripts/data/unicode-injection-filters.json"
OUT_POSTS = "assets/img/posts/ai"
OUT_HEADER = "assets/img/headers/ai"
F_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
F_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
F_UNI = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
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
YELLOW = (210, 153, 34)

D = json.load(open(DATA))
TECH = D["meta"]["techniques"]
NORMS = D["meta"]["normalisers"]


def font(path, size):
    return ImageFont.truetype(path, size)


def save(img, path, quality=88):
    img.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    print("wrote", path, img.size, os.path.getsize(path), "bytes")


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rate_colour(v):
    # 0 -> red, 0.5 -> amber, 1 -> green
    return mix(RED, YELLOW, v * 2) if v < 0.5 else mix(YELLOW, GREEN, (v - 0.5) * 2)


def caught(row):
    return sum(1 for t in TECH if row[t] >= 0.999)


# ------------------------------------------------------------ heatmap
def heatmap():
    rows = [(n, D["detection"][n]) for n in NORMS]
    rows.append(("skeleton or mixed-script word", D["mixed_script_word"]["skeleton_or_mixed"]))
    W, left, top, cw, ch = 1600, 390, 360, 72, 58
    H = top + ch * len(rows) + 120
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((40, 30), "Share of 240 attacks caught, by normaliser (rows) and obfuscation (columns)",
           font=font(F_BOLD, 34), fill=FG)
    d.text((40, 78), "12-phrase blocklist, substring match after normalising; 0 of 976 benign passages flagged in every row",
           font=font(F_REG, 24), fill=MUTED)
    lab = font(F_REG, 19)
    for j, t in enumerate(TECH):
        # rotated column label
        tw = int(d.textlength(t, font=lab)) + 8
        tmp = Image.new("RGB", (tw, 26), BG)
        ImageDraw.Draw(tmp).text((2, 2), t, font=lab, fill=FG)
        tmp = tmp.rotate(60, expand=True, fillcolor=BG)
        img.paste(tmp, (left + j * cw + cw // 2 - 10, top - tmp.size[1] - 6))
    num = font(F_BOLD, 21)
    for i, (n, row) in enumerate(rows):
        y = top + i * ch
        if i == len(rows) - 1:
            d.line((40, y - 4, left + cw * len(TECH), y - 4), fill=FG, width=2)
        d.text((40, y + 16), n, font=font(F_BOLD if i == len(rows) - 1 else F_REG, 22), fill=FG)
        for j, t in enumerate(TECH):
            v = row[t]
            x = left + j * cw
            d.rectangle((x + 2, y + 2, x + cw - 2, y + ch - 2), fill=rate_colour(v))
            s = f"{v * 100:.0f}%"
            d.text((x + (cw - d.textlength(s, font=num)) / 2, y + 16), s, font=num, fill=(10, 10, 10))
        c = caught(row)
        d.text((left + cw * len(TECH) + 14, y + 18), f"{c}/15", font=font(F_BOLD, 24), fill=FG)
    d.text((left + cw * len(TECH) + 4, top - 34), "caught", font=font(F_REG, 20), fill=MUTED)
    y = top + ch * len(rows) + 30
    m = D["meta"]
    d.text((40, y), f"Python {m['python']} (Unicode {m['unicode']}), ICU {m['icu']} uspoof skeleton, Apple M2 Pro; "
           f"{m['attacks_per_technique']} attacks per column, seed {m['seed']}; scripts/unicode-injection-filters/bench.py",
           font=font(F_REG, 20), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "unicode-injection-filters-heatmap.webp"))


# ------------------------------------------------------------ token cost
def token_cost():
    tp = D["tokens_per_char"]
    toks = sorted(((t, tp["phrase0_tokens"][t]["tokens"]) for t in TECH if t != "paraphrase"), key=lambda x: x[1])
    W, H = 1600, 840
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((40, 30), "Tokens to encode \"ignore previous instructions\" (SmolLM2 tokenizer)", font=font(F_BOLD, 32), fill=FG)
    y0, bh, gap, x0, bw_max = 100, 34, 14, 330, 560
    mx = max(v for _, v in toks)
    for i, (t, v) in enumerate(toks):
        y = y0 + i * (bh + gap)
        d.text((40, y + 5), t, font=font(F_REG, 22), fill=FG)
        w = max(6, bw_max * v / mx)
        d.rounded_rectangle((x0, y, x0 + w, y + bh), radius=5, fill=BLUE if v > 3 else GREEN)
        d.text((x0 + w + 10, y + 4), str(v), font=font(F_BOLD, 22), fill=FG)
    # right panel: detection above benign max threshold
    px = 1030
    d.rounded_rectangle((px, 100, W - 40, H - 60), radius=10, fill=PANEL, outline=BORDER, width=2)
    d.text((px + 24, 120), "Flag if tokens/char > benign max", font=font(F_BOLD, 26), fill=FG)
    d.text((px + 24, 156), f"threshold {tp['threshold_max_benign']:.2f} (a German passage);",
           font=font(F_REG, 21), fill=MUTED)
    d.text((px + 24, 182), f"benign medians: English {tp['benign_median']['eng']:.2f}, "
           f"German {tp['benign_median']['deu']:.2f}", font=font(F_REG, 21), fill=MUTED)
    det = sorted(tp["detection_above_threshold"].items(), key=lambda x: -x[1])
    y = 226
    for t, v in det:
        if t in ("plain", "upper case", "paraphrase"):
            continue
        d.text((px + 24, y), t, font=font(F_REG, 20), fill=FG)
        bx = px + 290
        d.rectangle((bx, y + 2, bx + 160, y + 22), fill=(40, 45, 52))
        d.rectangle((bx, y + 2, bx + 160 * v, y + 22), fill=rate_colour(v))
        d.text((bx + 170, y), f"{v * 100:.0f}%", font=font(F_BOLD, 20), fill=FG)
        y += 34
    d.text((px + 24, y + 8), "of 240 attacks each; one phrase in a", font=font(F_REG, 20), fill=MUTED)
    d.text((px + 24, y + 32), "normal paragraph barely moves the ratio", font=font(F_REG, 20), fill=MUTED)
    d.text((40, H - 46), "Same 28 characters of meaning; the model reads all of them. Data: scripts/data/unicode-injection-filters.json",
           font=font(F_REG, 20), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "unicode-injection-filters-token-cost.webp"))


# ------------------------------------------------------------ header (40:21)
def header():
    W, H = 1500, 788
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 40):
        d.line((x, 0, x, H), fill=(20, 25, 32))
    for y in range(0, H, 40):
        d.line((0, y, W, y), fill=(20, 25, 32))
    d.text((70, 56), "Unicode tricks vs prompt-injection", font=font(F_BOLD, 64), fill=FG)
    d.text((70, 132), "blocklists, measured", font=font(F_BOLD, 64), fill=FG)
    variants = [
        ("plain", "ignore previous instructions", FG),
        ("fullwidth", "ｉｇｎｏｒｅ　ｐｒｅｖｉｏｕｓ", FG),
        ("Cyrillic look-alikes", "іgnоrе prеvіоuѕ", FG),
        ("zero-width spaces", "i\u00b7g\u00b7n\u00b7o\u00b7r\u00b7e  (\u00b7 = U+200B)", FG),
        ("tag characters", "[ 30 invisible code points ]", MUTED),
    ]
    y = 250
    for label, text, col in variants:
        d.text((70, y + 6), label, font=font(F_REG, 24), fill=MUTED)
        d.text((340, y), text, font=font(F_UNI, 34), fill=col)
        y += 70
    # bars
    px = 940
    d.rounded_rectangle((px, 240, W - 60, 600), radius=12, fill=PANEL, outline=BORDER, width=2)
    d.text((px + 30, 262), "techniques caught (of 15)", font=font(F_REG, 26), fill=MUTED)
    rows = [("lower()", caught(D["detection"]["lower()"]), RED),
            ("full pipeline", caught(D["mixed_script_word"]["skeleton_or_mixed"]), GREEN)]
    yy = 320
    for label, c, col in rows:
        d.text((px + 30, yy), label, font=font(F_BOLD, 30), fill=FG)
        d.rounded_rectangle((px + 30, yy + 46, px + 30 + 400 * c / 15, yy + 92), radius=6, fill=col)
        d.text((px + 40 + 400 * c / 15, yy + 52), f"{c}/15", font=font(F_BOLD, 34), fill=FG)
        yy += 130
    m = D["meta"]
    tot = m["attacks_per_technique"] * len(TECH)
    ben = m["benign_passages"]["eng"] + m["benign_passages"]["deu"]
    d.text((70, 660), f"{tot:,} attacks, {ben} benign passages, 0 false positives", font=font(F_BOLD, 34), fill=GREEN)
    d.text((70, 714), "still missed by every pipeline: leetspeak, spaced letters, paraphrase", font=font(F_REG, 28),
           fill=ORANGE)
    save(img, os.path.join(OUT_HEADER, "ai-security-unicode-obfuscation-filters.webp"), quality=90)


if __name__ == "__main__":
    heatmap()
    token_cost()
    header()
