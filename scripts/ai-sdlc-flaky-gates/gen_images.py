#!/usr/bin/env python3
"""Build the webp images for the "flaky agent PRs vs re-run failed jobs" post.

Usage:
  python3 scripts/ai-sdlc-flaky-gates/gen_images.py

Everything is drawn from scripts/data/ai-sdlc-flaky-gates-go.json (written by
summarise.py); the terminal panel copies lines from the failing-run samples
recorded there. Nothing is typed in by hand except titles and axis labels.
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

DATA = os.environ.get("FLAKY_DATA", "scripts/data/ai-sdlc-flaky-gates-go.json")
OUT_POSTS = "assets/img/posts/ai"
OUT_HEADER = "assets/img/headers/ai"
SLUG = "ai-sdlc-flaky-agent-prs-ci-retries"

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
YELLOW = (210, 168, 70)

D = json.load(open(DATA))
CASES = D["cases"]
BY = {c["id"]: c for c in CASES}
POL = {p["id"]: p for p in D["policies"]}
MODE_LABEL = {
    "plain": "go test", "shuffle": "-shuffle", "race": "-race",
    "race_shuffle": "-race -shuffle", "stress10": "-race -shuffle -count=10",
    "loaded": "-race -shuffle 12 at once",
}
KIND_COL = {"control": GREEN, "correct": GREEN, "test-flake": YELLOW, "defect": RED}


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


def host_line():
    return (f'{D["host"]["cpu"]}, {D["go"].replace("go version ", "")}, '
            f'{D["total_runs"]:,} test-binary runs, host load median {D["host"]["load1_median"]:.0f}')


def pct(x):
    return f"{100 * x:.0f}%" if x >= 0.01 or x == 0 else f"{100 * x:.1f}%"


def fit(d, text, f, width):
    if d.textlength(text, font=f) <= width:
        return text
    while d.textlength(text + "…", font=f) > width:
        text = text[:-1]
    return text.rstrip() + "…"


# ------------------------------------------------------------ header (40:21)
def header():
    W, H = 1600, 840
    img, d = frame(W, H)
    d.text((70, 66), "AI SDLC  |  Go  |  CI policy  |  measured", font=font(F_BOLD, 30), fill=BLUE)
    d.text((70, 116), "\u201cRe-run failed jobs\u201d is a merge", font=font(F_BOLD, 72), fill=FG)
    d.text((70, 198), "button for flaky agent bugs", font=font(F_BOLD, 72), fill=FG)
    p1, p3, st10 = POL["plain1"], POL["plain3"], POL["stress"]
    tm = D["timing"]
    stats = [
        (pct(p1["defect_merge_mean"]), "of defective PRs merge\non one plain go test", ORANGE),
        (pct(p3["defect_merge_mean"]), "merge once CI re-runs\nred jobs up to 3 times", RED),
        (pct(st10["defect_merge_mean"]), "merge on -race -shuffle\n-count=10, one run", GREEN),
        (f'{1000 * tm["stress10_nosleep"]["green_median_s"]:.0f} ms', "that run, with\nGORACE=atexit_sleep_ms=0", BLUE),
    ]
    x = 70
    for big, small, col in stats:
        d.rounded_rectangle((x, 330, x + 340, 560), radius=14, fill=BG, outline=BORDER, width=2)
        d.text((x + 28, 350), big, font=font(F_BOLD, 76), fill=col)
        for k, ln in enumerate(small.split("\n")):
            d.text((x + 28, 456 + k * 32), ln, font=font(F_REG, 25), fill=MUTED)
        x += 368
    # retry curve sparkline per defect
    d.text((70, 604), "Chance a defective PR merges if CI retries a red go test up to k times (k = 1..5):",
           font=font(F_REG, 25), fill=MUTED)
    curve = D["retry_curve_plain"]
    x = 70
    for cid, ys in curve.items():
        if BY[cid]["kind"] != "defect":
            continue
        w, h, y0 = 330, 110, 650
        d.rounded_rectangle((x, y0, x + w, y0 + h), radius=10, fill=BG, outline=BORDER, width=1)
        # text strip on top, plot below it, so the 100% point never sits under a label
        pts = [(x + 24 + i * (w - 48) / 4, y0 + h - 12 - (h - 58) * v) for i, v in enumerate(ys)]
        d.line((x + 16, y0 + 42, x + w - 16, y0 + 42), fill=GRID, width=1)
        d.line(pts, fill=RED, width=4)
        for p in pts:
            d.ellipse((p[0] - 5, p[1] - 5, p[0] + 5, p[1] + 5), fill=RED)
        d.text((x + 16, y0 + 8), cid, font=font(F_BOLD, 24), fill=FG)
        lbl = f"k=1 {pct(ys[0])}  \u2192  k=5 {pct(ys[-1])}"
        d.text((x + w - 16 - d.textlength(lbl, font=font(F_BOLD, 20)), y0 + 11), lbl, font=font(F_BOLD, 20), fill=RED)
        x += w + 38
    d.text((70, H - 58), "4 seeded agent defects, 2 nondeterministic tests, 2 correct changes on one Go service.  "
                         + host_line(), font=font(F_REG, 19), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, SLUG + ".webp"))


# ------------------------------------------------------------ case x mode fail-rate matrix
def matrix():
    modes = list(D["modes"]) + (["loaded"] if D.get("contention") else [])
    cw, rh = 190, 64
    left, top = 640, 210
    W = left + cw * len(modes) + 40
    H = top + rh * len(CASES) + 120
    img, d = frame(W, H)
    d.text((40, 30), "How often each PR's test run goes red, per go test mode", font=font(F_BOLD, 30), fill=FG)
    d.text((40, 76), host_line() + ".", font=font(F_REG, 20), fill=MUTED)
    d.text((40, 104), "Cell: failing runs / runs. Darker red = fails more often. A defect row with a 0 cell "
                      "is a defect that mode cannot see.", font=font(F_REG, 20), fill=MUTED)
    for j, m in enumerate(modes):
        x = left + j * cw + cw / 2
        lines = MODE_LABEL[m].split(" ") if len(MODE_LABEL[m]) > 14 else [MODE_LABEL[m]]
        if len(lines) > 2:
            lines = [" ".join(lines[:2]), " ".join(lines[2:])]
        for k, ln in enumerate(lines):
            tw = d.textlength(ln, font=font(F_BOLD, 19))
            d.text((x - tw / 2, 146 + k * 24), ln, font=font(F_BOLD, 19), fill=BLUE)
    prev = None
    for i, c in enumerate(CASES):
        y = top + i * rh
        if c["kind"] != prev:
            d.line((40, y - 2, W - 40, y - 2), fill=BORDER, width=1)
            prev = c["kind"]
        d.text((40, y + 8), c["id"], font=font(F_MONO, 21), fill=KIND_COL[c["kind"]])
        d.text((118, y + 8), fit(d, c["title"], font(F_REG, 19), left - 140), font=font(F_REG, 19), fill=FG)
        d.text((118, y + 34), c["kind"] + (f' (= {c["src"]} in the gates post)' if c.get("src") else ""),
               font=font(F_REG, 16), fill=MUTED)
        for j, m in enumerate(modes):
            s = D["contention"]["cases"][c["id"]] if m == "loaded" else c["modes"][m]
            x0 = left + j * cw + 8
            r = s["rate"]
            if s["fail"]:
                a = 0.25 + 0.75 * r
                col = tuple(int(PANEL[k] + (RED[k] - PANEL[k]) * a) for k in range(3))
                d.rounded_rectangle((x0, y + 4, x0 + cw - 16, y + rh - 6), radius=6, fill=col)
            txt = f'{s["fail"]}/{s["n"]}'
            sub = pct(r)
            tw = d.textlength(txt, font=font(F_BOLD, 20))
            d.text((x0 + (cw - 16) / 2 - tw / 2, y + 8), txt, font=font(F_BOLD, 20), fill=FG if s["fail"] else GRID)
            tw = d.textlength(sub, font=font(F_REG, 16))
            d.text((x0 + (cw - 16) / 2 - tw / 2, y + 34), sub, font=font(F_REG, 16), fill=FG if s["fail"] else GRID)
    y = top + rh * len(CASES) + 24
    d.text((40, y), "-count=10 runs every test ten times inside one binary run; its rows count binary runs, "
                    "not test executions.", font=font(F_REG, 19), fill=MUTED)
    d.text((40, y + 30), "Shuffle seeds are recorded, so every red run can be replayed with -test.shuffle=<seed>. "
                         f'Last column: {D["contention"]["parallel"]} race binaries started at once, '
                         f'{D["contention"]["rounds"]} rounds.', font=font(F_REG, 19), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, SLUG + "-matrix.webp"))


# ------------------------------------------------------------ CI policies: what merges, what it costs
def policies():
    pols = D["policies"]
    W, H = 1500, 140 + 70 * len(pols) + 150
    img, d = frame(W, H)
    d.text((40, 30), f"{len(pols)} CI policies replayed on the recorded runs", font=font(F_BOLD, 30), fill=FG)
    d.text((40, 74), "Defects merged and nondeterministic tests let through (mean over cases, lower is better); "
                     "correct PRs blocked; seconds per green run.", font=font(F_REG, 19), fill=MUTED)
    x0, x1 = 560, 1020
    top = 150
    d.text((x0, top - 40), "defects merged", font=font(F_BOLD, 18), fill=RED)
    d.text((x0 + 200, top - 40), "flaky tests let through", font=font(F_BOLD, 18), fill=YELLOW)
    d.text((1060, top - 40), "correct blocked", font=font(F_BOLD, 18), fill=FG)
    d.text((1260, top - 40), "s / green run", font=font(F_BOLD, 18), fill=FG)
    tmax = max(p["median_s_correct"] for p in pols)
    for i, p in enumerate(pols):
        y = top + i * 70
        d.line((40, y - 6, W - 40, y - 6), fill=GRID, width=1)
        d.text((40, y + 10), fit(d, p["label"], font(F_BOLD, 19), x0 - 60), font=font(F_BOLD, 19), fill=FG)
        for k, (v, col) in enumerate(((p["defect_merge_mean"], RED), (p["test_flake_merge_mean"], YELLOW))):
            yy = y + 6 + k * 26
            d.rectangle((x0, yy, x0 + (x1 - x0 - 60) * v, yy + 20), fill=col)
            d.text((x0 + (x1 - x0 - 60) * v + 8, yy - 1), pct(v), font=font(F_REG, 18), fill=FG)
        cb = p["correct_block_mean"]
        d.text((1060, y + 14), pct(cb), font=font(F_BOLD, 22), fill=GREEN if cb == 0 else RED)
        bw = 140 * p["median_s_correct"] / tmax
        d.rectangle((1260, y + 18, 1260 + max(bw, 2), y + 36), fill=MUTED)
        d.text((1260 + max(bw, 2) + 8, y + 14), f'{p["median_s_correct"]:.2f}', font=font(F_REG, 18), fill=FG)
    y = top + 70 * len(pols) + 20
    d.text((40, y), "A retry policy takes consecutive groups of k recorded runs: the PR merges if any run in its group "
                    "is green (\"every run\" policies need all k). No independence model.", font=font(F_REG, 18), fill=MUTED)
    d.text((40, y + 28), "Defects F1-F4, nondeterministic tests T1-T2, correct BASE, C1, C2. Race-mode seconds include "
                         "the race runtime's default 1 s exit sleep.", font=font(F_REG, 18), fill=MUTED)
    d.text((40, y + 56), host_line() + ".", font=font(F_REG, 18), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, SLUG + "-policies.webp"))


# ------------------------------------------------------------ where the race second goes
def timing():
    tm = D["timing"]
    rows = [("plain", "go test (no race detector)", MUTED),
            ("race", "go test -race (default GORACE)", ORANGE),
            ("race_nosleep", "go test -race, GORACE=atexit_sleep_ms=0", GREEN),
            ("stress10_nosleep", "-race -shuffle -count=10, atexit_sleep_ms=0", BLUE)]
    W, H = 1500, 520
    img, d = frame(W, H)
    d.text((40, 30), "The race detector's second is a sleep at exit, not detection", font=font(F_BOLD, 30), fill=FG)
    d.text((40, 76), f'Median wall time of a green test-binary run, all 9 cases, {tm["reps"]} interleaved runs per '
                     f'case and variant. {D["host"]["cpu"]}, {D["go"].replace("go version ", "")}.',
           font=font(F_REG, 19), fill=MUTED)
    vmax = max(tm[k]["green_median_s"] for k, _, _ in rows)
    x0, bw = 620, 700
    for i, (k, label, col) in enumerate(rows):
        y = 140 + i * 72
        d.text((40, y + 8), label, font=font(F_BOLD, 21), fill=FG)
        v = tm[k]["green_median_s"]
        d.rectangle((x0, y, x0 + max(bw * v / vmax, 3), y + 40), fill=col)
        lbl = f"{v * 1000:.0f} ms" if v < 1 else f"{v:.2f} s"
        d.text((x0 + max(bw * v / vmax, 3) + 12, y + 8), lbl, font=font(F_BOLD, 22), fill=FG)
    fb = tm["fails_by_case"]
    y = 140 + len(rows) * 72 + 16
    d.text((40, y), "Red runs per case with and without the sleep (same seeds): "
           + ", ".join(f'{c} {fb[c]["race"]} vs {fb[c]["race_nosleep"]}' for c in fb if fb[c]["race"] or fb[c]["race_nosleep"]),
           font=font(F_REG, 19), fill=MUTED)
    d.text((40, y + 30), "The race runtime waits atexit_sleep_ms (default 1000) before a clean exit so late reports can "
                         "print; reports during a test fail that test either way.", font=font(F_REG, 19), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, SLUG + "-race-timing.webp"))


# ------------------------------------------------------------ terminal panel of real failures
def terminal():
    S = D["samples"]
    picks = [("T1.shuffle", ["--- FAIL", "handler_test.go"]),
             ("F2.race", ["ledger_test.go", "--- FAIL", "WARNING: DATA RACE", "Read at", "Previous write at", "ledger.go:65"]),
             ("F1.plain", ["--- FAIL", "ledger_test.go"]),
             ("F4.race_shuffle", ["--- FAIL", "ledger_test.go"]),
             ("T2.loaded", ["--- FAIL", "upstream_test.go"])]
    lines = []
    for key, keep in picks:
        if key not in S:
            continue
        body = S[key].splitlines()
        lines.append((f"$ {body[0]}", BLUE))
        seen = 0
        for ln in body[1:]:
            if seen >= 7:
                break
            if any(k in ln for k in keep) and "PASS" not in ln:
                if "testing.go" in ln or "created at" in ln:
                    continue
                txt = ln.rstrip().replace("\t", "    ")
                if "/trees/" in txt:
                    txt = "    " + txt.split("/trees/")[1].split("/", 1)[1]
                if len(txt) > 118:
                    txt = txt[:117] + "…"
                col = RED if ("FAIL" in ln or "DATA RACE" in ln) else FG
                lines.append((txt, col))
                seen += 1
        lines.append(("", FG))
    size, lh = 17, 26
    W, H = 1500, 80 + lh * len(lines) + 20
    img, d = frame(W, H)
    for i, c in enumerate((RED, ORANGE, GREEN)):
        d.ellipse((34 + i * 26, 30, 48 + i * 26, 44), fill=c)
    title = "first red run of five cases, copied from the recorded test output (paths shortened)"
    tw = d.textlength(title, font=font(F_REG, 18))
    d.text((W / 2 - tw / 2, 26), title, font=font(F_REG, 18), fill=MUTED)
    y = 72
    for ln, col in lines:
        d.text((36, y), ln, font=font(F_MONO, size), fill=col)
        y += lh
    save(img, os.path.join(OUT_POSTS, SLUG + "-terminal.webp"))


if __name__ == "__main__":
    os.makedirs(OUT_POSTS, exist_ok=True)
    os.makedirs(OUT_HEADER, exist_ok=True)
    header()
    matrix()
    policies()
    terminal()
    timing()
