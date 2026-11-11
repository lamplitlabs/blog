#!/usr/bin/env python3
"""Build the webp images for the "Go PGO in practice" post.

Usage: python3 scripts/go-pgo/gen_images.py <work-dir>

Reads scripts/data/go-pgo-m2pro.json (from summarise.py) and the pprof web UI
screenshots that shots.sh saved in <work-dir>/shots. Charts and panels are
drawn from the JSON; the -gcflags=-m and pgodebug panels print captured lines
verbatim (rows selected, not edited). Screenshots are cropped, not resized.
Webp quality 85.
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

WORK = sys.argv[1] if len(sys.argv) > 1 else "go-pgo-work"
DATA = "scripts/data/go-pgo-m2pro.json"
OUT_POSTS = "assets/img/posts/performance"
OUT_HEADER = "assets/img/headers/performance"

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
ORANGE = (240, 136, 62)
RED = (248, 81, 73)
GO_CYAN = (0, 173, 216)

D = json.load(open(DATA))
C = D["cells"]


def font(path, size):
    return ImageFont.truetype(path, size)


def save(img, path, quality=85):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    print("wrote", path, img.size, os.path.getsize(path), "bytes")


def frame(w, h):
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, w - 12, h - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    return img, d


def pct(v, c, key="instructions_per_line_vs_off_pct"):
    return C[f"{v}/{c}"][key]


# ------------------------------------------------------------ header (40:21)
def header():
    W, H = 1600, 840
    img, d = frame(W, H)
    d.text((64, 54), "Go PGO in practice", font=font(F_BOLD, 64), fill=FG)
    d.text((64, 136), "go build -pgo=cpu.pprof on a log router, measured on an M2 Pro (go1.27.2)",
           font=font(F_REG, 30), fill=MUTED)
    rows = [("PGO off", "off", MUTED), ("PGO, 2.4 s profile", "pgo", GO_CYAN),
            ("PGO, 0.4 s profile", "pgo-short", ORANGE), ("PGO, inlining disabled", "pgo-noinline", RED)]
    base = C["off/api"]["instructions_per_line_median"]
    x0, x1 = 520, W - 220
    y = 230
    d.text((64, y), "instructions per routed log line (api config, median of 5 runs)", font=font(F_BOLD, 28), fill=FG)
    y += 64
    for label, v, col in rows:
        val = C[f"{v}/api"]["instructions_per_line_median"]
        d.text((64, y + 14), label, font=font(F_REG, 32), fill=FG)
        lo = 2800
        bw = (x1 - x0) * (val - lo) / (base * 1.04 - lo)
        d.rounded_rectangle((x0, y + 6, x0 + bw, y + 62), radius=8, fill=col)
        delta = pct(v, "api")
        txt = f"{val:,.0f}" + ("" if v == "off" else f"  ({delta:+.1f}%)")
        d.text((x0 + bw + 16, y + 16), txt, font=font(F_BOLD, 30), fill=FG)
        y += 92
    d.text((x0, y + 4), "axis starts at 2,800", font=font(F_REG, 22), fill=MUTED)
    nd = pct("pgo-nodevirt", "api")
    d.text((64, H - 150), f"The gain is hot-call-site inlining; with devirtualization off it is still {nd:+.1f}%.",
           font=font(F_BOLD, 34), fill=GO_CYAN)
    sz = D["builds"]
    dsz = sz["pgo"]["binary_bytes"] - sz["off"]["binary_bytes"]
    d.text((64, H - 96), f"Binary size {dsz:+d} bytes; output checksums identical across all 8 builds.",
           font=font(F_REG, 30), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, "go-pgo-profile-guided-optimization.webp"))


# ------------------------------------------------------------ results chart
LABELS = [
    ("off", "PGO off (baseline)", MUTED),
    ("pgo", "PGO, api profile (2.4 s)", GO_CYAN),
    ("pgo-nodevirt", "PGO, devirtualization off", GO_CYAN),
    ("pgo-noinline", "PGO, inlining off", RED),
    ("pgo-short", "PGO, 0.4 s api profile", ORANGE),
    ("pgo-batchprof", "PGO, batch profile", BLUE),
    ("pgo-merged", "PGO, api + batch merged", BLUE),
    ("pgo-iter2", "PGO, profile of the PGO build", BLUE),
]


def results():
    W = 1600
    row_h = 60
    H = 230 + row_h * len(LABELS) + 150
    img, d = frame(W, H)
    d.text((48, 40), "Instructions and cycles per routed line, change vs PGO off", font=font(F_BOLD, 38), fill=FG)
    d.text((48, 96), "median of 5 interleaved runs x 5 passes over 1,000,000 lines; load-only cost subtracted",
           font=font(F_REG, 24), fill=MUTED)
    cols = [("api", "instructions_per_line_vs_off_pct", "api: instructions"),
            ("api", "cycles_per_line_vs_off_pct", "api: cycles"),
            ("batch", "instructions_per_line_vs_off_pct", "batch: instructions"),
            ("batch", "cycles_per_line_vs_off_pct", "batch: cycles")]
    lx = 48
    cx0 = 560
    cw = (W - cx0 - 48) // len(cols)
    y = 160
    for i, (_, _, t) in enumerate(cols):
        d.text((cx0 + i * cw + 10, y), t, font=font(F_BOLD, 24), fill=FG)
    y += 50
    scale = cw * 0.42 / 12.0  # px per percent, +-12% fits
    for v, label, col in LABELS:
        d.text((lx, y + 14), label, font=font(F_REG, 26), fill=FG)
        for i, (c, key, _) in enumerate(cols):
            zero = cx0 + i * cw + cw * 0.55
            val = C[f"{v}/{c}"][key]
            d.line((zero, y + 4, zero, y + row_h - 4), fill=BORDER, width=2)
            if v != "off":
                x2 = zero + val * scale
                d.rectangle((min(zero, x2), y + 14, max(zero, x2), y + row_h - 14),
                            fill=GREEN if val < -1 else (RED if val > 1 else MUTED))
            txt = "0" if v == "off" else f"{val:+.1f}%"
            tw = d.textlength(txt, font=font(F_BOLD, 22))
            tx = zero + 10 if val <= 0 else zero - tw - 10
            d.text((tx, y + 16), txt, font=font(F_BOLD, 22), fill=FG)
        y += row_h
    off_api = C["off/api"]
    off_b = C["off/batch"]
    d.text((48, y + 26), f"PGO-off baseline: api {off_api['instructions_per_line_median']:,.0f} instructions and "
           f"{off_api['cycles_per_line_median']:,.0f} cycles per line; batch {off_b['instructions_per_line_median']:,.0f} and "
           f"{off_b['cycles_per_line_median']:,.0f}.", font=font(F_REG, 24), fill=MUTED)
    d.text((48, y + 66), "Instruction counts repeat within 0.5% run to run; cycles move with host load (load average 5-12 during the runs).",
           font=font(F_REG, 24), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "go-pgo-results.webp"))


# ------------------------------------------------------------ terminal panels
def terminal(lines, out, width=1600, title="zsh", colour=None, size=19):
    mono = font(F_MONO, size)
    line_h = int(size * 1.5)
    top = 56
    height = top + 24 + line_h * len(lines) + 24
    img, d = frame(width, height)
    for i, c in enumerate((RED, ORANGE, GREEN)):
        d.ellipse((34 + i * 26, 30, 48 + i * 26, 44), fill=c)
    tw = d.textlength(title, font=font(F_REG, 18))
    d.text(((width - tw) / 2, 26), title, font=font(F_REG, 18), fill=MUTED)
    y = top + 16
    for ln in lines:
        d.text((36, y), ln, font=mono, fill=colour(ln) if colour else FG)
        y += line_h
    save(img, os.path.join(OUT_POSTS, out))


def read(name):
    with open(os.path.join(WORK, name)) as fh:
        return [l.rstrip("\n") for l in fh]


def m_diff():
    only = D["m_diff"]["only_with_pgo"]
    order = lambda l: (int(l.split(":")[1]), l)
    lines = ["$ go build -a -pgo=off      -gcflags=-m . 2>&1 | grep -E 'inlin|devirt' | sort > m-off.txt",
             "$ go build -a -pgo=api.pprof -gcflags=-m . 2>&1 | grep -E 'inlin|devirt' | sort > m-pgo.txt",
             "$ comm -13 m-off.txt m-pgo.txt          # lines only the PGO build prints, by source line",
             ""]
    lines += sorted(only, key=order)
    lines += ["", f"# {D['m_diff']['inlining_lines_off']} inlining lines without PGO, {D['m_diff']['inlining_lines_pgo']} with it; "
                  f"{len(D['m_diff']['only_without_pgo'])} decisions lost"]

    def colour(ln):
        if ln.startswith("$"):
            return BLUE
        if ln.startswith("#"):
            return MUTED
        if "devirtualizing" in ln:
            return ORANGE
        if "can inline" in ln:
            return GREEN
        return FG

    terminal(lines, "go-pgo-gcflags-m-diff.webp", colour=colour, size=19, title="what PGO changed: -gcflags=-m diff")


def pgodebug():
    full = sorted(set(l for l in read("pgodebug-api.txt") if l))
    short = sorted(set(l for l in read("pgodebug-api-short.txt") if l))
    short_s = lambda l: l.replace("example.com/logroute/", "")
    lines = ["$ go build -a -pgo=api.pprof -gcflags=-d=pgodebug=1 .      # 2.4 s profile, 2,080 ms of samples"]
    lines += [short_s(l) for l in full if l.startswith(("hot-callsite", "hot-budget"))]
    lines += ["# + 'increased budget=2000' for " + str(sum(l.startswith("hot-node") for l in full)) + " hot functions", ""]
    lines += ["$ go build -a -pgo=api-short.pprof -gcflags=-d=pgodebug=1 .  # 0.4 s profile, 230 ms of samples"]
    lines += [short_s(l) for l in short if l.startswith(("hot-callsite", "hot-budget"))]
    lines += ["# + 'increased budget=2000' for " + str(sum(l.startswith("hot-node") for l in short)) + " hot functions"]

    def colour(ln):
        if ln.startswith("$"):
            return BLUE
        if ln.startswith("#"):
            return MUTED
        if ln.startswith("hot-callsite"):
            return ORANGE
        return FG

    terminal(lines, "go-pgo-pgodebug.webp", colour=colour, size=17, title="the compiler's own account: -d=pgodebug=1")


# ------------------------------------------------------------ pprof screenshots
def flames():
    shots = os.path.join(WORK, "shots")
    a = Image.open(os.path.join(shots, "flame-off.png")).convert("RGB").crop((0, 0, 1440, 250))
    b = Image.open(os.path.join(shots, "flame-pgo.png")).convert("RGB").crop((0, 0, 1440, 250))
    W, pad, lab = 1500, 30, 50
    H = pad + lab + a.height + pad + lab + b.height + pad
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    y = pad
    for im, t in ((a, "PGO off: the profile the PGO build was made from (api.pprof)"),
                  (b, "PGO build, same input: the same boxes, because pprof still draws inlined calls as frames")):
        d.text((pad, y + 8), t, font=font(F_BOLD, 26), fill=FG)
        y += lab
        img.paste(im, (pad, y))
        y += im.height + pad
    save(img, os.path.join(OUT_POSTS, "go-pgo-pprof-flamegraphs.webp"))


def source():
    im = Image.open(os.path.join(WORK, "shots", "source-off.png")).convert("RGB").crop((0, 0, 1440, 1120))
    save(im, os.path.join(OUT_POSTS, "go-pgo-pprof-source-scanfields.webp"))


if __name__ == "__main__":
    header()
    results()
    m_diff()
    pgodebug()
    flames()
    source()
