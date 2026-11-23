#!/usr/bin/env python3
"""Build the webp images for the "ReDoS in AI guardrails, measured" post.

Usage: python3 scripts/guardrail-redos/gen_images.py

Reads scripts/data/guardrail-redos-m2pro.json (written by summarise.py from a
measure.sh run). Terminal panels print the raw shots/*.txt text kept in that JSON,
cut to the panel width but otherwise unedited. Nothing is typed in by hand.
"""
import json
import math
import os

from PIL import Image, ImageDraw, ImageFont

DATA = "scripts/data/guardrail-redos-m2pro.json"
OUT_POSTS = "assets/img/posts/ai"
OUT_HEADER = "assets/img/headers/ai"

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
PURPLE = (188, 140, 255)
YELLOW = (210, 153, 34)
RUST = (222, 165, 132)

D = json.load(open(DATA))
ENGINES = ["python", "node", "nodefb", "go", "rust"]
LABEL = {
    "python": "Python 3.13 re",
    "node": "Node 22 (V8 Irregexp)",
    "nodefb": "Node 22 + linear fallback flag",
    "go": "Go 1.27 regexp",
    "rust": "Rust regex 1.13",
}
SHORT = {"python": "Python re", "node": "Node", "nodefb": "Node+fallback", "go": "Go regexp", "rust": "Rust regex"}
COL = {"python": BLUE, "node": ORANGE, "nodefb": YELLOW, "go": PURPLE, "rust": RUST}
CAP_MS = D["cap_s"] * 1000


def font(path, size):
    return ImageFont.truetype(path, size)


def save(img, path, quality=85):
    img.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    print("wrote", path, img.size, os.path.getsize(path), "bytes")


def cell(kind, engine, rule, variant, n):
    for b in D["bench"]:
        if (b["kind"], b["engine"], b["rule"], b["variant"], b["n"]) == (kind, engine, rule, variant, n):
            return b
    return None


def fmt_ms(ms, capped=False):
    if capped:
        return f"> {ms / 1000:,.0f} s (killed)"
    if ms >= 1000:
        return f"{ms / 1000:,.1f} s"
    if ms >= 1:
        return f"{ms:,.1f} ms"
    if ms >= 0.01:
        return f"{ms * 1000:,.0f} µs"
    if ms >= 0.001:
        return f"{ms * 1000:,.1f} µs"
    return f"{ms * 1e6:,.0f} ns"


def host_line():
    h = D["host"]
    cpu = h["host"].split(",")[0]
    return f'{cpu}, {h["python"]}, node {h["node"]}, {h["go"].split()[2]}, {h["rustc"].split(" (")[0]}'


def natural_text(rule, k):
    rules = json.load(open("scripts/guardrail-redos/rules.json"))["rules"]
    r = next(x for x in rules if x["name"] == rule)
    n = r["natural"]
    return n["prefix"] + n["sep"].join(n["words"][:k]) + n["suffix"]


# ------------------------------------------------------------ terminal panel
def terminal(lines, out, width=1500, title="zsh", colour=None, size=19):
    mono = font(F_MONO, size)
    line_h = int(size * 1.45)
    top = 56
    height = top + 24 + line_h * len(lines) + 24
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, width - 12, height - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    for i, c in enumerate((RED, ORANGE, GREEN)):
        d.ellipse((34 + i * 26, 30, 48 + i * 26, 44), fill=c)
    tw = d.textlength(title, font=font(F_REG, 18))
    d.text((width / 2 - tw / 2, 26), title, font=font(F_REG, 18), fill=MUTED)
    y = top + 16
    maxw = width - 72
    for ln in lines:
        while d.textlength(ln, font=mono) > maxw:
            ln = ln[:-2] + "…"
        d.text((36, y), ln, font=mono, fill=colour(ln) if colour else FG)
        y += line_h
    save(img, os.path.join(OUT_POSTS, out))


def curl_panel():
    raw = D["shots"]["curl.txt"].splitlines()
    lines = []
    for ln in raw:
        if ln.startswith("$ "):
            ln = ln.replace("localhost:", "localhost:")
        lines.append(ln)

    def colour(ln):
        if ln.startswith("$"):
            return MUTED
        try:
            secs = float(ln.rsplit(" ", 1)[1].rstrip("s"))
        except (ValueError, IndexError):
            return FG
        return RED if secs > 0.5 else GREEN
    terminal(lines, "guardrail-redos-curl-poison.webp", title="one 37-byte request to each guard service (curl)",
             colour=colour, size=18)


def compile_panel():
    raw = D["shots"]["compile.txt"].splitlines()
    lines = [raw[0]]
    for ln in raw[1:]:
        c = ln.split("\t")
        lines.append(f"{c[2]:<14} {c[3]:<29} {c[4]:<6} {int(c[5]) / 1000:>7.2f} ms  {c[6] if c[6] != '-' else ''}")

    def colour(ln):
        if ln.startswith("$"):
            return MUTED
        return RED if " error " in ln else FG
    terminal(lines, "guardrail-redos-rust-compile.webp", title="Rust regex 1.13: compiling each rule (default 10 MiB size limit)",
             colour=colour, size=17, width=1500)


# ------------------------------------------------------------ growth chart (log y)
def growth_chart():
    rule = "secret_assign"
    W, H = 1500, 860
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((60, 36), "secret_assign, naive rule: time for one attack string  token=\"aaaa…a", font=font(F_BOLD, 34), fill=FG)
    d.text((60, 86), "median per engine, log scale; a line stops when one string takes more than 1 s", font=font(F_REG, 24), fill=MUTED)
    x0, x1, y0, y1 = 150, W - 330, 150, H - 110
    lo, hi = -4, 4  # 10^-4 ms .. 10^4 ms
    for e in range(lo, hi + 1):
        y = y1 - (y1 - y0) * (e - lo) / (hi - lo)
        d.line((x0, y, x1, y), fill=GRID, width=1)
        lab = fmt_ms(10 ** e)
        d.text((x0 - 14 - d.textlength(lab, font=font(F_REG, 19)), y - 11), lab, font=font(F_REG, 19), fill=MUTED)
    ns = [8, 12, 16, 18, 20, 22, 24, 26, 28, 30, 32, 64, 256, 1024, 4096, 16384, 65536, 262144]
    xs = {n: x0 + (x1 - x0) * i / (len(ns) - 1) for i, n in enumerate(ns)}
    for n in ns:
        lab = f"{n:,}" if n < 1000 else f"{n // 1024}k"
        if n in (8, 16, 20, 24, 28, 32, 64, 256, 1024, 4096, 16384, 65536, 262144):
            d.text((xs[n] - d.textlength(lab, font=font(F_REG, 18)) / 2, y1 + 12), lab, font=font(F_REG, 18), fill=MUTED)
    d.text(((x0 + x1) / 2 - 170, y1 + 44), "attacker-supplied characters after token=\"", font=font(F_REG, 21), fill=MUTED)

    def ypos(ms):
        v = max(lo, min(hi, math.log10(max(ms, 1e-9))))
        return y1 - (y1 - y0) * (v - lo) / (hi - lo)
    ly = y0
    for eng in ENGINES:
        pts = []
        for n in ns:
            c = cell("attack", eng, rule, "naive", n)
            if c:
                pts.append((xs[n], ypos(c["ms"]), c))
        if len(pts) > 1:
            d.line([(x, y) for x, y, _ in pts], fill=COL[eng], width=4)
        for x, y, _ in pts:
            d.ellipse((x - 5, y - 5, x + 5, y + 5), fill=COL[eng])
        last = pts[-1][2]
        d.rectangle((x1 + 30, ly + 6, x1 + 50, ly + 26), fill=COL[eng])
        d.text((x1 + 60, ly), SHORT[eng], font=font(F_BOLD, 22), fill=FG)
        d.text((x1 + 60, ly + 28), f'{last["n"]:,} chars: {fmt_ms(last["ms"], last["capped"])}', font=font(F_REG, 19), fill=MUTED)
        ly += 74
    d.text((60, H - 46), host_line(), font=font(F_REG, 19), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "guardrail-redos-attack-growth.webp"))


# ------------------------------------------------------------ natural-line table
def natural_table():
    rules = ["role_override", "secret_assign", "exfil_url", "md_image", "pii_redact"]
    W = 1500
    row_h = 64
    H = 200 + row_h * len(rules) * 2 + 110
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((40, 30), "Longest ordinary line each engine finished (one line, words added one at a time)", font=font(F_BOLD, 30), fill=FG)
    d.text((40, 76), "red = the step that took more than 1 s (or hit the 120 s kill); no crafted padding, just the sample sentence",
           font=font(F_REG, 21), fill=MUTED)
    cx = [40, 290, 420]
    colw = (W - 440) / len(ENGINES)
    y = 130
    d.text((cx[0], y), "rule", font=font(F_BOLD, 22), fill=MUTED)
    d.text((cx[1], y), "variant", font=font(F_BOLD, 22), fill=MUTED)
    for i, e in enumerate(ENGINES):
        d.text((cx[2] + i * colw, y), SHORT[e], font=font(F_BOLD, 22), fill=COL[e])
    y += 44
    worst = {(w["engine"], w["rule"], w["variant"]): w for w in D["natural_worst"]}
    for r in rules:
        for v in ("naive", "hardened"):
            d.line((40, y - 8, W - 40, y - 8), fill=GRID, width=1)
            d.text((cx[0], y + 8), r, font=font(F_MONO, 21), fill=FG)
            d.text((cx[1], y + 8), v, font=font(F_REG, 21), fill=FG if v == "naive" else GREEN)
            for i, e in enumerate(ENGINES):
                w = worst.get((e, r, v))
                if not w:
                    continue
                bad = w["capped"] or w["ms"] > D["budget_ms"]
                txt = fmt_ms(w["ms"], w["capped"])
                d.text((cx[2] + i * colw, y), txt, font=font(F_BOLD, 22), fill=RED if bad else FG)
                d.text((cx[2] + i * colw, y + 28), f'{w["bytes"]} bytes', font=font(F_REG, 17), fill=MUTED)
            y += row_h
    d.text((40, H - 50), host_line() + "; median of 3 runs", font=font(F_REG, 19), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "guardrail-redos-natural-lines.webp"))


# ------------------------------------------------------------ load test chart
def load_chart():
    W, H = 1500, 900
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    m = D["load_meta"]
    d.text((40, 30), f'Guard service under load: {m["rps"]} benign req/s for {m["secs"]} s, plus one 37-byte line every {m["poison_every"]}',
           font=font(F_BOLD, 30), fill=FG)
    d.text((40, 76), "share of benign requests that failed (reset, refused or 5 s timeout), and p99 latency of the ones that succeeded",
           font=font(F_REG, 21), fill=MUTED)
    L = {(x["engine"], x["variant"]): x for x in D["load"]}
    y = 140
    bx0, bx1 = 560, 960
    px0, px1 = 1020, W - 60
    d.text((bx0, y), "benign requests failed", font=font(F_BOLD, 22), fill=MUTED)
    d.text((px0, y), "p99 of successful requests (log)", font=font(F_BOLD, 22), fill=MUTED)
    y += 46
    lo, hi = -1, 4  # 0.1 ms .. 10 s

    def px(ms):
        v = max(lo, min(hi, math.log10(max(ms, 1e-9))))
        return px0 + (px1 - px0) * (v - lo) / (hi - lo)
    for e in ENGINES:
        for v in ("naive", "hardened"):
            x = L.get((e, v))
            if not x:
                continue
            d.text((40, y + 6), f"{LABEL[e]}", font=font(F_BOLD, 21), fill=COL[e])
            d.text((420, y + 6), v, font=font(F_REG, 21), fill=FG if v == "naive" else GREEN)
            f = x["benign_failed_pct"]
            bw = (bx1 - bx0) * f / 100
            d.rectangle((bx0, y + 4, bx1, y + 34), outline=GRID, width=1)
            if bw > 0:
                d.rectangle((bx0, y + 4, bx0 + max(3, bw), y + 34), fill=RED)
            d.text((bx1 - 90 if f > 80 else bx0 + bw + 10, y + 7), f"{f:.1f}%", font=font(F_BOLD, 21), fill=FG)
            p = x["ok_p99_ms"]
            if p is not None:
                d.rectangle((px0, y + 4, px(p), y + 34), fill=RED if p > 100 else GREEN)
                d.text((min(px(p) + 10, px1 - 110), y + 7), fmt_ms(p), font=font(F_BOLD, 21), fill=FG)
            y += 58
        y += 8
    for e in range(lo, hi + 1):
        xx = px0 + (px1 - px0) * (e - lo) / (hi - lo)
        lab = fmt_ms(10 ** e)
        d.text((xx - d.textlength(lab, font=font(F_REG, 16)) / 2, y), lab, font=font(F_REG, 16), fill=MUTED)
    reps = D["load"][0]["reps"]
    d.text((40, H - 46), host_line() + f"; {reps} runs pooled, open-loop Go client, latency from scheduled send time",
           font=font(F_REG, 19), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "guardrail-redos-load-test.webp"))


# ------------------------------------------------------------ header (40:21)
def header():
    W, H = 1600, 840  # 40:21, the theme's .preview-img aspect ratio, so nothing is cropped
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 40):
        d.line((x, 0, x, H), fill=(20, 25, 32), width=1)
    for y in range(0, H, 40):
        d.line((0, y, W, y), fill=(20, 25, 32), width=1)
    line = natural_text("secret_assign", 4)
    d.text((80, 64), '(api[_-]?key|token|secret|password)\\s*[:=]\\s*"([\\w-]+)+"', font=font(F_MONO, 28), fill=RUST)
    d.text((80, 112), "ReDoS in AI guardrails, measured:", font=font(F_BOLD, 66), fill=FG)
    d.text((80, 192), "one ordinary line, five regex engines", font=font(F_BOLD, 66), fill=FG)
    d.text((80, 292), f"input: {line}   ({len(line)} bytes)", font=font(F_MONO, 26), fill=MUTED)
    bars = []
    for e in ENGINES:
        c = cell("natural", e, "secret_assign", "naive", 4)
        bars.append((LABEL[e], c["ms"], c["capped"], COL[e]))
    lo, hi = -4, 4
    y = 350
    for label, ms, capped, col in bars:
        d.text((80, y + 8), label, font=font(F_REG, 28), fill=FG)
        v = max(lo, min(hi, math.log10(max(ms, 1e-9))))
        bw = max(8, 640 * (v - lo) / (hi - lo))
        d.rounded_rectangle((560, y, 560 + bw, y + 46), radius=6, fill=col)
        d.text((560 + bw + 16, y + 8), fmt_ms(ms, capped), font=font(F_BOLD, 30), fill=RED if ms > 100 else GREEN)
        y += 66
    d.text((80, y + 22), "log scale; same rule, same 37 bytes; the hardened rewrite is under 10 µs everywhere",
           font=font(F_BOLD, 30), fill=GREEN)
    d.text((80, y + 72), host_line() + ", median of 3 runs", font=font(F_REG, 24), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, "ai-security-guardrail-redos.webp"), quality=90)


if __name__ == "__main__":
    os.makedirs(OUT_POSTS, exist_ok=True)
    os.makedirs(OUT_HEADER, exist_ok=True)
    curl_panel()
    compile_panel()
    growth_chart()
    natural_table()
    load_chart()
    header()
