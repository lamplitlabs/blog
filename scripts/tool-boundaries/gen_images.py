#!/usr/bin/env python3
"""Build the webp images for the "tool-call permission boundaries, measured" post.

Usage:
  python3 scripts/tool-boundaries/gen_images.py --work <scratch-dir>

Reads scripts/data/agent-tool-boundaries.json and <work>/capture/*.txt (both
written by scripts/tool-boundaries/bench.py). Every number comes from the
JSON; the terminal panels print captured transcripts verbatim (lines selected,
long lines cut with an ellipsis, the scratch path shortened to ~bench).

Outputs:
  assets/img/headers/ai/ai-security-agent-tool-boundaries-measured.webp  (1600x840, 40:21)
  assets/img/posts/ai/agent-tool-boundaries-matrix.webp
  assets/img/posts/ai/agent-tool-boundaries-glob-bypass.webp
  assets/img/posts/ai/agent-tool-boundaries-sandbox-denied.webp
  assets/img/posts/ai/agent-tool-boundaries-cost.webp
"""
import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "scripts", "data", "agent-tool-boundaries.json")
OUT_HEAD = os.path.join(ROOT, "assets", "img", "headers", "ai")
OUT_POSTS = os.path.join(ROOT, "assets", "img", "posts", "ai")
F_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
F_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
F_MONO = "/System/Library/Fonts/Menlo.ttc"

BG = (13, 17, 23)
PANEL = (22, 27, 34)
BORDER = (48, 54, 61)
FG = (230, 237, 243)
MUTED = (139, 148, 158)
RED = (248, 81, 73)
ORANGE = (240, 136, 62)
YELLOW = (210, 153, 34)
GREEN = (63, 185, 80)
BLUE = (88, 166, 255)

NAMES = {"none": "No boundary", "allowlist": "Program allowlist", "allowlist+args": "Allowlist + argument rules",
         "env-scrub": "Scrubbed environment", "sandbox": "OS sandbox (sandbox-exec)", "sandbox+scrub": "Sandbox + scrubbed env"}
SHORT = {"none": "none", "allowlist": "allowlist", "allowlist+args": "allowlist\n+ args", "env-scrub": "scrubbed\nenv",
         "sandbox": "OS\nsandbox", "sandbox+scrub": "sandbox\n+ scrub"}


def font(path, size):
    return ImageFont.truetype(path, size)


def save(img, path, quality=88):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    print("wrote", os.path.relpath(path, ROOT), img.size, os.path.getsize(path), "bytes")


def colour_for(frac):
    if frac >= 0.75:
        return RED
    if frac >= 0.4:
        return ORANGE
    if frac > 0.05:
        return YELLOW
    return GREEN


def header(d):
    W, H = 1600, 840
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    s = d["summary"]
    n_att = len(d["attacks"])
    n_task = len(d["tasks"])
    dr.text((80, 62), "Tool-call permission boundaries, measured", font=font(F_BOLD, 54), fill=FG)
    dr.text((80, 140), "A hijacked coding agent ran %d attacks against each boundary: read files outside the" % n_att,
            font=font(F_REG, 27), fill=MUTED)
    dr.text((80, 176), "workspace, read env secrets, write ~/.zshrc, exfiltrate. Attacks that reached their goal:",
            font=font(F_REG, 27), fill=MUTED)
    label_f, val_f = font(F_REG, 30), font(F_BOLD, 30)
    x0, x1 = 560, 1330
    y = 258
    for pol in d["policies"]:
        met = s[pol]["attacks_met"]
        frac = met / n_att
        dr.text((x0 - 24, y + 4), NAMES[pol], font=label_f, fill=FG, anchor="ra")
        dr.rounded_rectangle((x0, y, x1, y + 46), radius=6, fill=PANEL)
        if met:
            dr.rounded_rectangle((x0, y, x0 + max(12, int((x1 - x0) * frac)), y + 46), radius=6, fill=colour_for(frac))
        dr.text((x1 + 22, y + 6), "%d/%d" % (met, n_att), font=val_f, fill=FG)
        y += 76
    tasks = ", ".join("%s %d/%d" % (NAMES[p].split(" (")[0].split(" + ")[0] if p not in ("allowlist+args", "sandbox+scrub") else
                                   {"allowlist+args": "argument rules", "sandbox+scrub": "sandbox + scrub"}[p],
                                   s[p]["tasks_ok"], n_task) for p in ("allowlist+args", "sandbox", "sandbox+scrub"))
    dr.text((80, 728), "Normal tasks still working (%d: go test, npm test, git commit, sed -i, ...): %s." % (n_task, tasks),
            font=font(F_REG, 24), fill=MUTED)
    m = d["machine"]
    dr.text((80, 770), "%s, %s, %s. Seed %d. Every attack ran on a fresh copy of the fixture." % (
        m["os"], m["cpu"], m["go"].replace("go version ", "").split(" ")[0], d["seed"]), font=font(F_REG, 22), fill=MUTED)
    save(img, os.path.join(OUT_HEAD, "ai-security-agent-tool-boundaries-measured.webp"))


GOAL_LABEL = {"read-file": "read file", "read-csv": "read file", "read-env": "read env", "write-outside": "write outside",
              "exfil-file": "exfiltrate", "exfil-src": "send source", "exfil-env": "exfiltrate env"}


def matrix(d):
    pols = d["policies"]
    rows = d["attacks"]
    cell = {(c["attack"], c["policy"]): c for c in d["attack_cells"]}
    lab_w, goal_w, cw, rh, top = 560, 170, 150, 34, 150
    W = lab_w + goal_w + cw * len(pols) + 40
    H = top + rh * len(rows) + 150
    img = Image.new("RGB", (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(img)
    dr.text((30, 22), "Which boundary held each attack (%d attacks x %d boundaries, fresh fixture per cell)" % (len(rows), len(pols)),
            font=font(F_BOLD, 24), fill=(31, 35, 40))
    hf = font(F_BOLD, 17)
    for j, p in enumerate(pols):
        cx = lab_w + goal_w + cw * j + cw // 2
        for k, ln in enumerate(SHORT[p].split("\n")):
            dr.text((cx, 78 + k * 22), ln, font=hf, fill=(31, 35, 40), anchor="ma")
    dr.text((30, 100), "attack (what the hijacked agent ran)", font=hf, fill=(87, 96, 106))
    dr.text((lab_w, 100), "goal", font=hf, fill=(87, 96, 106))
    rf, mf, cf = font(F_REG, 16), font(F_MONO, 15), font(F_BOLD, 15)
    styles = {"-": ((255, 216, 211), (164, 14, 38), "BREACH"), "validator": ((201, 240, 211), (26, 127, 55), "refused"),
              "sandbox": ((201, 240, 211), (26, 127, 55), "denied"), "env-scrub": ((221, 244, 255), (9, 105, 218), "no secret"),
              "attack-failed": ((240, 240, 240), (87, 96, 106), "failed")}
    for i, a in enumerate(rows):
        y = top + rh * i
        if i % 2:
            dr.rectangle((20, y, W - 20, y + rh), fill=(246, 248, 250))
        lbl = a["label"] if len(a["label"]) <= 52 else a["label"][:51] + "..."
        dr.text((30, y + 8), lbl, font=mf, fill=(31, 35, 40))
        dr.text((lab_w, y + 8), GOAL_LABEL[a["goal"]], font=rf, fill=(87, 96, 106))
        for j, p in enumerate(pols):
            c = cell[(a["id"], p)]
            bg, fg, txt = styles[c["stopped_by"]]
            x = lab_w + goal_w + cw * j
            dr.rectangle((x + 4, y + 3, x + cw - 4, y + rh - 3), fill=bg)
            dr.text((x + cw // 2, y + 9), txt, font=cf, fill=fg, anchor="ma")
    y = top + rh * len(rows) + 14
    dr.line((20, y - 6, W - 20, y - 6), fill=(87, 96, 106), width=2)
    dr.text((30, y + 4), "attacks that reached their goal", font=font(F_BOLD, 17), fill=(31, 35, 40))
    dr.text((30, y + 40), "normal tasks that still worked", font=font(F_BOLD, 17), fill=(31, 35, 40))
    for j, p in enumerate(pols):
        s = d["summary"][p]
        cx = lab_w + goal_w + cw * j + cw // 2
        dr.text((cx, y + 4), "%d/%d" % (s["attacks_met"], s["attacks"]), font=font(F_BOLD, 19),
                fill=(164, 14, 38) if s["attacks_met"] else (26, 127, 55), anchor="ma")
        dr.text((cx, y + 40), "%d/%d" % (s["tasks_ok"], s["tasks"]), font=font(F_BOLD, 19),
                fill=(26, 127, 55) if s["tasks_ok"] == s["tasks"] else (154, 103, 0), anchor="ma")
    dr.text((30, H - 40), "refused = the command validator blocked the call; denied = the kernel sandbox returned "
            "'Operation not permitted' or refused the connection; no secret = the run had no ACME_* variable to leak.",
            font=font(F_REG, 15), fill=(87, 96, 106))
    save(img, os.path.join(OUT_POSTS, "agent-tool-boundaries-matrix.webp"))


def read_capture(work, name):
    with open(os.path.join(work, "capture", name)) as fh:
        lines = fh.read().splitlines()
    return lines


def tidy(work, lines, width=96):
    real = os.path.realpath(os.path.abspath(work))
    out = []
    for ln in lines:
        ln = ln.replace(real, "~bench")
        if ln.startswith("# server hits:"):
            try:
                hits = json.loads(ln[len("# server hits:"):].strip())
            except ValueError:
                hits = []
            for h in hits:
                out.append("# collector got %s %s on port %d: %s" % (h["method"], h["path"], h["port"], h["body"][:60]))
            if not hits:
                out.append("# no request reached either server")
            continue
        if len(ln) > width:
            ln = ln[:width - 3] + "..."
        out.append(ln)
    return out


def terminal_panels(panels, out, width=1600, size=18):
    mono = font(F_MONO, size)
    line_h = int(size * 1.5)
    title_f = font(F_BOLD, 21)
    total = 40
    for title, lines in panels:
        total += 60 + line_h * len(lines) + 34
    img = Image.new("RGB", (width, total), BG)
    dr = ImageDraw.Draw(img)
    y = 20
    for title, lines in panels:
        h = 60 + line_h * len(lines) + 20
        dr.rounded_rectangle((16, y, width - 16, y + h), radius=12, fill=PANEL, outline=BORDER, width=2)
        for i, c in enumerate((RED, ORANGE, GREEN)):
            dr.ellipse((36 + i * 24, y + 20, 50 + i * 24, y + 34), fill=c)
        dr.text((120, y + 16), title, font=title_f, fill=FG)
        yy = y + 56
        for ln in lines:
            col = FG
            if ln.startswith("$ "):
                col = BLUE
            elif ln.startswith("[refused]") or "refused by policy" in ln:
                col = GREEN
            elif "Operation not permitted" in ln or "operation not permitted" in ln or ln.startswith("# no request"):
                col = GREEN
            elif "ACME-CANARY" in ln or ln.startswith("# goal met: True") or ln.startswith("# collector got"):
                col = RED
            elif ln.startswith("["):
                col = MUTED
            dr.text((40, yy), ln, font=mono, fill=col)
            yy += line_h
        y += h + 14
    save(img, os.path.join(OUT_POSTS, out))


def glob_bypass(d, work):
    panels = []
    for att, pol, title in (("read_rel", "allowlist_args", "allowlist + argument rules: `cat ../.config/...` is refused"),
                            ("read_glob", "allowlist_args", "allowlist + argument rules: the same read through the glob .[.] passes"),
                            ("read_glob", "sandbox", "OS sandbox: the same glob, denied by the kernel")):
        panels.append((title, tidy(work, read_capture(work, "attack-%s-%s.txt" % (att, pol)))))
    terminal_panels(panels, "agent-tool-boundaries-glob-bypass.webp")


def sandbox_denied(d, work):
    panels = []
    for att, pol, title in (("git_fsmonitor_post", "allowlist_args", "allowlist + argument rules: a .git/config fsmonitor hook runs curl"),
                            ("git_fsmonitor_post", "sandbox", "OS sandbox: write_file to .git/config is denied"),
                            ("make_env", "sandbox", "OS sandbox, full environment: the Makefile prints the env token"),
                            ("make_env", "sandbox_scrub", "sandbox + scrubbed environment: nothing to print")):
        lines = tidy(work, read_capture(work, "attack-%s-%s.txt" % (att, pol)))
        panels.append((title, lines[:9]))
    terminal_panels(panels, "agent-tool-boundaries-sandbox-denied.webp")


def cost(d):
    tasks = [t["id"] for t in d["tasks"]]
    tc = {(c["task"], c["policy"]): c for c in d["task_cells"]}
    pick = [("none", "no boundary"), ("allowlist+args", "allowlist + args"), ("sandbox+scrub", "sandbox + scrub")]
    W = 1600
    rh = 30
    top = 150
    H = top + rh * len(tasks) + 120
    img = Image.new("RGB", (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(img)
    dr.text((30, 22), "What the boundaries cost the %d normal tasks: median wall time of %d runs (ms)" % (len(tasks), d["repeats"]),
            font=font(F_BOLD, 24), fill=(31, 35, 40))
    sp = d["spawn_median_ms"]
    dr.text((30, 62), "Fixed cost: bash -c true %.1f ms, sandbox-exec bash -c true %.1f ms; validators %.0f-%.0f us per command." % (
        sp["bash -c true"], sp["sandbox-exec bash -c true"], d["validator_us_per_command"]["allowlist"],
        d["validator_us_per_command"]["allowlist+args"]), font=font(F_REG, 19), fill=(87, 96, 106))
    hf = font(F_BOLD, 17)
    xs = [700, 960, 1220]
    dr.text((30, 112), "task", font=hf, fill=(87, 96, 106))
    for x, (_, name) in zip(xs, pick):
        dr.text((x, 112), name, font=hf, fill=(31, 35, 40))
    dr.text((1440, 112), "sandbox vs none", font=hf, fill=(31, 35, 40))
    mf, rf = font(F_MONO, 15), font(F_REG, 17)
    labels = {t["id"]: t["label"] for t in d["tasks"]}
    for i, t in enumerate(tasks):
        y = top + rh * i
        if i % 2:
            dr.rectangle((20, y - 4, W - 20, y + rh - 4), fill=(246, 248, 250))
        lbl = labels[t] if len(labels[t]) <= 66 else labels[t][:65] + "..."
        dr.text((30, y), lbl, font=mf, fill=(31, 35, 40))
        for x, (p, _) in zip(xs, pick):
            c = tc[(t, p)]
            if c["ok"]:
                dr.text((x, y), "%.1f" % c["median_ms"], font=rf, fill=(31, 35, 40))
            else:
                dr.text((x, y), "refused", font=font(F_BOLD, 17), fill=(164, 14, 38))
        a, b = tc[(t, "none")], tc[(t, "sandbox+scrub")]
        if a["ok"] and b["ok"]:
            dr.text((1440, y), "%+.1f ms" % (b["median_ms"] - a["median_ms"]), font=rf, fill=(87, 96, 106))
    y = top + rh * len(tasks) + 20
    dr.text((30, y), "Times include process start, the tool itself and (for sandboxed runs) sandbox-exec compiling the profile. "
            "Host: %s, %s." % (d["machine"]["cpu"], d["machine"]["os"]), font=font(F_REG, 16), fill=(87, 96, 106))
    dr.text((30, y + 28), "Warm Go build and npm caches; go test runs with -count=1. Min and max per cell are in "
            "scripts/data/agent-tool-boundaries.json.", font=font(F_REG, 16), fill=(87, 96, 106))
    save(img, os.path.join(OUT_POSTS, "agent-tool-boundaries-cost.webp"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    with open(DATA) as fh:
        d = json.load(fh)
    header(d)
    matrix(d)
    glob_bypass(d, a.work)
    sandbox_denied(d, a.work)
    cost(d)


if __name__ == "__main__":
    main()
