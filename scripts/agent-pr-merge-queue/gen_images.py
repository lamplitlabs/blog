#!/usr/bin/env python3
"""Build the webp images for the "parallel agent PRs vs merge policy" post.

Usage:
  python3 scripts/agent-pr-merge-queue/gen_images.py

Everything is drawn from scripts/data/agent-pr-merge-queue.json (summarise.py) and
scripts/data/agent-pr-merge-queue-transcript.json (transcript.py). Only titles and
labels are typed in by hand.
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

D = json.load(open("scripts/data/agent-pr-merge-queue.json"))
TR = json.load(open("scripts/data/agent-pr-merge-queue-transcript.json"))
OUT_POSTS = "assets/img/posts/ai"
OUT_HEADER = "assets/img/headers/ai"
SLUG = "ai-sdlc-parallel-agent-prs-merge-queue"

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

A0, A1 = D["arms"]["default"], D["arms"]["split"]
RES_COL = {"green": GREEN, "textual": YELLOW, "build": RED, "test": PURPLE}
RES_LABEL = {"green": "clean merge, CI green", "textual": "git conflict (author must rebase)",
             "build": "clean merge, does not compile", "test": "clean merge, tests fail"}
POL_LABEL = {"stale": "Checks on PR base only,\nno up-to-date rule",
             "strict": "Require up to date,\nevery PR re-runs per landing",
             "queue1": "Merge queue,\none entry at a time",
             "queue4": "Merge queue,\n4 entries built at once"}


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
    return (f'{D["host"]["cpu"]}, {D["go"].replace("go version ", "").split(" ")[0]}, '
            f'{D["git"].split(" (")[0]}; CI = gofmt -l, go vet, go test -race on every merged tree')


def unordered(arm):
    c = {"green": 0, "textual": 0, "build": 0, "test": 0}
    T = sorted({k[:3] for k in arm["matrix"]})
    for i, a in enumerate(T):
        for b in T[i + 1:]:
            c[arm["matrix"][f"{a}>{b}"]] += 1
    return c, len(T) * (len(T) - 1) // 2


def header():
    W, H = 1600, 840
    img, d = frame(W, H)
    d.text((70, 62), "AI SDLC  |  Go  |  merge policy  |  measured", font=font(F_BOLD, 30), fill=BLUE)
    d.text((70, 112), "12 agent PRs, each green alone.", font=font(F_BOLD, 66), fill=FG)
    d.text((70, 190), "Merged together, main went red.", font=font(F_BOLD, 66), fill=FG)
    c0, n = unordered(A0)
    c1, _ = unordered(A1)
    s0, q0 = A0["policies"]["stale"], A0["policies"]["queue1"]
    s1, q1 = A1["policies"]["stale"], A1["policies"]["queue1"]
    stats = [
        (f'{c0["build"]}\u2192{c1["build"] + c1["test"]}', f"of {n} PR pairs merge cleanly\nand break the build or tests", RED),
        (f'{c0["textual"]}\u2192{c1["textual"]}', f"pairs hit a git conflict\n(default vs merge-friendly rules)", YELLOW),
        (f'{round(100 * s1["red_share_of_main_commits"])}%', "of main commits red with\nno up-to-date rule", ORANGE),
        (f'{q1["red_main_commits"]}', f'red commits on main with\na merge queue ({q1["landed_mean"]:.1f} PRs land)', GREEN),
    ]
    x = 70
    for big, small, col in stats:
        d.rounded_rectangle((x, 318, x + 340, 548), radius=14, fill=BG, outline=BORDER, width=2)
        d.text((x + 26, 338), big, font=font(F_BOLD, 70), fill=col)
        for k, ln in enumerate(small.split("\n")):
            d.text((x + 26, 444 + k * 32), ln, font=font(F_REG, 24), fill=MUTED)
        x += 368
    # mini matrices of both arms
    for j, (arm, title) in enumerate(((A0, "default AGENTS.md"), (A1, "\u201cmerge-friendly\u201d AGENTS.md"))):
        x0, y0 = 70 + j * 740, 640
        d.text((x0, y0 - 44), title, font=font(F_BOLD, 24), fill=FG)
        # compact strip: count bars
        c, n = unordered(arm)
        bx, bw = x0, 640
        acc = 0
        for k in ("green", "textual", "build", "test"):
            w = bw * c[k] / n
            if w:
                d.rectangle((bx + acc, y0, bx + acc + w, y0 + 46), fill=RES_COL[k])
                lbl = str(c[k])
                if w > 34:
                    d.text((bx + acc + 10, y0 + 9), lbl, font=font(F_BOLD, 24), fill=BG)
            acc += w
    lx = 70
    for k in ("green", "textual", "build", "test"):
        d.rectangle((lx, 720, lx + 20, 740), fill=RES_COL[k])
        d.text((lx + 30, 716), RES_LABEL[k], font=font(F_REG, 21), fill=MUTED)
        lx += 46 + d.textlength(RES_LABEL[k], font=font(F_REG, 21))
    d.text((70, H - 66), f'{unordered(A0)[1]} PR pairs per arm, 100 seeded arrival orders x 4 merge policies.  ' + host_line(),
           font=font(F_REG, 18), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, SLUG + ".webp"))


def matrix():
    cs, gap = 46, 4
    T = sorted({k[:3] for k in A0["matrix"]})
    gw = len(T) * (cs + gap)
    left, top = 110, 220
    W = left + 2 * gw + 200
    H = top + gw + 190
    img, d = frame(W, H)
    d.text((40, 30), "Every pair of the 12 agent PRs, merged in both orders and run through CI",
           font=font(F_BOLD, 30), fill=FG)
    d.text((40, 76), "Row = PR merged first, column = PR merged second. Each PR was green on its own base "
                     "before it entered the matrix.", font=font(F_REG, 20), fill=MUTED)
    d.text((40, 104), "Both orders gave the same result for every pair, so each grid is symmetric.",
           font=font(F_REG, 20), fill=MUTED)
    for j, (arm, title) in enumerate(((A0, "Arm A: default AGENTS.md"), (A1, "Arm B: \u201cmerge-friendly\u201d AGENTS.md"))):
        x0 = left + j * (gw + 110)
        d.text((x0, 150), title, font=font(F_BOLD, 23), fill=BLUE)
        c, n = unordered(arm)
        d.text((x0, 182), f'{c["textual"]} conflict, {c["build"]} no build, {c["test"]} tests fail, {c["green"]} green',
               font=font(F_REG, 19), fill=MUTED)
        for i, a in enumerate(T):
            d.text((x0 - 56, top + i * (cs + gap) + 12), a, font=font(F_MONO, 19), fill=FG)
            for k, b in enumerate(T):
                xx, yy = x0 + k * (cs + gap), top + i * (cs + gap)
                if a == b:
                    d.rectangle((xx, yy, xx + cs, yy + cs), fill=GRID)
                    continue
                r = arm["matrix"][f"{a}>{b}"]
                d.rounded_rectangle((xx, yy, xx + cs, yy + cs), radius=6, fill=RES_COL[r])
                mark = {"green": "", "textual": "C", "build": "B", "test": "T"}[r]
                if mark:
                    tw = d.textlength(mark, font=font(F_BOLD, 20))
                    d.text((xx + cs / 2 - tw / 2, yy + 12), mark, font=font(F_BOLD, 20), fill=BG)
        for k, b in enumerate(T):
            tw = d.textlength(b[1:], font=font(F_MONO, 16))
            d.text((x0 + k * (cs + gap) + cs / 2 - tw / 2, top + gw + 4), b[1:], font=font(F_MONO, 16), fill=MUTED)
    y = top + gw + 50
    lx = 40
    for k, m in (("green", ""), ("textual", "C"), ("build", "B"), ("test", "T")):
        d.rounded_rectangle((lx, y, lx + 26, y + 26), radius=5, fill=RES_COL[k])
        d.text((lx + 7, y + 2), m, font=font(F_BOLD, 18), fill=BG)
        d.text((lx + 36, y + 1), RES_LABEL[k], font=font(F_REG, 20), fill=FG)
        lx += 70 + d.textlength(RES_LABEL[k], font=font(F_REG, 20))
    d.text((40, y + 50), "Arm B's rules: new code in new files, small edits, add exported names instead of changing "
                         "them unless the ticket says so.", font=font(F_REG, 19), fill=MUTED)
    d.text((40, y + 80), host_line() + ".", font=font(F_REG, 19), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, SLUG + "-pair-matrix.webp"))


def policies():
    pols = ["stale", "strict", "queue1", "queue4"]
    W, rh = 1500, 104
    top = 200
    H = top + rh * len(pols) + 150
    img, d = frame(W, H)
    n = D["arms"]["default"]["orders"]
    d.text((40, 30), f"Four merge policies replayed on {n} seeded arrival orders of the same 12 PRs",
           font=font(F_BOLD, 30), fill=FG)
    d.text((40, 76), "Every merge is a real git merge and every verdict a real CI run on the merged tree. "
                     "Mean per order; red commits summed over all orders.", font=font(F_REG, 20), fill=MUTED)
    cols = [(470, "PRs landed (of 12)", 12), (820, "red commits on main", None), (1110, "CI runs per order", 45)]
    for x, t, _ in cols:
        d.text((x, 130), t, font=font(F_BOLD, 21), fill=FG)
    d.text((470, 160), "\u25a0 arm A default AGENTS.md   \u25a0 arm B merge-friendly", font=font(F_REG, 17), fill=MUTED)
    d.text((470, 160), "\u25a0", font=font(F_REG, 17), fill=BLUE)
    d.text((470 + d.textlength("\u25a0 arm A default AGENTS.md   ", font=font(F_REG, 17)), 160), "\u25a0",
           font=font(F_REG, 17), fill=PURPLE)
    for i, p in enumerate(pols):
        y = top + i * rh
        d.line((40, y - 8, W - 40, y - 8), fill=GRID, width=1)
        for k, ln in enumerate(POL_LABEL[p].split("\n")):
            d.text((40, y + 8 + k * 30), ln, font=font(F_BOLD if k == 0 else F_REG, 21), fill=FG if k == 0 else MUTED)
        for a_i, (arm, col) in enumerate(((A0, BLUE), (A1, PURPLE))):
            s = arm["policies"][p]
            yy = y + 6 + a_i * 40
            w = 250 * s["landed_mean"] / 12
            d.rectangle((470, yy, 470 + w, yy + 28), fill=col)
            d.text((470 + w + 10, yy + 2), f'{s["landed_mean"]:.2f}', font=font(F_BOLD, 20), fill=FG)
            red = s["red_main_commits"]
            share = s.get("red_share_of_main_commits")
            txt = f"{red}" + (f"  ({round(100 * share)}% of commits)" if share else "")
            d.text((820, yy + 2), txt, font=font(F_BOLD, 21), fill=RED if red else GREEN)
            w = 230 * s["ci_runs_mean"] / 45
            d.rectangle((1110, yy, 1110 + w, yy + 28), fill=col)
            extra = f'  ({s["ci_rounds_mean"]:.1f} rounds)'
            d.text((1110 + w + 10, yy + 2), f'{s["ci_runs_mean"]:.1f}' + extra, font=font(F_REG, 19), fill=FG)
    y = top + rh * len(pols) + 10
    notes = [
        "\u201cLanded\u201d counts PRs merged in one pass; the others go back to their agent with a conflict or a red merged "
        "tree. CI runs include the 12 PR-branch runs.",
        "Rounds = CI waits in sequence (a round runs in parallel). The no-up-to-date policy lands more because it "
        "never tests the merged tree before merging.",
        host_line() + ".",
    ]
    for k, t in enumerate(notes):
        d.text((40, y + k * 30), t, font=font(F_REG, 18), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, SLUG + "-policies.webp"))


def terminal():
    lines = []
    for s in TR:
        arm = "arm A, default AGENTS.md" if s["arm"] == "patches" else "arm B, merge-friendly AGENTS.md"
        lines.append((f'# {arm}: {s["a"]} lands, then {s["b"]} (both were green alone)', MUTED))
        for ln in s["lines"]:
            col = BLUE if ln.startswith("$") else RED if ("FAIL" in ln or "vet:" in ln or "exit" in ln
                                                             or "want" in ln) else FG
            if ln.startswith("# "):
                col = MUTED
            lines.append((ln.replace("\t", "    "), col))
        lines.append(("", FG))
    size, lh = 18, 27
    W, H = 1500, 80 + lh * len(lines) + 10
    img, d = frame(W, H)
    for i, c in enumerate((RED, ORANGE, GREEN)):
        d.ellipse((34 + i * 26, 30, 48 + i * 26, 44), fill=c)
    title = "two clean merges that break main, recorded by transcript.py (git 2.54, go1.27.4)"
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
