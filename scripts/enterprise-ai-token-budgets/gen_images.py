#!/usr/bin/env python3
"""Draw the webp images for the "Enterprise AI: token budgets that hold under concurrency" post.

    python3 scripts/enterprise-ai-token-budgets/gen_images.py --term .tmp/budgets-term.txt \
        --shot-post .tmp/status-post.png --shot-reserve .tmp/status-reserve.png

Every number comes from scripts/data/enterprise-ai-token-budgets.json (summarise.py). --term is the
captured stdout of run_experiment.py, drawn verbatim. The --shot-* PNGs are headless-browser
screenshots of the gateway's /budgets page (capture_status.py), re-encoded as webp unchanged.
"""
import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data", "enterprise-ai-token-budgets.json")
OUT_POSTS = "assets/img/posts/ai"
OUT_HEADER = "assets/img/headers/ai"
SLUG = "enterprise-ai-token-budgets-concurrency"

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
S = D["setup"]
BUDGET = S["budgets"]["batch-summariser"]
MODE_COL = {"none": MUTED, "post": RED, "estimate": ORANGE, "reserve": GREEN}
MODE_NAME = {"none": "meter only", "post": "check, bill after", "estimate": "estimate prompt", "reserve": "reserve max_tokens"}


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


def res(mode, conc):
    return next(r for r in D["results"] if r["mode"] == mode and r["conc"] == conc)


def setup_line():
    return (f'{S["batch_requests"]} batch calls x {len(S["modes"])} modes x concurrency {"/".join(map(str, S["concurrency"]))}'
            f' x {S["reps"]} reps = {S["runs"]} runs  |  SmolLM2-135M on llama-server, M2 Pro')


# ------------------------------------------------------------------ header 40:21
def header():
    W, H = 1600, 840
    img, d = frame(W, H)
    hi = max(S["concurrency"])
    d.text((70, 66), "Enterprise AI  |  cost controls  |  measured", font=font(F_BOLD, 30), fill=BLUE)
    d.text((70, 116), "Token budgets that hold", font=font(F_BOLD, 74), fill=FG)
    d.text((70, 200), "under concurrency", font=font(F_BOLD, 74), fill=FG)
    x = 70
    for mode in S["modes"]:
        r = res(mode, hi)
        big = f'{r["batch_spent"] / BUDGET * 100:.0f}%'
        d.rounded_rectangle((x, 330, x + 340, 548), radius=14, fill=BG, outline=BORDER, width=2)
        d.text((x + 28, 352), big, font=font(F_BOLD, 76), fill=MODE_COL[mode])
        d.multiline_text((x + 28, 458), f'of budget spent\n{MODE_NAME[mode]}', font=font(F_REG, 25), fill=MUTED, spacing=6)
        x += 368
    d.text((70, 590), f"Same {S['batch_requests']}-call batch job, {BUDGET:,}-token budget, {hi} parallel workers. Only the admission rule changes.",
           font=font(F_REG, 25), fill=MUTED)
    chips = [("register use case", YELLOW), ("count prompt", BLUE), ("reserve max_tokens", GREEN), ("call model", MUTED),
             ("settle real usage", GREEN), ("audit row", YELLOW)]
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


# ------------------------------------------------------------------ spent vs budget bars
def overshoot_bars():
    W, H = 1400, 760
    img, d = frame(W, H)
    d.text((50, 40), "Tokens billed to a 40,000-token team budget, by admission rule", font=font(F_BOLD, 34), fill=FG)
    d.text((50, 88), f"batch-summariser: {S['batch_requests']} calls, ~{S['batch_prompt_tokens_approx']} prompt tokens each, "
                     f"max_tokens {S['batch_max_tokens']}. Bar = median of {S['reps']} reps, tick = worst rep.",
           font=font(F_REG, 22), fill=MUTED)
    left, right, top, bottom = 300, W - 80, 160, H - 110
    vmax = 90000
    sx = lambda v: left + (right - left) * v / vmax  # noqa: E731
    for v in range(0, vmax + 1, 10000):
        x = sx(v)
        d.line((x, top, x, bottom), fill=GRID, width=1)
        d.text((x - 20, bottom + 10), f"{v // 1000}k", font=font(F_REG, 18), fill=MUTED)
    concs = S["concurrency"]
    bh, gap = 34, 10
    y = top + 10
    for mode in S["modes"]:
        d.text((50, y + 8), MODE_NAME[mode], font=font(F_BOLD, 24), fill=MODE_COL[mode])
        d.text((50, y + 40), f'mode "{mode}"', font=font(F_REG, 19), fill=MUTED)
        for conc in concs:
            r = res(mode, conc)
            x1 = sx(r["batch_spent"])
            d.rounded_rectangle((left, y, x1, y + bh), radius=6, fill=MODE_COL[mode] if conc == max(concs) else tuple(int(c * 0.55) for c in MODE_COL[mode]))
            xm = sx(r["batch_spent_max"])
            d.line((xm, y - 3, xm, y + bh + 3), fill=FG, width=2)
            over = f'+{r["batch_overshoot_pct"]:.1f}% over' if r["batch_overshoot_pct"] else "within budget"
            label = f'c={conc}: {int(r["batch_spent"]):,}  ({over}, {int(r["batch_served"])} served)'
            lx = max(x1, xm) + 12
            if lx + d.textlength(label, font=font(F_REG, 19)) > W - 30:
                lx = left + 10
            d.text((lx, y + 7), label, font=font(F_REG, 19), fill=FG)
            y += bh + gap
        y += 22
    xb = sx(BUDGET)
    d.line((xb, top - 8, xb, bottom), fill=FG, width=3)
    d.text((xb + 8, top - 30), f"budget {BUDGET:,}", font=font(F_BOLD, 20), fill=FG)
    d.text((50, H - 62), "Darker bar: 4 parallel workers. Brighter bar: 16. " + setup_line().split("|")[1].strip(),
           font=font(F_REG, 20), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, SLUG + "-overshoot.webp"))


# ------------------------------------------------------------------ spend over time
def spend_curves():
    W, H = 1400, 760
    img, d = frame(W, H)
    hi = max(S["concurrency"])
    d.text((50, 40), f"Cumulative tokens billed over time, {hi} parallel workers (rep 0)", font=font(F_BOLD, 34), fill=FG)
    d.text((50, 88), "Each step is one reply arriving. Once the line crosses the budget, every token above it is spend nobody approved.",
           font=font(F_REG, 22), fill=MUTED)
    left, right, top, bottom = 120, W - 300, 150, H - 110
    curves = D["spend_curves"]
    tmax = max(p[0] for c in curves.values() for p in c) * 1.03
    vmax = 90000
    sx = lambda t: left + (right - left) * t / tmax  # noqa: E731
    sy = lambda v: bottom - (bottom - top) * v / vmax  # noqa: E731
    for v in range(0, vmax + 1, 10000):
        d.line((left, sy(v), right, sy(v)), fill=GRID, width=1)
        d.text((left - 60, sy(v) - 10), f"{v // 1000}k", font=font(F_REG, 18), fill=MUTED)
    step = 10 if tmax < 120 else 20
    for t in range(0, int(tmax) + 1, step):
        d.text((sx(t) - 10, bottom + 10), f"{t}s", font=font(F_REG, 18), fill=MUTED)
    d.line((left, sy(BUDGET), right, sy(BUDGET)), fill=FG, width=3)
    d.text((left + 8, sy(BUDGET) - 30), f"team budget {BUDGET:,}", font=font(F_BOLD, 20), fill=FG)
    for mode in S["modes"]:
        pts = curves.get(mode)
        if not pts:
            continue
        xy = []
        for i, (t, v) in enumerate(pts):
            if i:
                xy.append((sx(t), sy(pts[i - 1][1])))
            xy.append((sx(t), sy(v)))
        d.line(xy, fill=MODE_COL[mode], width=4 if mode != "estimate" else 2)
    # end labels; modes that end on the same total (post and estimate can) share one label slot
    ends = {}
    for mode in S["modes"]:
        if curves.get(mode):
            ends.setdefault(curves[mode][-1][1], []).append(mode)
    for total, modes in ends.items():
        y = sy(total) - 12 * len(modes)
        for mode in modes:
            d.text((right + 14, y), f'{MODE_NAME[mode]} {total / 1000:.1f}k', font=font(F_BOLD, 19), fill=MODE_COL[mode])
            y += 24
    d.text((50, H - 62), "Billed when the reply arrives (prompt + completion from the server's usage block).",
           font=font(F_REG, 20), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, SLUG + "-spend-over-time.webp"))


# ------------------------------------------------------------------ budget sweep
def sweep():
    rows = D.get("budget_sweep")
    if not rows:
        return
    W, H = 1400, 700
    img, d = frame(W, H)
    d.text((50, 40), "Overshoot vs budget size, 16 parallel workers", font=font(F_BOLD, 34), fill=FG)
    d.text((50, 88), "Same batch job, one run per budget. \"Check, bill after\" overshoots by up to a wave of in-flight calls;",
           font=font(F_REG, 22), fill=MUTED)
    d.text((50, 118), "\"reserve max_tokens\" never ends above the line.", font=font(F_REG, 22), fill=MUTED)
    left, right, top, bottom = 120, W - 80, 190, H - 120
    budgets = sorted({r["budget"] for r in rows})
    vmax = 80
    sy = lambda v: bottom - (bottom - top) * v / vmax  # noqa: E731
    for v in range(0, vmax + 1, 10):
        d.line((left, sy(v), right, sy(v)), fill=GRID, width=1)
        d.text((left - 60, sy(v) - 10), f"{v}%", font=font(F_REG, 18), fill=MUTED)
    gw = (right - left) / len(budgets)
    bw = 52
    for i, b in enumerate(budgets):
        cx = left + gw * (i + 0.5)
        d.text((cx - 30, bottom + 12), f"{b // 1000}k", font=font(F_BOLD, 20), fill=FG)
        for j, mode in enumerate(("post", "reserve")):
            r = next((r for r in rows if r["budget"] == b and r["mode"] == mode), None)
            if r is None:
                continue
            x0 = cx - bw - 4 + j * (bw + 8)
            v = r["overshoot_pct"]
            if v > 0:
                d.rectangle((x0, sy(v), x0 + bw, bottom), fill=MODE_COL[mode])
            else:
                d.line((x0, bottom - 1, x0 + bw, bottom - 1), fill=MODE_COL[mode], width=4)
            label = f"+{v:.0f}%" if v > 0 else "0%"
            d.text((x0 + bw / 2 - d.textlength(label, font=font(F_BOLD, 18)) / 2, sy(v) - 26), label,
                   font=font(F_BOLD, 18), fill=MODE_COL[mode])
    d.text((left, bottom + 44), "team budget (tokens)", font=font(F_REG, 20), fill=MUTED)
    d.rectangle((W - 520, bottom + 48, W - 500, bottom + 64), fill=MODE_COL["post"])
    d.text((W - 490, bottom + 44), MODE_NAME["post"], font=font(F_REG, 20), fill=FG)
    d.rectangle((W - 300, bottom + 48, W - 280, bottom + 64), fill=MODE_COL["reserve"])
    d.text((W - 270, bottom + 44), MODE_NAME["reserve"], font=font(F_REG, 20), fill=FG)
    save(img, os.path.join(OUT_POSTS, SLUG + "-sweep.webp"))


# ------------------------------------------------------------------ terminal
def terminal(path):
    lines = [l.rstrip("\n") for l in open(path) if l.strip()]
    fm = font(F_MONO, 19)
    W = 1400
    H = 120 + 30 * len(lines) + 40
    img, d = frame(W, H)
    for i, c in enumerate((RED, YELLOW, GREEN)):
        d.ellipse((40 + i * 26, 34, 56 + i * 26, 50), fill=c)
    d.text((140, 30), "$ python3 scripts/enterprise-ai-token-budgets/run_experiment.py --conc 4,16 --reps 3",
           font=font(F_MONO, 18), fill=MUTED)
    y = 90
    for l in lines:
        mode = l.split()[0]
        col = MODE_COL.get(mode, FG)
        l = l.replace("peak_in_flight", "peak")
        d.text((40, y), l, font=fm, fill=col)
        y += 30
    save(img, os.path.join(OUT_POSTS, SLUG + "-terminal.webp"))


def shot(path, name):
    im = Image.open(path)
    save(im, os.path.join(OUT_POSTS, f"{SLUG}-{name}.webp"), quality=90)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--term")
    ap.add_argument("--shot-post")
    ap.add_argument("--shot-reserve")
    a = ap.parse_args()
    header()
    overshoot_bars()
    spend_curves()
    sweep()
    if a.term:
        terminal(a.term)
    if a.shot_post:
        shot(a.shot_post, "status-post")
    if a.shot_reserve:
        shot(a.shot_reserve, "status-reserve")


if __name__ == "__main__":
    main()
