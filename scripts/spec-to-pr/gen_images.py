#!/usr/bin/env python3
"""Draw the webp images for the "spec to PR with coding agents: what to gate" post.

Usage:
  python3 scripts/spec-to-pr/gen_images.py --gates-term .tmp/gates-term.txt

Every number comes from scripts/data/spec-to-pr-agents.json (summarise.py).
--gates-term is the captured stdout of run_gates.py and --lint-term that of
spec_lint.py; both are drawn verbatim as terminal panels.
"""
import argparse
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data", "spec-to-pr-agents.json")
OUT_POSTS = "assets/img/posts/ai"
OUT_HEADER = "assets/img/headers/ai"
SLUG = "ai-sdlc-spec-to-pr-agents-what-to-gate"

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
YELLOW = (210, 168, 70)

D = json.load(open(DATA))
T = D["totals"]
GATES = ["own_tests", "scope", "diff_coverage", "mutation", "acceptance"]
GNAME = {"own_tests": "agent's own tests", "scope": "scope / file allow-list", "diff_coverage": "diff coverage >= 90%",
         "mutation": "mutation score >= 80%", "acceptance": "acceptance tests from spec"}
TNAME = {"T1-late-fee": "T1 late fee", "T2-charge-retry": "T2 charge retry", "T3-csv-export": "T3 CSV export",
         "T4-discount": "T4 discount", "T5-charge-log": "T5 charge log", "T6-pagination": "T6 pagination"}


def font(path, size):
    return ImageFont.truetype(path, size)


def save(img, path, quality=88):
    img.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    print("wrote", path, img.size, os.path.getsize(path), "bytes")


class FitDraw(ImageDraw.ImageDraw):
    """ImageDraw that fails loudly when a text line runs past the right frame edge."""

    def text(self, xy, text, *a, **kw):
        f = kw.get("font")
        if f is not None and "\n" not in text:
            right = xy[0] + self.textlength(text, font=f)
            if right > self.im.size[0] - 16:
                raise SystemExit(f"text overflows image ({right:.0f} > {self.im.size[0] - 16}): {text!r}")
        return super().text(xy, text, *a, **kw)


def frame(W, H):
    img = Image.new("RGB", (W, H), BG)
    d = FitDraw(img)
    d.rounded_rectangle((12, 12, W - 12, H - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    return img, d


def setup_line():
    s = D["setup"]
    return (f'{s["tickets"]} tickets x thin/full spec x {s["reps"]} runs = {s["runs"]} agent PRs, '
            f'Python {s["python"]}, {s["host"]}')


# ------------------------------------------------------------------ header 40:21
def header():
    W, H = 1600, 840
    img, d = frame(W, H)
    d.text((70, 66), "AI SDLC  |  coding agents  |  measured", font=font(F_BOLD, 30), fill=BLUE)
    d.text((70, 116), "Spec to PR with agents:", font=font(F_BOLD, 74), fill=FG)
    d.text((70, 200), "what to gate", font=font(F_BOLD, 74), fill=FG)
    th, fu, al = T["thin"], T["full"], T["all"]
    stats = [
        (f'{al["own_tests_pass"]}/{al["runs"]}', "agent PRs with green CI", GREEN),
        (f'{th["acceptance_pass"]}/{th["runs"]}', "thin-spec PRs correct", RED),
        (f'{fu["acceptance_pass"]}/{fu["runs"]}', "full-spec PRs correct", GREEN),
        (f'{th["wrong_prs_blocked_before_acceptance"]}/{th["wrong_prs"]}', "wrong PRs caught by\ncoverage + mutation", ORANGE),
    ]
    x = 70
    for big, small, col in stats:
        d.rounded_rectangle((x, 330, x + 340, 548), radius=14, fill=BG, outline=BORDER, width=2)
        d.text((x + 28, 352), big, font=font(F_BOLD, 76), fill=col)
        d.multiline_text((x + 28, 458), small, font=font(F_REG, 25), fill=MUTED, spacing=6)
        x += 368
    d.text((70, 590), "Gate the spec before the agent, and the PR against the spec after it:", font=font(F_REG, 25), fill=MUTED)
    chips = [("spec lint", YELLOW), ("agent", MUTED), ("own tests", BLUE), ("scope", BLUE), ("diff coverage", BLUE),
             ("mutation", BLUE), ("acceptance tests", GREEN), ("human review", YELLOW)]
    x, y = 70, 636
    for i, (label, col) in enumerate(chips):
        w = d.textlength(label, font=font(F_BOLD, 22)) + 30
        d.rounded_rectangle((x, y, x + w, y + 48), radius=24, fill=BG, outline=col, width=2)
        d.text((x + 15, y + 11), label, font=font(F_BOLD, 22), fill=col)
        x += w + 8
        if i < len(chips) - 1:
            d.text((x, y + 8), ">", font=font(F_BOLD, 26), fill=MUTED)
            x += 26
    d.text((70, H - 62), setup_line(), font=font(F_REG, 21), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, SLUG + ".webp"))


# ------------------------------------------------------------------ run x gate matrix
def matrix():
    runs = sorted(D["runs"], key=lambda r: (r["variant"] != "thin", r["ticket_name"], r["rep"]))
    cw, rh = 150, 34
    left, top = 330, 210
    W = left + cw * len(GATES) + 60
    H = top + rh * len(runs) + 120
    img, d = frame(W, H)
    d.text((40, 30), "24 agent PRs against 5 gates", font=font(F_BOLD, 32), fill=FG)
    d.text((40, 78), setup_line() + ".", font=font(F_REG, 20), fill=MUTED)
    d.text((40, 106), "Cell = gate result. Acceptance shows hidden spec tests passed. Red = gate fails the PR.",
           font=font(F_REG, 20), fill=MUTED)
    for j, g in enumerate(GATES):
        x = left + j * cw + cw / 2
        words = GNAME[g].split(" ")
        half = (len(words) + 1) // 2
        for k, ln in enumerate([" ".join(words[:half]), " ".join(words[half:])]):
            tw = d.textlength(ln, font=font(F_BOLD, 18))
            d.text((x - tw / 2, 146 + k * 22), ln, font=font(F_BOLD, 18), fill=GREEN if g == "acceptance" else BLUE)
    for i, r in enumerate(runs):
        y = top + i * rh
        if i == 12:
            d.line((40, y - 3, W - 40, y - 3), fill=FG, width=2)
        col = ORANGE if r["variant"] == "thin" else GREEN
        d.text((40, y + 7), f'{TNAME[r["ticket_name"]]}', font=font(F_REG, 19), fill=FG)
        d.text((215, y + 7), f'{r["variant"]} {r["rep"]}', font=font(F_MONO, 17), fill=col)
        for j, g in enumerate(GATES):
            gr = r["gates"][g]
            x0 = left + j * cw + 10
            if g == "own_tests":
                txt = f'{gr["tests"]} pass' if gr["pass"] else "fail"
            elif g == "scope":
                txt = "ok" if gr["pass"] else "out"
            elif g == "diff_coverage":
                txt = f'{gr["pct"]:.0f}%'
            elif g == "mutation":
                txt = f'{gr["score"]:.0f}%'
            else:
                txt = f'{gr["passed"]}/{gr["total"]}'
            fill = RED if not gr["pass"] else BG
            d.rounded_rectangle((x0, y + 3, x0 + cw - 20, y + rh - 3), radius=5, fill=fill, outline=BORDER)
            tw = d.textlength(txt, font=font(F_BOLD, 18))
            d.text((x0 + (cw - 20) / 2 - tw / 2, y + 7), txt, font=font(F_BOLD, 18), fill=BG if not gr["pass"] else FG)
    y = top + rh * len(runs) + 18
    d.text((40, y), "Top half: one-line tickets (14-28 words).  Bottom half: the same tickets with rules, "
                    "examples and scope (68-154 words).", font=font(F_REG, 19), fill=MUTED)
    d.text((40, y + 30), "Own tests = the suite after the agent's change (8 base tests + its own). "
                         "Every run reported its suite green.", font=font(F_REG, 19), fill=MUTED)
    d.text((40, y + 60), "Same agent, same prompt, same repo for every run; only TICKET.md differs.",
           font=font(F_REG, 19), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, SLUG + "-matrix.webp"))


# ------------------------------------------------------------------ per-ticket bars
def per_ticket():
    W, H = 1500, 720
    img, d = frame(W, H)
    d.text((40, 30), "Hidden acceptance tests passed, per ticket (2 runs each)", font=font(F_BOLD, 32), fill=FG)
    d.text((40, 78), "Orange = one-line ticket, green = full ticket. Words = ticket length.", font=font(F_REG, 21), fill=MUTED)
    x0, x1, top, rh = 330, 1180, 150, 80
    for p in range(0, 101, 20):
        x = x0 + (x1 - x0) * p / 100
        d.line((x, top - 12, x, top + rh * 6), fill=GRID, width=1)
        d.text((x - 14, top + rh * 6 + 8), f"{p}%", font=font(F_REG, 17), fill=MUTED)
    for i, (t, v) in enumerate(D["per_ticket"].items()):
        y = top + i * rh
        d.text((40, y + 8), TNAME[t], font=font(F_BOLD, 21), fill=FG)
        d.text((40, y + 38), f'{v["spec_words"]["thin"]} vs {v["spec_words"]["full"]} words', font=font(F_REG, 17), fill=MUTED)
        for k, (var, col) in enumerate((("thin", ORANGE), ("full", GREEN))):
            s = v[var]
            frac = s["acceptance_tests_passed"] / s["acceptance_tests_total"]
            yy = y + 6 + k * 32
            d.rectangle((x0, yy, x0 + (x1 - x0) * frac, yy + 26), fill=col)
            d.text((x0 + (x1 - x0) * frac + 10, yy + 2),
                   f'{s["acceptance_tests_passed"]}/{s["acceptance_tests_total"]}', font=font(F_BOLD, 19), fill=col)
        mt, mf = v["thin"]["mutation_score_median"], v["full"]["mutation_score_median"]
        d.text((1270, y + 8), f"mutation {mt:.0f}%", font=font(F_REG, 18), fill=ORANGE)
        d.text((1270, y + 40), f"mutation {mf:.0f}%", font=font(F_REG, 18), fill=GREEN)
    th, fu = T["thin"], T["full"]
    d.text((40, H - 66), f'Totals: thin {th["acceptance_tests_passed"]}/{th["acceptance_tests_total"]} '
                         f'({100 * th["acceptance_tests_passed"] / th["acceptance_tests_total"]:.0f}%), '
                         f'full {fu["acceptance_tests_passed"]}/{fu["acceptance_tests_total"]}. '
                         f'Right column: median mutation score of the agent\'s own tests on its own code.',
           font=font(F_REG, 19), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, SLUG + "-per-ticket.webp"))


# ------------------------------------------------------------------ terminal panels
def terminal(lines, title, out, colour):
    fm = font(F_MONO, 19)
    lh = 27
    W = 1500
    H = 120 + lh * len(lines) + 40
    img = Image.new("RGB", (W, H), BG)
    d = FitDraw(img)
    d.rounded_rectangle((12, 12, W - 12, H - 12), radius=12, fill=(10, 12, 16), outline=BORDER, width=2)
    d.rectangle((14, 14, W - 14, 60), fill=PANEL)
    for k, c in enumerate((RED, YELLOW, GREEN)):
        d.ellipse((34 + k * 26, 30, 50 + k * 26, 46), fill=c)
    d.text((130, 26), title, font=font(F_REG, 19), fill=MUTED)
    y = 84
    for ln in lines:
        d.text((40, y), ln, font=fm, fill=colour(ln))
        y += lh
    save(img, out)


def gates_term(path):
    raw = [l.rstrip("\n") for l in open(path) if l.strip() and not l.startswith("wrote")]
    lines = ["$ python3 scripts/spec-to-pr/run_gates.py --runs .tmp/spec-to-pr-runs --out .tmp/gates-raw.json"]
    lines += [l.replace("T6-pagination", "T6-pagination") for l in raw]

    def colour(l):
        if l.startswith("$"):
            return BLUE
        if ".thin." in l:
            acc = l.rsplit("acc=", 1)[1]
            a, b = acc.split("/")
            return ORANGE if a != b else FG
        return FG
    terminal(lines, "run_gates.py - 24 workspaces, 5 gates each", os.path.join(OUT_POSTS, SLUG + "-gates-terminal.webp"), colour)


def lint_term():
    specs = sorted(os.path.join(HERE, "specs", f) for f in os.listdir(os.path.join(HERE, "specs")))
    p = subprocess.run([sys.executable, os.path.join(HERE, "spec_lint.py")] + specs, capture_output=True, text=True)
    lines = ["$ python3 scripts/spec-to-pr/spec_lint.py scripts/spec-to-pr/specs/*.md"] + p.stdout.rstrip().splitlines()
    lines.append(f"$ echo $?")
    lines.append(str(p.returncode))

    def colour(l):
        if l.startswith("$"):
            return BLUE
        if l.startswith("FAIL"):
            return RED
        if l.startswith("ok"):
            return GREEN
        if l.startswith("     "):
            return ORANGE
        return FG
    terminal(lines, "spec_lint.py - the gate before the agent", os.path.join(OUT_POSTS, SLUG + "-spec-lint.webp"), colour)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gates-term", required=True)
    a = ap.parse_args()
    os.makedirs(OUT_POSTS, exist_ok=True)
    header()
    matrix()
    per_ticket()
    gates_term(a.gates_term)
    lint_term()


if __name__ == "__main__":
    main()
