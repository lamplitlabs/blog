#!/usr/bin/env python3
"""Build the webp images for the "agent-written code review loop, measured" post.

Usage:
  python3 scripts/ai-review-loop/gen_images.py

Everything is drawn from scripts/data/ai-review-loop-go.json (written by
summarise.py): verdicts, comment locations, diffs, oracle output and agent
replies are copied from the run, never typed in. Same palette as the gates post.
"""
import json
import os
import subprocess
import textwrap

from PIL import Image, ImageDraw, ImageFont

DATA = "scripts/data/ai-review-loop-go.json"
OUT_POSTS = "assets/img/posts/ai"
OUT_HEADER = "assets/img/headers/ai"
SLUG = "ai-sdlc-agent-code-review-loop"

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

D = json.load(open(DATA))
T = D["totals"]
ROWS = {r["pr"]: r for r in D["rows"]}
CLS = {"silent-error": "silent error", "boundary": "boundary", "weak-tests": "weak tests",
       "concurrency": "concurrency", "benign": "correct"}


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


def dots(d, W, title):
    for i, c in enumerate((RED, ORANGE, GREEN)):
        d.ellipse((34 + i * 26, 30, 48 + i * 26, 44), fill=c)
    tw = d.textlength(title, font=font(F_REG, 18))
    d.text((W / 2 - tw / 2, 26), title, font=font(F_REG, 18), fill=MUTED)


def wrap(text, width, lines):
    """textwrap.wrap, cut to `lines` lines with an ellipsis when text was dropped."""
    w = textwrap.wrap(text, width)
    if len(w) > lines:
        w = w[:lines]
        w[-1] = w[-1][: width - 2].rstrip() + " …"
    return w


def go_version():
    try:
        return subprocess.run(["go", "version"], capture_output=True, text=True).stdout.split()[2]
    except (OSError, IndexError):
        return "go"


# ------------------------------------------------------------ header (40:21)
def header():
    W, H = 1600, 840
    img, d = frame(W, H)
    d.text((70, 70), "AI SDLC  |  Go  |  measured", font=font(F_BOLD, 30), fill=BLUE)
    d.text((70, 120), "Agent reviews, agent fixes,", font=font(F_BOLD, 74), fill=FG)
    d.text((70, 205), "agent re-reviews. Who checks?", font=font(F_BOLD, 74), fill=FG)
    a, f, p = T["arms"]["r1"], T["fix"], T["planted"]
    stats = [
        (f'{a["defects_blocked"]}/{T["defects"]}', "defects flagged by review", GREEN),
        (f'{f["oracle_pass"]}/{f["fixed"]}', "fixes pass hidden tests", ORANGE),
        (f'{len(f["rereview_approved_but_oracle_fail"])}', "wrong fix the re-review approved", RED),
        (f'{p["declined"]}/{p["planted"]}', "wrong reviews declined", PURPLE),
    ]
    x = 70
    for big, small, col in stats:
        d.rounded_rectangle((x, 340, x + 340, 540), radius=14, fill=BG, outline=BORDER, width=2)
        d.text((x + 28, 362), big, font=font(F_BOLD, 76), fill=col)
        d.text((x + 28, 470), small, font=font(F_REG, 23), fill=MUTED)
        x += 368
    # the loop as a chip strip
    d.text((70, 590), "One pass of the loop, every step an agent or a gate:", font=font(F_REG, 25), fill=MUTED)
    x, y = 70, 636
    steps = [("author PR", FG), ("8 CI gates", BLUE), ("review agent", GREEN), ("fix agent", ORANGE),
             ("8 CI gates", BLUE), ("re-review", GREEN), ("hidden tests", RED)]
    for i, (label, col) in enumerate(steps):
        w = d.textlength(label, font=font(F_BOLD, 24)) + 36
        d.rounded_rectangle((x, y, x + w, y + 48), radius=24, fill=BG, outline=col, width=2)
        d.text((x + 18, y + 10), label, font=font(F_BOLD, 24), fill=col)
        x += w
        if i < len(steps) - 1:
            d.text((x + 8, y + 8), "->", font=font(F_BOLD, 26), fill=MUTED)
            x += 50
    d.text((70, H - 62), f'{T["defects"]} defective + {T["correct"]} correct agent PRs on one Go service, '
                         f'{T["agent_runs"]} agent runs, {T["model_calls"]} model calls, {go_version()}, Apple M2 Pro.',
           font=font(F_REG, 20), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, SLUG + ".webp"))


# ------------------------------------------------------------ verdict grid
def grid():
    order = [r for r in D["rows"] if r["label"] == "defect"] + [r for r in D["rows"] if r["label"] == "correct"]
    cols = [("r1", "review A\nrepo"), ("r2", "review B\nrepo"), ("d1", "review C\ndiff only"),
            ("fix", "fix\nCI gates"), ("rereview", "re-review\nverdict"), ("oracle", "hidden\ntests"),
            ("planted", "wrong review\nplanted")]
    lw, cw, rh, top = 560, 128, 40, 150
    W = lw + cw * len(cols) + 60
    H = top + rh * len(order) + 30 + 150
    img, d = frame(W, H)
    d.text((40, 30), "Every pull request through every arm of the loop", font=font(F_BOLD, 28), fill=FG)
    d.text((40, 70), "Red = blocks or fails, green = approves or passes, grey = step not run for that PR",
           font=font(F_REG, 19), fill=MUTED)
    for j, (_, lab) in enumerate(cols):
        for k, part in enumerate(lab.split("\n")):
            tw = d.textlength(part, font=font(F_BOLD, 17))
            d.text((lw + j * cw + cw / 2 - tw / 2, 102 + k * 21), part, font=font(F_BOLD, 17), fill=FG)
    y = top
    for i, r in enumerate(order):
        if i == T["defects"]:
            d.line((30, y - 1, W - 30, y - 1), fill=BORDER, width=2)
        lab_col = RED if r["label"] == "defect" else GREEN
        d.text((40, y + 9), r["pr"], font=font(F_BOLD, 18), fill=lab_col)
        t = r["title"] if len(r["title"]) <= 44 else r["title"][:43] + "…"
        d.text((112, y + 9), t, font=font(F_MONO, 15), fill=FG)
        for j, (key, _) in enumerate(cols):
            x0 = lw + j * cw + 8
            box = (x0, y + 4, x0 + cw - 16, y + rh - 4)
            txt, col = "-", BORDER
            if key in ("r1", "r2", "d1"):
                rv = r["reviews"][key]
                if rv["verdict"] == "request_changes":
                    txt, col = f'block {rv["blocking"]}', RED
                else:
                    txt, col = "approve", GREEN
            elif key == "fix" and r.get("fix"):
                txt, col = ("green", GREEN) if not r["fix"]["ci1"]["blocked"] else ("blocked", RED)
            elif key == "rereview" and r.get("rereview"):
                txt, col = ("approve", GREEN) if r["rereview"]["verdict"] == "approve" else ("block", RED)
            elif key == "oracle":
                o = r["fix"]["oracle1"] if r.get("fix") else r["oracle0"]
                txt, col = ("pass", GREEN) if o["pass"] else ("FAIL", RED)
            elif key == "planted" and r.get("planted"):
                acts = {x["action"] for x in r["planted"]["reply"]["responses"]}
                txt, col = ("declined", GREEN) if acts == {"declined"} else ("complied", RED)
            fill = BG if col == BORDER else tuple(int(c * 0.28 + b * 0.72) for c, b in zip(col, BG))
            d.rounded_rectangle(box, radius=8, fill=fill, outline=col, width=2)
            tw = d.textlength(txt, font=font(F_BOLD, 16))
            d.text(((box[0] + box[2]) / 2 - tw / 2, y + 11), txt, font=font(F_BOLD, 16),
                   fill=MUTED if col == BORDER else FG)
        y += rh
    y += 24
    notes = [
        "Top 7 rows: seeded defects that passed every blocking CI gate in the gates post. Bottom 7: correct changes.",
        "Hidden tests: for defects, run on the code after the fix round; for correct PRs, on the PR as written.",
        "PR-10 is the row to look at: three reviewers blocked it, the fix went green, the re-review approved it,",
        "and the hidden acceptance test still fails, because the fix answered the reviewer, not the requirement.",
    ]
    for n in notes:
        d.text((40, y), n, font=font(F_REG, 19), fill=YELLOW if n.startswith(("PR-10", "and the")) else MUTED)
        y += 30
    save(img, os.path.join(OUT_POSTS, SLUG + "-grid.webp"))


# ------------------------------------------------------------ PR-10 terminal panel
def pr10_panel():
    r = ROWS["PR-10"]
    blk = [c for c in r["reviews"]["r1"]["comments"] if c["severity"] == "blocking"][0]
    out = [("$ cat reviews/PR-10.r1.review0.json   # round 0, repo-aware reviewer", MUTED)]
    out += [("  " + ln, RED) for ln in wrap(f'BLOCKING {blk["file"]}:{blk["line"]}  ' + blk["body"], 118, 4)]
    out.append(("", FG))
    out.append(("$ git diff round0 round1 -- config.go   # the fix agent's answer (excerpt)", MUTED))
    body = [ln for ln in r["fix"]["diff"]["diff"].split("diff --git a/config.go")[1].split("diff --git")[0].splitlines()
            if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    keep = [ln for ln in body if any(k in ln for k in ("Warnings", "err != nil ||", "err == nil &&", "} else {", "Sprintf", "MAX_TOKENS=%q"))]
    for ln in keep[:8]:
        out.append(("  " + ln.replace("\t", "    ")[:118], GREEN if ln[0] == "+" else RED))
    out.append(("", FG))
    ci = r["fix"]["ci1"]
    out.append(("$ python3 loop.py ci $W PR-10 1", MUTED))
    out.append((f'  blocked: {ci["blocked"]}   (all 8 blocking gates green)', GREEN))
    rr = r["rereview"]
    out.append(("$ cat reviews/PR-10.r1.review1.json   # round 1 re-review", MUTED))
    out.append((f'  verdict: {rr["verdict"]}, {rr["blocking"]} blocking, {rr["nits"]} nit', GREEN))
    nit = rr["comments"][0]["body"] if rr["comments"] else ""
    out += [("  nit: " + ln if i == 0 else "       " + ln, YELLOW) for i, ln in enumerate(wrap(nit, 110, 2))]
    out.append(("", FG))
    o = r["fix"]["oracle1"]
    out.append(("$ python3 loop.py oracle $W PR-10 1   # hidden acceptance tests, never in the workspace", MUTED))
    out.append((f'  --- FAIL: {o["failed"][0]}', RED))
    for ln in o["first_lines"][:4]:
        out.append(("      " + ln, RED))
    size, lh = 16, 25
    W, H = 1500, 80 + lh * len(out) + 30
    img, d = frame(W, H)
    dots(d, W, "PR-10: the reviewer, the fixer and the re-reviewer all agree; the hidden test does not")
    y = 70
    for ln, col in out:
        d.text((36, y), ln, font=font(F_MONO, size), fill=col)
        y += lh
    save(img, os.path.join(OUT_POSTS, SLUG + "-pr10.webp"))


# ------------------------------------------------------------ planted wrong reviews
def planted_panel():
    out = []
    for pr in ("PR-14", "PR-13", "PR-06", "PR-05"):
        p = ROWS[pr]["planted"]
        c = p["review"]["comments"][0]
        rep = p["reply"]["responses"][0]
        out.append((f'{pr}w  {ROWS[pr]["title"]}', FG, True))
        out += [(("  REVIEW    " if i == 0 else "            ") + ln, RED, False)
                for i, ln in enumerate(wrap(c["body"], 110, 2))]
        note = rep["note"].replace("`", "")
        out += [((f'  {rep["action"].upper():10}' if i == 0 else "            ") + ln, GREEN, False)
                for i, ln in enumerate(wrap(note, 110, 3))]
        files = p["diff"].get("files") or []
        out.append((f'  changed: {", ".join(files) or "nothing"}   CI: {"green" if not p["ci1"]["blocked"] else "blocked"}'
                    f'   hidden tests: {"pass" if p["oracle1"]["pass"] else "FAIL"}', MUTED, False))
    size, lh = 16, 24
    W, H = 1500, 86 + lh * len(out) + 6 * 4 + 30
    img, d = frame(W, H)
    d.text((40, 30), "A confident, wrong blocking review on four correct PRs: the fix agent's reply",
           font=font(F_BOLD, 25), fill=FG)
    y = 78
    for ln, col, bold in out:
        if bold:
            y += 6
        d.text((40, y), ln, font=font(F_BOLD if bold else F_MONO, 18 if bold else size), fill=col)
        y += lh
    save(img, os.path.join(OUT_POSTS, SLUG + "-planted.webp"))


# ------------------------------------------------------------ cost per step
def cost_chart():
    a = T["arms"]
    steps = [("review, repo-aware (A)", a["r1"]["median_seconds"], a["r1"]["median_model_calls"], GREEN),
             ("review, repo-aware (B)", a["r2"]["median_seconds"], a["r2"]["median_model_calls"], GREEN),
             ("review, diff only (C)", a["d1"]["median_seconds"], a["d1"]["median_model_calls"], BLUE),
             ("fix round", T["fix"]["median_seconds"], T["fix"]["median_model_calls"], ORANGE),
             ("re-review", T["fix"]["rereview_median_seconds"], None, GREEN),
             ("reply to a wrong review", T["planted"]["median_seconds"], None, PURPLE)]
    calls = {(r["run"], r["kind"], r["round"]): [] for r in D["runs"]}
    for r in D["runs"]:
        calls[(r["run"], r["kind"], r["round"])].append(r["model_calls"])
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else None  # noqa: E731
    steps[4] = (steps[4][0], steps[4][1], med(calls.get(("r1", "review", 1), [])), steps[4][3])
    steps[5] = (steps[5][0], steps[5][1], med(calls.get(("w1", "fix", 1), [])), steps[5][3])
    W, H = 1500, 120 + 70 * len(steps) + 90
    img, d = frame(W, H)
    d.text((40, 30), "Median wall time per agent step (seconds), with median model calls", font=font(F_BOLD, 28), fill=FG)
    left, right = 400, W - 200
    mx = max(s[1] for s in steps)
    y = 100
    for lab, sec, mc, col in steps:
        d.text((40, y + 14), lab, font=font(F_REG, 22), fill=FG)
        w = (right - left) * sec / mx
        d.rounded_rectangle((left, y + 6, left + w, y + 50), radius=8, fill=col)
        d.text((left + w + 14, y + 14), f"{sec:g} s  ({mc:g} calls)", font=font(F_BOLD, 22), fill=FG)
        y += 70
    ag = T["agent_runs"]
    d.text((40, y + 20), f'{ag} agent runs in total, {T["agent_seconds"] / 60:.0f} agent-minutes, {T["model_calls"]} model calls. '
                         'CI gates and hidden tests add about 3 s per PR.', font=font(F_REG, 20), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, SLUG + "-cost.webp"))


if __name__ == "__main__":
    os.makedirs(OUT_POSTS, exist_ok=True)
    os.makedirs(OUT_HEADER, exist_ok=True)
    header()
    grid()
    pr10_panel()
    planted_panel()
    cost_chart()
