#!/usr/bin/env python3
"""Build the webp images for the "tool-call argument parser differentials" post.

    python3 scripts/tool-args-differential/gen_images.py <work-dir>

<work-dir> is the output of bench.py followed by shots.sh. Charts read
scripts/data/tool-args-differential.json; the terminal panel prints the real
<work-dir>/bench.txt; the report image is the headless-Chromium screenshot
<work-dir>/shots/report.png, scaled, not redrawn. Nothing is typed in by hand.
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

WORK = sys.argv[1] if len(sys.argv) > 1 else "tool-args-work"
DATA = "scripts/data/tool-args-differential.json"
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
RUST = (222, 165, 132)

D = json.load(open(DATA))
EXEC_LABEL = {
    "typed": "struct\n(default)",
    "typed-deny": "struct +\ndeny_unknown",
    "alias": "struct +\n#[serde(alias)]",
    "value": "serde_json\n::Value",
    "typed-deny-checked": "deny_unknown +\ncanonicalize",
}


def font(path, size):
    return ImageFont.truetype(path, size)


def save(img, path, quality=88):
    img.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    print("wrote", path, img.size, os.path.getsize(path), "bytes")


def frame(W, H):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, W - 12, H - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    return img, d


def heat(v, worst):
    if v == 0:
        return (18, 54, 31)
    t = min(1.0, 0.35 + 0.65 * v / worst)
    return (int(60 + 158 * t), int(30 + 10 * (1 - t)), int(34 + 10 * (1 - t)))


def matrix(mode, out, title):
    gates = D["gates"]
    exs = D["executors"]
    L = D["leaks"][mode]
    worst = max(L[g][v] for g in gates for v in exs)
    W, H = 1500, 300 + 78 * len(gates)
    img, d = frame(W, H)
    d.text((40, 32), title, font=font(F_BOLD, 30), fill=FG)
    v = D["versions"]
    d.text((40, 76), "%d read_file argument strings, each run through 7 gates and 5 Rust executors that really open the file. "
           % D["payloads"], font=font(F_REG, 20), fill=MUTED)
    d.text((40, 102), "Cell = payloads the gate allowed and the executor answered with the canary. %s, %s, serde_json %s."
           % (D["host"], v["rustc"].split(" (")[0], v["serde_json"]), font=font(F_REG, 20), fill=MUTED)
    x0, cw, y0, rh = 380, 214, 150, 78
    for j, e in enumerate(exs):
        for k, part in enumerate(EXEC_LABEL[e].split("\n")):
            tw = d.textlength(part, font=font(F_BOLD, 20))
            d.text((x0 + j * cw + cw / 2 - tw / 2, y0 + 8 + k * 26), part, font=font(F_BOLD, 20), fill=RUST)
    y = y0 + 80
    for g in gates:
        d.text((40, y + 24), g, font=font(F_MONO, 21), fill=FG)
        for j, e in enumerate(exs):
            n = L[g][e]
            box = (x0 + j * cw + 6, y + 6, x0 + (j + 1) * cw - 6, y + rh - 6)
            d.rounded_rectangle(box, radius=8, fill=heat(n, worst))
            s = str(n)
            tw = d.textlength(s, font=font(F_BOLD, 30))
            d.text(((box[0] + box[2]) / 2 - tw / 2, y + 22), s, font=font(F_BOLD, 30), fill=FG if n else (86, 211, 100))
        y += rh
    note = ("fail-closed: a gate that finds no string path denies the call" if mode == "closed"
            else "fail-open: a gate denies only a path it found and disliked (no path seen -> allow)")
    d.text((40, y + 22), note, font=font(F_REG, 20), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, out))


def terminal():
    rows = open(os.path.join(WORK, "bench.txt")).read().rstrip("\n").splitlines()
    lines = ["$ python3 scripts/tool-args-differential/bench.py ~/tool-args-work"] + rows
    size, line_h = 19, 28
    W, H = 1500, 56 + 24 + line_h * len(lines) + 30
    img, d = frame(W, H)
    for i, c in enumerate((RED, ORANGE, GREEN)):
        d.ellipse((34 + i * 26, 30, 48 + i * 26, 44), fill=c)
    t = "bench.txt: canary reads per gate x executor"
    d.text((W / 2 - d.textlength(t, font=font(F_REG, 18)) / 2, 26), t, font=font(F_REG, 18), fill=MUTED)
    y = 72
    for ln in lines:
        col = BLUE if ln.startswith("$") else ORANGE if ln.startswith("==") else MUTED if "canonical" in ln else FG
        d.text((36, y), ln, font=font(F_MONO, size), fill=col)
        y += line_h
    save(img, os.path.join(OUT_POSTS, "tool-args-differential-terminal.webp"))


def report_shot():
    src = Image.open(os.path.join(WORK, "shots/report-full.png")).convert("RGB")
    # rows: header + benign + the first attack families; keep the page's own pixels
    crop = src.crop((0, 0, 1440, min(src.height, 1100)))
    save(crop, os.path.join(OUT_POSTS, "tool-args-differential-report.webp"), quality=90)


def cost_chart():
    P = D["parse_ns_median"]
    bars = [
        ("struct (default)", P["typed/with-reason"], GREEN),
        ("struct + #[serde(alias)]", P["alias/with-reason"], GREEN),
        ("struct + deny_unknown_fields", P["typed-deny/with-reason"], BLUE),
        ("serde_json::Value + .get(\"path\")", P["value/with-reason"], ORANGE),
        ("deny_unknown + re-serialise {\"path\"}", P["parse+reserialise/with-reason"], ORANGE),
    ]
    canon = P["canonicalize-check/plain"]
    W, H = 1500, 640
    img, d = frame(W, H)
    d.text((40, 32), "What each executor costs per call (ns, median of 5 x 1M calls)", font=font(F_BOLD, 30), fill=FG)
    d.text((40, 76), "Payload: {\"path\": <58-byte path>, \"reason\": <59-byte string>}. %s, %s, --release."
           % (D["host"], D["versions"]["rustc"].split(" (")[0]), font=font(F_REG, 20), fill=MUTED)
    x0, x1, y = 560, 1380, 140
    top = 250.0
    for i in range(6):
        v = top * i / 5
        x = x0 + (x1 - x0) * v / top
        d.line((x, y - 6, x, y + 5 * 70), fill=GRID, width=1)
        d.text((x - 12, y + 5 * 70 + 6), "%d" % v, font=font(F_REG, 17), fill=MUTED)
    for name, v, col in bars:
        d.text((40, y + 14), name, font=font(F_MONO, 20), fill=FG)
        d.rounded_rectangle((x0, y + 8, x0 + (x1 - x0) * v / top, y + 52), radius=6, fill=col)
        d.text((x0 + (x1 - x0) * v / top + 10, y + 16), "%.0f ns" % v, font=font(F_BOLD, 22), fill=FG)
        y += 70
    d.text((40, y + 50), "Off the chart: std::fs::canonicalize + starts_with(workspace) = %.1f us per call (two realpath walks on APFS)."
           % (canon / 1000), font=font(F_BOLD, 22), fill=RED)
    d.text((40, y + 86), "It was the only executor change that closed the symlink row; the serde variants differ by tens of ns.",
           font=font(F_REG, 20), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "tool-args-differential-cost.webp"))


def header():
    W, H = 1600, 840
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((80, 70), "AI SECURITY  /  RUST", font=font(F_BOLD, 30), fill=RUST)
    d.text((80, 120), "Your tool gate and your serde", font=font(F_BOLD, 66), fill=FG)
    d.text((80, 198), "executor read different JSON", font=font(F_BOLD, 66), fill=FG)
    d.text((80, 292), "%d read_file argument strings, 7 gates x 5 Rust executors, real canary reads" % D["payloads"],
           font=font(F_REG, 30), fill=MUTED)
    L = D["leaks"]["closed"]
    rows = [
        ("Go encoding/json gate -> serde struct", L["go encoding/json"]["typed"], RED),
        ("regex gate -> serde_json::Value", L["regex on raw text"]["value"], RED),
        ("JSON.parse / json.loads gate -> serde struct", L["node JSON.parse"]["typed"], ORANGE),
        ("any gate -> deny_unknown + canonicalize", L["python json.loads"]["typed-deny-checked"], GREEN),
    ]
    worst = max(r[1] for r in rows)
    y = 380
    for name, n, col in rows:
        d.text((80, y + 8), name, font=font(F_REG, 32), fill=FG)
        x0 = 900
        w = 0 if n == 0 else max(14, 330 * n / worst)
        if w:
            d.rounded_rectangle((x0, y, x0 + w, y + 52), radius=8, fill=col)
        d.text((x0 + w + 18, y + 6), "%d canary read%s" % (n, "" if n == 1 else "s"), font=font(F_BOLD, 32), fill=col)
        y += 92
    d.text((80, 760), "%s, %s, serde_json %s, go1.27.2, node 22. Fail-closed gates." %
           (D["host"], D["versions"]["rustc"].split(" (")[0], D["versions"]["serde_json"]), font=font(F_REG, 24), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, "ai-security-tool-args-parser-differential.webp"))


if __name__ == "__main__":
    os.makedirs(OUT_POSTS, exist_ok=True)
    matrix("closed", "tool-args-differential-matrix-closed.webp", "Canary reads: fail-closed gate (rows) x Rust executor (columns)")
    matrix("open", "tool-args-differential-matrix-open.webp", "Canary reads: fail-open gate (rows) x Rust executor (columns)")
    terminal()
    report_shot()
    cost_chart()
    header()
