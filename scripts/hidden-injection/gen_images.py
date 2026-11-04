#!/usr/bin/env python3
"""Build the webp images for the "hidden prompt injection vs agent page readers" post.

Usage:
  python3 scripts/hidden-injection/gen_images.py --work <scratch-dir>

Reads scripts/data/hidden-injection-readers.json and <work>/capture/ (both
written by scripts/hidden-injection/bench.py). The screenshot in the
side-by-side figure is the headless-Chromium capture of a corpus page,
cropped, not edited; every number comes from the JSON.

Outputs:
  assets/img/headers/ai/ai-security-hidden-prompt-injection-page-readers.webp  (1600x840, 40:21)
  assets/img/posts/ai/hidden-injection-reader-matrix.webp
  assets/img/posts/ai/hidden-injection-what-you-see-vs-inner-text.webp
"""
import argparse
import io
import json
import os
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "scripts", "data", "hidden-injection-readers.json")
OUT_HEAD = os.path.join(ROOT, "assets", "img", "headers", "ai")
OUT_POSTS = os.path.join(ROOT, "assets", "img", "posts", "ai")
F_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
F_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
F_MONO = "/System/Library/Fonts/Menlo.ttc"

LABELS = {
    "raw_html": "Raw HTML",
    "bs4_text": "BeautifulSoup\nget_text()",
    "html2text": "html2text\n(markdown)",
    "text_content": "textContent",
    "inner_text": "innerText",
    "ax_tree": "Accessibility\ntree",
    "ocr": "OCR of a\nscreenshot",
    "visible": "Visible-text\nfilter",
    "visible_ocr": "Filter +\nOCR check",
}
MATRIX_READERS = ["raw_html", "bs4_text", "html2text", "text_content", "inner_text", "ax_tree", "ocr", "visible", "visible_ocr"]
HEADER_READERS = ["raw_html", "html2text", "bs4_text", "ax_tree", "inner_text", "visible", "ocr"]


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
    n = d["attack_pages"]
    tot = d["attack_totals"]
    fig = plt.figure(figsize=(16, 8.4), dpi=100)
    fig.patch.set_facecolor("#0d1117")
    fig.text(0.05, 0.885, "Hidden prompt injection vs agent page readers", color="#e6edf3", fontsize=38, weight="bold")
    fig.text(0.05, 0.815, "%d web pages, each hiding one injection with one of %d techniques. Share that reached the model's context:" % (
        n, len([c for c in d["carriers"] if c["group"] not in ("control", "held-out")])), color="#8b949e", fontsize=19)
    ax = fig.add_axes([0.30, 0.15, 0.64, 0.60])
    ax.set_facecolor("#0d1117")
    names = {"raw_html": "Raw HTML", "html2text": "html2text (markdown)", "bs4_text": "BeautifulSoup get_text()",
             "ax_tree": "Accessibility tree", "inner_text": "innerText", "visible": "Visible-text filter", "ocr": "OCR of a screenshot"}
    vals = [tot[r] for r in HEADER_READERS]
    colours = ["#f85149", "#f85149", "#f0883e", "#f0883e", "#d29922", "#3fb950", "#3fb950"]
    ys = list(range(len(vals)))[::-1]
    ax.barh(ys, [100.0 * v / n for v in vals], color=colours, height=0.62)
    for y, v in zip(ys, vals):
        ax.text(100.0 * v / n + 1.2, y, "%d%%  (%d/%d)" % (round(100.0 * v / n), v, n), va="center", color="#e6edf3", fontsize=19, weight="bold")
    ax.set_yticks(ys)
    ax.set_yticklabels([names[r] for r in HEADER_READERS], color="#e6edf3", fontsize=19)
    ax.set_xlim(0, 128)
    ax.set_xticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(axis="y", length=0, pad=14)
    ho = d["held_out_totals"]
    fig.text(0.05, 0.085, "Held out: %d pages, 6 techniques written after the filter was frozen. Filter alone let %d through, "
             "filter + OCR check %d." % (d["held_out_pages"], ho["visible"], ho["visible_ocr"]), color="#8b949e", fontsize=15)
    fig.text(0.05, 0.045, "%s, html2text %s, BeautifulSoup %s, Apple Vision OCR. Seed %d." % (
        d["browser"].replace("Google Chrome for Testing", "Headless Chromium"), d["html2text"], d["bs4"], d["seed"]),
        color="#8b949e", fontsize=15)
    save_fig(fig, os.path.join(OUT_HEAD, "ai-security-hidden-prompt-injection-page-readers.webp"), size=(1600, 840))


def matrix(d):
    rows = [c for c in d["carriers"]]
    n = d["pages_per_carrier"]
    fig = plt.figure(figsize=(14, 12.6), dpi=100)
    fig.patch.set_facecolor("white")
    left, width, bottom, height = 0.30, 0.69, 0.085, 0.78
    ax = fig.add_axes([left, bottom, width, height])
    # Green = payload kept out of the model's context, red = delivered.
    cmap = LinearSegmentedColormap.from_list("gr", ["#c9f0d3", "#fff1c2", "#ffd8d3"])
    grid = []
    for r in rows:
        line = []
        for k in MATRIX_READERS:
            frac = r[k] / n
            line.append(1 - frac if r["group"] == "control" else frac)
        grid.append(line)
    ax.imshow(grid, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i, r in enumerate(rows):
        for j, k in enumerate(MATRIX_READERS):
            v = r[k]
            ax.text(j, i, "%d/%d" % (v, n), ha="center", va="center", fontsize=12.5, color="#1f2328",
                    weight="bold" if v in (0, n) else "normal")
    ax.set_xticks(range(len(MATRIX_READERS)))
    ax.set_xticklabels([LABELS[k] for k in MATRIX_READERS], fontsize=11.5, color="#1f2328")
    ax.xaxis.tick_top()
    ylabels = []
    for r in rows:
        lbl = r["label"]
        if r["group"] == "held-out":
            lbl = "held out: " + lbl.replace(" = url() background", " = url() bg")
        ylabels.append(lbl)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(ylabels, fontsize=11.5, color="#1f2328")
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks([x - 0.5 for x in range(1, len(MATRIX_READERS))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(rows))], minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    # Separators between groups.
    for i in range(1, len(rows)):
        if rows[i]["group"] != rows[i - 1]["group"] and (rows[i]["group"] in ("held-out", "control") or rows[i - 1]["group"] == "markup"):
            ax.axhline(i - 0.5, color="#57606a", linewidth=1.6)
    tot, a = d["attack_totals"], d["attack_pages"]
    for j, k in enumerate(MATRIX_READERS):
        fig.text(left + width * (j + 0.5) / len(MATRIX_READERS), 0.052, "%d/%d" % (tot[k], a),
                 ha="center", va="center", fontsize=12.5, weight="bold", color="#1f2328")
    fig.text(left - 0.01, 0.052, "Delivered, %d techniques" % (a // n), ha="right", va="center", fontsize=12.5, weight="bold", color="#1f2328")
    fig.text(0.012, 0.972, "Hidden injections that reached the reader's output, by hiding technique (%d pages each)" % n,
             fontsize=15.5, weight="bold", color="#1f2328")
    fig.text(0.012, 0.012, "Red = the payload reached the text an agent would send to the model. Last row is a control with the payload in plain sight:\n"
             "there a reader should deliver it (green). %s; html2text %s; BeautifulSoup %s; Apple Vision OCR. Seed %d." % (
                 d["browser"].replace("Google Chrome for Testing", "Headless Chromium"), d["html2text"], d["bs4"], d["seed"]),
             fontsize=10.5, color="#57606a")
    save_fig(fig, os.path.join(OUT_POSTS, "hidden-injection-reader-matrix.webp"), size=(1400, 1260))


def side_by_side(d, work):
    cap = os.path.join(work, "capture")
    with open(os.path.join(cap, "example.json")) as fh:
        ex = json.load(fh)
    shot = Image.open(os.path.join(cap, "example.png")).convert("RGB")
    W, H = 1600, 900
    img = Image.new("RGB", (W, H), (246, 248, 250))
    dr = ImageDraw.Draw(img)
    hf = ImageFont.truetype(F_BOLD, 24)
    sf = ImageFont.truetype(F_REG, 17)
    mf = ImageFont.truetype(F_MONO, 15)
    # Left: the rendered page, cropped to its top 820 px, scaled to 760 wide.
    crop = shot.crop((0, 0, 1280, 1240 if shot.size[1] >= 1240 else shot.size[1]))
    scale = 760 / crop.size[0]
    crop = crop.resize((760, int(crop.size[1] * scale)), Image.LANCZOS)
    crop = crop.crop((0, 0, 760, min(crop.size[1], 790)))
    dr.text((30, 22), "What a person sees (headless Chromium screenshot)", font=hf, fill=(31, 35, 40))
    img.paste(crop, (30, 70))
    dr.rectangle((29, 69, 30 + crop.size[0], 70 + crop.size[1]), outline=(208, 215, 222), width=2)
    # Right: innerText, the payload highlighted.
    x0 = 830
    dr.text((x0, 22), "What document.body.innerText hands the model", font=hf, fill=(31, 35, 40))
    dr.rounded_rectangle((x0, 70, W - 30, 70 + 790), radius=10, fill=(13, 17, 23))
    y = 88
    text = ex["outputs"]["inner_text"]
    for para in text.split("\n"):
        hot = ex["canary"] in para
        lines = textwrap.wrap(para, 76) or [""]
        for ln in lines:
            if y > 70 + 790 - 26:
                break
            if hot:
                dr.rectangle((x0 + 10, y - 2, W - 40, y + 20), fill=(90, 20, 24))
            dr.text((x0 + 18, y), ln, font=mf, fill=(255, 166, 158) if hot else (201, 209, 217))
            y += 22
        y += 6 if para else 0
    dr.text((30, H - 30), "Page %s from the benchmark corpus: the payload is a paragraph styled color:%s on a white page. "
            "Canary %s. Nothing in the screenshot is edited." % (ex["id"], ex["variant"], ex["canary"]),
            font=sf, fill=(87, 96, 106))
    save_pil(img, os.path.join(OUT_POSTS, "hidden-injection-what-you-see-vs-inner-text.webp"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    with open(DATA) as fh:
        d = json.load(fh)
    os.makedirs(OUT_HEAD, exist_ok=True)
    os.makedirs(OUT_POSTS, exist_ok=True)
    header(d)
    matrix(d)
    side_by_side(d, a.work)


if __name__ == "__main__":
    main()
