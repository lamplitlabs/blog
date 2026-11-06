#!/usr/bin/env python3
"""Build the webp images for the "AI code review gates in CI, measured on Go" post.

Usage:
  python3 scripts/ai-review-gates/gen_images.py

Everything is drawn from scripts/data/ai-review-gates-go.json (written by
summarise.py) and, for the terminal panel, from the findings recorded in it.
Nothing is typed in by hand except titles and axis labels.
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

DATA = "scripts/data/ai-review-gates-go.json"
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
YELLOW = (210, 168, 70)

D = json.load(open(DATA))
GATES = D["gates"]
CASES = D["cases"]
T = D["totals"]
SHORT = {
    "build_vet": "go vet", "test": "go test", "race": "go test -race", "diff_coverage": "diff coverage",
    "analyzers": "x/tools analyzers", "policy": "policy P1-P4", "secrets": "gitleaks",
    "test_integrity": "test integrity", "expected_moved": "expected moved", "review_hints": "review hints",
}
CLS = {
    "silent-error": "silent error fallback", "boundary": "boundary / off-by-one", "weak-tests": "tests that prove nothing",
    "hallucinated-api": "hallucinated API / arg order", "duplicate-helper": "duplicated helper",
    "concurrency": "concurrency / resources", "security": "security", "benign": "correct change (benign)",
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


def host_line():
    return (f'{D["host"]["cpu"]}, {D["go"].replace("go version ", "")}, gitleaks {D["gitleaks"]}, '
            f'median of {D["reps"]} runs per gate')


# ------------------------------------------------------------ header (40:21)
def header():
    W, H = 1600, 840
    img, d = frame(W, H)
    d.text((70, 70), "AI SDLC  |  Go  |  measured", font=font(F_BOLD, 30), fill=BLUE)
    d.text((70, 120), "Which CI gates stop a bad", font=font(F_BOLD, 74), fill=FG)
    d.text((70, 205), "agent pull request?", font=font(F_BOLD, 74), fill=FG)
    nd = T["defects"]
    stats = [
        (f'{T["blocked"]}/{nd}', "seeded defects blocked", GREEN),
        (f'{len(T["not_blocked"])}/{nd}', "got past every blocking gate", RED),
        (f'{len(T["benign_blocked"])}/{T["benign"]}', "correct PRs blocked", ORANGE),
        (f'{T["pipeline_seconds_median"]:.1f} s', "all gates, median per PR", BLUE),
    ]
    x = 70
    for big, small, col in stats:
        d.rounded_rectangle((x, 340, x + 340, 540), radius=14, fill=BG, outline=BORDER, width=2)
        d.text((x + 28, 362), big, font=font(F_BOLD, 76), fill=col)
        d.text((x + 28, 470), small, font=font(F_REG, 25), fill=MUTED)
        x += 368
    # gate strip: one chip per gate, width ~ defects caught alone + total
    d.text((70, 590), "Gates in CI order (blocking, then advisory):", font=font(F_REG, 25), fill=MUTED)
    x, y = 70, 636
    for g in GATES:
        label = SHORT[g["id"]]
        w = d.textlength(label, font=font(F_BOLD, 24)) + 36
        if x + w > W - 70:
            x, y = 70, y + 62
        col = BLUE if g["kind"] == "block" else YELLOW
        d.rounded_rectangle((x, y, x + w, y + 48), radius=24, fill=BG, outline=col, width=2)
        d.text((x + 18, y + 10), label, font=font(F_BOLD, 24), fill=col)
        x += w + 14
    d.text((70, H - 62), f'{nd} seeded agent-style defects + {T["benign"]} correct changes on one Go service.  '
                         + host_line(), font=font(F_REG, 20), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, "ai-sdlc-ai-code-review-gates-ci-go-measured.webp"))


# ------------------------------------------------------------ case x gate matrix
def matrix():
    rows = CASES
    cw, rh = 96, 38
    left, top = 600, 244
    W = left + cw * len(GATES) + 160
    H = top + rh * len(rows) + 130
    img, d = frame(W, H)
    d.text((40, 30), f'Every seeded PR against every gate ({T["defects"]} defects, {T["benign"]} correct changes)',
           font=font(F_BOLD, 30), fill=FG)
    d.text((40, 76), host_line() + ".", font=font(F_REG, 21), fill=MUTED)
    d.text((40, 106), "Red = blocking gate fails the PR.  Amber = advisory flag for the reviewer.  - = gate passes.",
           font=font(F_REG, 21), fill=MUTED)
    for j, g in enumerate(GATES):
        x = left + j * cw + cw / 2
        words = SHORT[g["id"]].split(" ")
        lines = [" ".join(words[:2]), " ".join(words[2:])] if len(words) > 2 else [words[0], " ".join(words[1:])]
        for k, ln in enumerate(l for l in lines if l):
            tw = d.textlength(ln, font=font(F_BOLD, 19))
            d.text((x - tw / 2, 146 + k * 24), ln, font=font(F_BOLD, 19),
                   fill=BLUE if g["kind"] == "block" else YELLOW)
        sub = f'{g["seconds_median"]:.2f} s'
        tw = d.textlength(sub, font=font(F_REG, 17))
        d.text((x - tw / 2, 198), sub, font=font(F_REG, 17), fill=MUTED)
    d.text((left + cw * len(GATES) + 20, 160), "verdict", font=font(F_BOLD, 19), fill=FG)
    prev = None
    for i, c in enumerate(rows):
        y = top + i * rh
        if c["cls"] != prev:
            d.line((40, y - 2, W - 40, y - 2), fill=BORDER, width=1)
            prev = c["cls"]
        d.text((40, y + 7), c["id"], font=font(F_MONO, 20), fill=MUTED)
        title = c["title"]
        while d.textlength(title, font=font(F_REG, 20)) > left - 120:
            title = title[:-2]
        if title != c["title"]:
            title = title.rstrip() + "…"
        d.text((105, y + 7), title, font=font(F_REG, 20), fill=FG if c["cls"] != "benign" else GREEN)
        for j, g in enumerate(GATES):
            x0 = left + j * cw + 8
            hit = g["id"] in c["failed_gates"]
            if hit:
                col = RED if g["kind"] == "block" else YELLOW
                d.rounded_rectangle((x0, y + 3, x0 + cw - 16, y + rh - 3), radius=5, fill=col)
                if g["id"] in c["flaky"]:
                    d.text((x0 + 18, y + 8), c["flaky"][g["id"]], font=font(F_BOLD, 19), fill=BG)
            else:
                d.text((x0 + cw / 2 - 12, y + 5), "-", font=font(F_REG, 22), fill=GRID)
        if c["cls"] == "benign":
            v, col = ("BLOCKED" if c["blocked"] else "flag" if c["advisory_only"] else "pass"), (
                RED if c["blocked"] else YELLOW if c["advisory_only"] else GREEN)
        else:
            v, col = ("blocked" if c["blocked"] else "flag only" if c["advisory_only"] else "ESCAPED"), (
                GREEN if c["blocked"] else YELLOW if c["advisory_only"] else RED)
        d.text((left + cw * len(GATES) + 20, y + 7), v, font=font(F_BOLD, 20), fill=col)
    y = top + rh * len(rows) + 22
    d.text((40, y), "Groups: silent error D01-04, boundary D05-08, weak tests D09-12, hallucinated API D13-14, "
                    "duplicate helper D15, concurrency D16-21, security D22-26, correct changes B01-08.",
           font=font(F_REG, 19), fill=MUTED)
    d.text((40, y + 32), "A fraction in a cell (2/5) means the gate failed on that many of the 5 runs: "
                         "the racy code in D16 and D17 only sometimes loses an increment.", font=font(F_REG, 19), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "ai-sdlc-review-gates-matrix.webp"))


# ------------------------------------------------------------ yield vs cost per gate
def yield_chart():
    W, H = 1500, 760
    img, d = frame(W, H)
    d.text((40, 32), "What each gate catches, what only it catches, and what it costs per PR",
           font=font(F_BOLD, 30), fill=FG)
    d.text((40, 76), host_line(), font=font(F_REG, 20), fill=MUTED)
    x0, x1, top, rh = 330, 980, 150, 52
    n = T["defects"]
    for i in range(0, n + 1, 2):
        x = x0 + (x1 - x0) * i / n
        d.line((x, top - 10, x, top + rh * len(GATES)), fill=GRID, width=1)
        d.text((x - 8, top + rh * len(GATES) + 8), str(i), font=font(F_REG, 16), fill=MUTED)
    d.text((x0, top + rh * len(GATES) + 34), f"seeded defects flagged (of {n})", font=font(F_REG, 18), fill=MUTED)
    d.text((1040, 118), "seconds per PR", font=font(F_BOLD, 18), fill=FG)
    d.text((1230, 118), "correct PRs flagged", font=font(F_BOLD, 18), fill=FG)
    tmax = max(g["seconds_median"] for g in GATES)
    for i, g in enumerate(GATES):
        y = top + i * rh
        col = BLUE if g["kind"] == "block" else YELLOW
        d.text((40, y + 10), SHORT[g["id"]], font=font(F_BOLD, 20), fill=col)
        tot, alone = g["defects_caught"], len(g["only_gate_for"])
        wt = (x1 - x0) * tot / n
        wa = (x1 - x0) * alone / n
        if tot:
            d.rectangle((x0, y + 8, x0 + wt, y + rh - 12), fill=(48, 70, 100) if g["kind"] == "block" else (90, 75, 35))
        if alone:
            d.rectangle((x0, y + 8, x0 + wa, y + rh - 12), fill=col)
        d.text((x0 + wt + 10, y + 10), f"{tot}" + (f"  ({alone} only here)" if alone else ""),
               font=font(F_REG, 18), fill=FG)
        bw = 150 * g["seconds_median"] / tmax
        d.rectangle((1040, y + 14, 1040 + max(bw, 2), y + rh - 18), fill=MUTED)
        d.text((1040 + max(bw, 2) + 8, y + 10), f'{g["seconds_median"]:.2f}', font=font(F_REG, 18), fill=FG)
        bf = g["benign_flagged"]
        d.text((1230, y + 10), ", ".join(bf) if bf else "none", font=font(F_REG, 18), fill=RED if bf else GREEN)
    y = top + rh * len(GATES) + 70
    d.text((40, y), "Light bar: all defects the gate flags. Solid bar: defects no other blocking gate catches. "
                    "Advisory gates (amber) never block a merge.", font=font(F_REG, 18), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "ai-sdlc-review-gates-yield-cost.webp"))


# ------------------------------------------------------------ terminal panel of real findings
def findings_panel():
    pick = [("D18", "build_vet"), ("D19", "build_vet"), ("D16", "race"), ("D15", "diff_coverage"),
            ("D22", "policy"), ("D24", "policy"), ("D23", "secrets"), ("D11", "test_integrity"),
            ("D10", "test_integrity"), ("D09", "expected_moved")]
    by = {c["id"]: c for c in CASES}
    lines = []
    for cid, gid in pick:
        f = by[cid]["findings"][gid]
        lines.append((f"[{cid}] {SHORT[gid]}", MUTED))
        txt = f.split("; ")[0]
        col = YELLOW if gid == "expected_moved" else RED
        if len(txt) > 124:
            txt = txt[:123] + "…"
        lines.append(("    " + txt, col))
    size, lh = 17, 27
    W, H = 1500, 80 + lh * len(lines) + 40
    img, d = frame(W, H)
    for i, c in enumerate((RED, ORANGE, GREEN)):
        d.ellipse((34 + i * 26, 30, 48 + i * 26, 44), fill=c)
    title = "first finding of each gate, copied from the gate run (results.json)"
    tw = d.textlength(title, font=font(F_REG, 18))
    d.text((W / 2 - tw / 2, 26), title, font=font(F_REG, 18), fill=MUTED)
    y = 72
    for ln, col in lines:
        d.text((36, y), ln, font=font(F_MONO, size), fill=col)
        y += lh
    save(img, os.path.join(OUT_POSTS, "ai-sdlc-review-gates-findings.webp"))


# ------------------------------------------------------------ the diffs no gate blocked
def escapes_panel():
    by = {c["id"]: c for c in CASES}
    hints = {c["id"]: c["findings"].get("review_hints", "") for c in CASES}
    out = []
    for cid in T["not_blocked"]:
        if cid == "D09":
            continue  # shown in the findings panel
        c = by[cid]
        out.append((f"{cid}  {c['title']}", FG, True))
        body = [ln for ln in c["diff"].splitlines()
                if ln[:1] in "+-" and not ln.startswith(("+++", "---")) and ln[1:].strip()]
        for ln in body[:5]:
            out.append(("  " + ln.replace("\t", "    ")[:112], GREEN if ln[0] == "+" else RED, False))
        if len(body) > 5:
            out.append((f"  ... {len(body) - 5} more changed lines", MUTED, False))
        h = hints[cid]
        out.append(("  review hint: " + (h.split("; ")[0] if h else "none"), YELLOW if h else MUTED, False))
    size, lh = 16, 24
    W, H = 1500, 80 + lh * len(out) + 40
    img, d = frame(W, H)
    d.text((40, 30), "Seeded defects that every blocking gate let through", font=font(F_BOLD, 26), fill=FG)
    y = 74
    for ln, col, bold in out:
        if bold:
            y += 6
        d.text((40, y), ln, font=font(F_BOLD if bold else F_MONO, 18 if bold else size), fill=col)
        y += lh
    save(img, os.path.join(OUT_POSTS, "ai-sdlc-review-gates-escapes.webp"))


if __name__ == "__main__":
    os.makedirs(OUT_POSTS, exist_ok=True)
    os.makedirs(OUT_HEADER, exist_ok=True)
    header()
    matrix()
    yield_chart()
    findings_panel()
    escapes_panel()
