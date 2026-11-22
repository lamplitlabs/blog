#!/usr/bin/env python3
"""Build the webp images for the "agent-written Go tests vs mutation testing" post.

Usage:
  python3 scripts/agent-tests-mutation/gen_images.py <work-dir>

Numbers come from scripts/data/agent-tests-mutation-go.json (summarise.py);
the report image is <work-dir>/shots/human-report.png from shots.sh, cropped,
never redrawn. Same dark palette as the gates and review-loop posts.
"""
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

WORK = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else None
DATA = "scripts/data/agent-tests-mutation-go.json"
OUT_POSTS = "assets/img/posts/ai"
OUT_HEADER = "assets/img/headers/ai"
SLUG = "ai-sdlc-agent-written-tests-mutation-testing"

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
PURPLE = (188, 140, 255)
YELLOW = (210, 168, 70)
GREY = (60, 66, 74)

D = json.load(open(DATA))
SUITES = D["suites"]
ARM_COL = {"human": FG, "plain": BLUE, "coverage": YELLOW, "mutants": PURPLE, "plainmut": ORANGE}
ARM_NAME = {"human": "hand-written suite", "plain": "\"write unit tests\"",
            "coverage": "\"reach 90% coverage\"", "mutants": "\"kill mutants\" on the hand suite",
            "plainmut": "\"kill mutants\" on an agent suite"}
CLS = {"silent-error": "silent error", "boundary": "boundary", "weak-tests": "weak tests",
       "hallucinated-api": "hallucinated API", "duplicate-helper": "duplicate helper",
       "concurrency": "concurrency", "security": "security", "benign": "correct change"}


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


def score(s):
    m = s["mutation_score_pct"]
    return m[0] if isinstance(m, list) else m


def caught(s):
    return s["caught_test_or_race"]


def go_version():
    return D.get("host", {}).get("go") or subprocess.run(["go", "env", "GOVERSION"], capture_output=True,
                                                         text=True).stdout.strip()


# ------------------------------------------------------------ header (40:21)
def header():
    W, H = 1600, 840
    img, d = frame(W, H)
    d.text((70, 62), "AI SDLC  |  Go  |  measured", font=font(F_BOLD, 30), fill=BLUE)
    d.text((70, 110), "Agent-written Go tests: same 97.3%", font=font(F_BOLD, 62), fill=FG)
    d.text((70, 182), "mutation score, 15 vs 18-19 bugs caught", font=font(F_BOLD, 62), fill=FG)
    # scatter: x = mutation score, y = seeded defects caught (go test or -race)
    px0, py0, pw, ph = 170, 300, 1000, 400
    xmin, xmax, ymin, ymax = 70, 100, 8, 20
    d.rectangle((px0, py0, px0 + pw, py0 + ph), fill=BG, outline=BORDER, width=2)

    def X(v):
        return px0 + (v - xmin) / (xmax - xmin) * pw

    def Y(v):
        return py0 + ph - (v - ymin) / (ymax - ymin) * ph
    for v in range(xmin, xmax + 1, 5):
        d.line((X(v), py0, X(v), py0 + ph), fill=GREY, width=1)
        t = f"{v}%"
        d.text((X(v) - d.textlength(t, font=font(F_REG, 20)) / 2, py0 + ph + 10), t, font=font(F_REG, 20),
               fill=MUTED)
    for v in range(ymin, ymax + 1, 2):
        d.line((px0, Y(v), px0 + pw, Y(v)), fill=GREY, width=1)
        t = str(v)
        d.text((px0 - 16 - d.textlength(t, font=font(F_REG, 20)), Y(v) - 12), t, font=font(F_REG, 20), fill=MUTED)
    d.text((px0 + pw / 2 - 210, py0 + ph + 40), "mutation score (gomut, 81 mutants)", font=font(F_REG, 22),
           fill=MUTED)
    lab = "seeded defects caught of 26"
    tmp = Image.new("RGBA", (int(d.textlength(lab, font=font(F_REG, 22))) + 4, 30), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((2, 2), lab, font=font(F_REG, 22), fill=MUTED)
    tmp = tmp.rotate(90, expand=True)
    img.paste(tmp, (px0 - 80, int(py0 + ph / 2 - tmp.size[1] / 2)), tmp)
    # points; identical points within an arm are spread a little sideways
    seen = {}
    for s in SUITES:
        k = (score(s), caught(s))
        n = seen.get(k, 0)
        seen[k] = n + 1
        x, y = X(k[0]) + n * 16, Y(k[1])
        c = ARM_COL[s["arm"]]
        d.ellipse((x - 11, y - 11, x + 11, y + 11), fill=c, outline=BG, width=2)
    # legend with arm ranges
    lx, ly = 1205, 296
    for arm in ("human", "plain", "coverage", "mutants", "plainmut"):
        a = D["arms"][arm]
        lo, hi = a["mutation_score_pct"]
        cs = a["caught_test_or_race"]
        sc = f"{lo:g}%" if lo == hi else f"{lo:g}-{hi:g}%"
        ct = f"{min(cs)}" if min(cs) == max(cs) else f"{min(cs)}-{max(cs)}"
        d.ellipse((lx, ly + 6, lx + 20, ly + 26), fill=ARM_COL[arm])
        d.text((lx + 32, ly), ARM_NAME[arm], font=font(F_BOLD, 19), fill=FG)
        d.text((lx + 32, ly + 27), f"score {sc}, caught {ct}", font=font(F_REG, 18), fill=MUTED)
        ly += 80
    d.text((70, H - 62), f"13 suites (1 hand-written, 12 agent-written) for one 282-line Go service, "
                         f"26 seeded agent-style defects, {go_version()}, Apple M2 Pro.",
           font=font(F_REG, 20), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, SLUG + ".webp"))


# ------------------------------------------------------------ gomut report screenshot
def report():
    src = os.path.join(WORK, "shots", "human-report.png")
    im = Image.open(src).convert("RGB")
    px = im.load()
    W, H = im.size
    bg = px[5, 5]
    last = 0
    for y in range(H):
        if any(abs(px[x, y][0] - bg[0]) > 6 for x in range(0, W, 3)):
            last = y
    im = im.crop((0, 0, W, min(H, last + 24)))
    save(im, os.path.join(OUT_POSTS, SLUG + "-report.webp"), quality=90)


# ------------------------------------------------------------ defect x suite matrix
def matrix():
    defs = D["defects"]
    seeded = [x for x in defs if x["cls"] != "benign"]
    cols = SUITES
    lw, cw, rh, top = 600, 74, 31, 190
    W = lw + cw * len(cols) + 50
    H = top + rh * len(seeded) + 150
    img, d = frame(W, H)
    d.text((40, 32), "Which seeded defect each test suite catches", font=font(F_BOLD, 28), fill=FG)
    d.text((40, 72), "Green = go test fails, blue = only go test -race fails, dark = the defect passes CI. "
                     "Same 26 defects, every suite run twice.", font=font(F_REG, 18), fill=MUTED)
    groups = [("human", "hand"), ("plain", "plain"), ("coverage", "90% cov"), ("mutants", "mutants/hand"),
              ("plainmut", "mutants/plain")]
    for arm, lab in groups:
        js = [j for j, s in enumerate(cols) if s["arm"] == arm]
        x0, x1 = lw + js[0] * cw, lw + (js[-1] + 1) * cw
        d.line((x0 + 6, 132, x1 - 6, 132), fill=ARM_COL[arm], width=3)
        t = lab
        d.text(((x0 + x1) / 2 - d.textlength(t, font=font(F_BOLD, 18)) / 2, 106), t, font=font(F_BOLD, 18),
               fill=ARM_COL[arm])
    for j, s in enumerate(cols):
        t = "-" if s["run"] == "human" else s["run"].split("-")[1]
        d.text((lw + j * cw + cw / 2 - d.textlength(t, font=font(F_REG, 16)) / 2, 142), t,
               font=font(F_REG, 16), fill=MUTED)
        sc = f"{score(s):g}%"
        d.text((lw + j * cw + cw / 2 - d.textlength(sc, font=font(F_BOLD, 16)) / 2, 162), sc,
               font=font(F_BOLD, 16), fill=FG)
    d.text((40, 162), "mutation score", font=font(F_BOLD, 16), fill=FG)
    prev = None
    for i, x in enumerate(seeded):
        y = top + i * rh
        if x["cls"] != prev:
            d.line((40, y - 1, W - 40, y - 1), fill=BORDER, width=1)
            prev = x["cls"]
        title = x["title"]
        if len(title) > 50:
            title = title[:48].rstrip() + "…"
        d.text((40, y + 6), x["id"], font=font(F_MONO, 15), fill=MUTED)
        d.text((88, y + 5), title, font=font(F_REG, 16), fill=FG)
        cl = CLS[x["cls"]]
        d.text((lw - 14 - d.textlength(cl, font=font(F_REG, 14)), y + 7), cl, font=font(F_REG, 14), fill=MUTED)
        for j, s in enumerate(cols):
            r = s["defects"][x["id"]]
            if r["test"] == "yes":
                c = GREEN
            elif r["race"] == "yes":
                c = BLUE
            elif "flaky" in (r["test"], r["race"]):
                c = YELLOW
            else:
                c = (33, 38, 45)
            cx = lw + j * cw
            d.rounded_rectangle((cx + 6, y + 3, cx + cw - 6, y + rh - 3), radius=5, fill=c)
    y = top + rh * len(seeded) + 14
    d.line((40, y - 8, W - 40, y - 8), fill=BORDER, width=1)
    d.text((40, y), "caught (go test or -race)", font=font(F_BOLD, 17), fill=FG)
    for j, s in enumerate(cols):
        t = f"{caught(s)}/26"
        d.text((lw + j * cw + cw / 2 - d.textlength(t, font=font(F_BOLD, 17)) / 2, y), t,
               font=font(F_BOLD, 17), fill=FG)
    d.text((40, y + 40), "Yellow = caught in one of the two runs only (counted as not caught). "
                         "No suite failed on any of the 5 behaviour-preserving changes.",
           font=font(F_REG, 17), fill=MUTED)
    d.text((40, y + 70), "Columns: one suite per agent run (r1-r3). mutants/hand started from the hand-written suite, "
                         "mutants/plain rN from plain rN.", font=font(F_REG, 17), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, SLUG + "-matrix.webp"))


if __name__ == "__main__":
    os.makedirs(OUT_POSTS, exist_ok=True)
    os.makedirs(OUT_HEADER, exist_ok=True)
    header()
    matrix()
    if WORK:
        report()
