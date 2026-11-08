#!/usr/bin/env python3
"""Draw the webp images for the "replay data vs forgetting, measured" post.

    python3 scripts/finetune-replay/gen_post_images.py --work <run_mixes.sh work dir>

Every number comes from scripts/data/finetune-replay-smollm2-135m.json (written by
scripts/finetune-replay/summarise.py from the llama-finetune / llama-perplexity logs), and the
terminal image prints lines copied from <work>/logs/*.general.log; nothing is typed in by hand.

Outputs:
  assets/img/headers/ai/fine-tuning-replay-mix-forgetting.webp          (1600x840, 40:21)
  assets/img/posts/ai/fine-tuning-replay-mix-layout.webp                (1400x520)
  assets/img/posts/ai/fine-tuning-replay-mix-tradeoff.webp              (1400x1000)
  assets/img/posts/ai/fine-tuning-replay-kl-terminal.webp               (1400x?)
  assets/img/posts/ai/fine-tuning-replay-vs-learning-rate.webp          (1400x640)
"""
from __future__ import annotations

import argparse
import io
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "scripts", "data", "finetune-replay-smollm2-135m.json")
OUT_HEAD = os.path.join(ROOT, "assets", "img", "headers", "ai")
OUT_POSTS = os.path.join(ROOT, "assets", "img", "posts", "ai")

INK, MUTED, GRID = "#1f2328", "#57606a", "#d0d7de"
GREY, BLUE, ORANGE = "#8c959f", "#0969da", "#d1601f"
MIX_COLOUR = {0: "#cf222e", 10: "#d1601f", 25: "#8250df", 50: "#1a7f37"}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 13, "axes.edgecolor": GRID, "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.titleweight": "bold", "axes.titlesize": 15,
    "axes.titlecolor": INK,
})


def save(fig, name, out_dir, size):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    im = Image.open(buf).convert("RGB")
    if im.size != size:
        raise SystemExit(f"{name}: rendered {im.size}, expected {size}")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    im.save(path, "WEBP", quality=88, method=6)
    print("wrote", os.path.relpath(path, ROOT), im.size)


def tidy(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


MAIN_LR = "1e-5"


def by_epoch(d, ep, lr=MAIN_LR):
    return [r for r in d["runs"] if r["epoch"] == ep and r["lr"] == lr and not r.get("order_seed")]


def reshuffled(d, ep):
    return [r for r in d["runs"] if r["epoch"] == ep and r.get("order_seed")]


def mix_layout(d):
    mixes = d["mixes"]["mixes"]
    fig, ax = plt.subplots(figsize=(14, 5.2))
    names = sorted((k for k in mixes if k.isdigit()), key=int)
    for i, k in enumerate(names):
        y = len(names) - 1 - i
        layout = mixes[k].get("layout") or [["D", mixes[k]["domain_chars"]]]
        x = 0
        for kind, n in layout:
            ax.barh(y, n / 1000, left=x / 1000, height=0.62, color=BLUE if kind == "D" else ORANGE, linewidth=0)
            x += n
        ax.text(-6, y, f"{k}% replay", ha="right", va="center", fontsize=13.5, fontweight="bold", color=INK)
    total = d["mixes"]["train_chars"] / 1000
    ax.axvline(total * 0.95, color=INK, linestyle="--", linewidth=1.2)
    ax.text(total * 0.95, len(names) - 0.45, "last 5%: llama-finetune's\nvalidation split", ha="center",
            va="bottom", fontsize=11, color=INK)
    ax.set_xlim(0, total * 1.005)
    ax.set_ylim(-0.6, len(names) + 0.15)
    ax.set_yticks([])
    ax.set_xlabel("position in the 400 KB training file (thousand characters)")
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    fig.text(0.01, 0.95, "Same 400 KB budget, four mixes", fontsize=16, fontweight="bold", color=INK)
    fig.text(0.01, 0.885, "■ this blog's posts (the task)", fontsize=12.5, color=BLUE)
    fig.text(0.24, 0.885, "■ general English replay (Wikinews, Wikivoyage, Wikibooks)", fontsize=12.5, color=ORANGE)
    fig.subplots_adjust(left=0.11, right=0.99, top=0.76, bottom=0.15)
    save(fig, "fine-tuning-replay-mix-layout.webp", OUT_POSTS, (1400, 520))


def tradeoff(d):
    base = d["runs"][0]
    e1, e2 = by_epoch(d, 1), by_epoch(d, 2)
    xs = [r["replay_pct"] for r in e2]
    specs = [
        ("ppl_seen", lambda r: r["ppl_seen"]["ppl"], "Blog text it trained on", "perplexity, lower is better"),
        ("ppl_heldout", lambda r: r["ppl_heldout"]["ppl"], "33 held-out blog posts", "perplexity, lower is better"),
        ("kld", lambda r: r["general"]["kld_mean"], "Drift on general English", "mean KL divergence to base, nats/token"),
        ("hs", lambda r: r["hellaswag"]["acc"], "HellaSwag (1,000 tasks)", "accuracy %, higher is better"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    for ax, (key, fn, title, sub) in zip(axes.flat, specs):
        for runs, style, lab in ((e1, "o--", "after epoch 1"), (e2, "o-", "after epoch 2")):
            ys = [fn(r) for r in runs]
            ax.plot([r["replay_pct"] for r in runs], ys, style, color=INK if style == "o-" else GREY,
                    linewidth=2.2, markersize=7, label=lab, zorder=3)
        rs = reshuffled(d, 2)
        if rs:
            ax.plot([r["replay_pct"] for r in rs], [fn(r) for r in rs], "D", markersize=9, markerfacecolor="none",
                    markeredgecolor=ORANGE, markeredgewidth=2, label="epoch 2, same mix reshuffled", zorder=4)
        for r in e2:
            v = fn(r)
            fmt = "{:.3f}" if key == "kld" else "{:.1f}"
            ax.annotate(fmt.format(v), (r["replay_pct"], v), textcoords="offset points", xytext=(0, 10),
                        ha="center", fontsize=11.5, fontweight="bold", color=MIX_COLOUR.get(r["replay_pct"], INK))
        if key != "kld":
            bv = fn(base)
            ax.axhline(bv, color=BLUE, linewidth=1.4, linestyle=":")
            ax.text(xs[-1], bv, f" base {bv:.1f}", va="bottom", ha="right", fontsize=11, color=BLUE)
        else:
            ax.axhline(0, color=BLUE, linewidth=1.4, linestyle=":")
            ax.text(xs[-1], 0, " base 0", va="bottom", ha="right", fontsize=11, color=BLUE)
        lo, hi = ax.get_ylim()
        ax.set_ylim(min(lo, 0) if key == "kld" else lo, hi + (hi - lo) * 0.12)
        ax.set_xticks(xs, [f"{x}%" for x in xs])
        ax.set_xlabel("share of the 400 KB that is general replay")
        ax.set_title(title + "\n", loc="left")
        ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=11.5, color=MUTED)
        tidy(ax)
    axes.flat[0].legend(frameon=False, fontsize=11, loc="upper left")
    fig.subplots_adjust(left=0.06, right=0.98, top=0.92, bottom=0.07, hspace=0.42, wspace=0.18)
    save(fig, "fine-tuning-replay-mix-tradeoff.webp", OUT_POSTS, (1400, 1000))


def terminal(d, work):
    F_MONO = "/System/Library/Fonts/Menlo.ttc"
    F_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
    BG, PANEL, BORDER = (13, 17, 23), (22, 27, 34), (48, 54, 61)
    FG, MUT, BL, GR, RD = (230, 237, 243), (139, 148, 158), (88, 166, 255), (63, 185, 80), (248, 81, 73)
    keep = ("Mean PPL(Q)", "Mean PPL(base)", "Mean    KLD", "99.0%   KLD", "Median  KLD", "Same top p")
    e2 = by_epoch(d, 2)
    hi = max(e2, key=lambda r: r["replay_pct"])
    lo = min(e2, key=lambda r: r["replay_pct"])
    lines = []
    for r, col in ((lo, RD), (hi, GR)):
        lines.append((f"$ llama-perplexity -m {r['tag']}.gguf -f general_wiki.txt -c 512 \\", BL))
        lines.append(("    --kl-divergence-base base_general.kld --kl-divergence", BL))
        with open(os.path.join(work, "logs", f"{r['tag']}.general.log"), encoding="utf-8", errors="replace") as fh:
            for ln in fh.read().splitlines():
                if ln.startswith(keep):
                    lines.append(("  " + ln.rstrip(), col if ln.startswith(("Mean    KLD", "Same top p")) else FG))
        lines.append(("", FG))
    lines.pop()
    mono = ImageFont.truetype(F_MONO, 21)
    line_h, top, width = 31, 64, 1400
    height = top + 30 + line_h * len(lines) + 24
    img = Image.new("RGB", (width, height), BG)
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle((12, 12, width - 12, height - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    for i, c in enumerate(((248, 81, 73), (240, 136, 62), (63, 185, 80))):
        dr.ellipse((34 + i * 26, 30, 48 + i * 26, 44), fill=c)
    tf = ImageFont.truetype(F_REG, 18)
    title = f"llama-perplexity --kl-divergence: {lo['replay_pct']}% vs {hi['replay_pct']}% replay, epoch 2, on general text"
    dr.text((width / 2 - dr.textlength(title, font=tf) / 2, 26), title, font=tf, fill=MUT)
    y = top + 20
    for text, c in lines:
        if dr.textlength(text, font=mono) > width - 72:
            raise SystemExit("terminal line too wide: %r" % text)
        dr.text((36, y), text, font=mono, fill=c)
        y += line_h
    path = os.path.join(OUT_POSTS, "fine-tuning-replay-kl-terminal.webp")
    img.save(path, "WEBP", quality=90, method=6)
    print("wrote", os.path.relpath(path, ROOT), img.size)


def lr_control(d):
    """Replay share against learning rate: the two knobs side by side, epoch 2."""
    base = d["runs"][0]
    rows = [r for r in d["runs"] if r["epoch"] == 2 and not r.get("order_seed")]
    rows.sort(key=lambda r: (-float(r["lr"]), r["replay_pct"]))
    lab = [f"{r['lr']}\n{r['replay_pct']}%" for r in rows]
    col = [MIX_COLOUR.get(r["replay_pct"], INK) if r["lr"] == MAIN_LR else BLUE for r in rows]
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(14, 6.4))
    specs = [
        (a1, lambda r: r["general"]["kld_mean"], "Drift on general English", "mean KL divergence to base (nats/token)", "{:.3f}", None),
        (a2, lambda r: r["ppl_heldout"]["ppl"], "Held-out blog posts", "perplexity, lower is better", "{:.1f}", base["ppl_heldout"]["ppl"]),
        (a3, lambda r: r["ppl_seen"]["ppl"], "Blog text it trained on", "perplexity, lower is better", "{:.1f}", base["ppl_seen"]["ppl"]),
    ]
    for ax, fn, title, sub, fmt, bv in specs:
        vals = [fn(r) for r in rows]
        ax.bar(range(len(rows)), vals, color=col, width=0.7)
        for i, v in enumerate(vals):
            ax.text(i, v + max(vals) * 0.02, fmt.format(v), ha="center", fontsize=11, fontweight="bold", color=INK)
        if bv is not None:
            ax.axhline(bv, color=GREY, linestyle=":", linewidth=1.5)
            ax.text(len(rows) - 0.5, bv, f"base {bv:.1f}", ha="right", va="bottom", fontsize=10.5, color=MUTED)
        ax.set_ylim(0, max(vals + [bv or 0]) * 1.15)
        ax.set_xticks(range(len(rows)), lab, fontsize=10.5)
        ax.set_title(title + "\n", loc="left")
        ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=11, color=MUTED)
        tidy(ax)
    fig.text(0.5, 0.025, "each bar: learning rate (top line) and replay share (bottom line), after epoch 2; "
             "blue bars are lr 1e-6", ha="center", fontsize=11.5, color=MUTED)
    fig.subplots_adjust(left=0.04, right=0.99, top=0.86, bottom=0.16, wspace=0.16)
    save(fig, "fine-tuning-replay-vs-learning-rate.webp", OUT_POSTS, (1400, 640))


def hero(d):
    e2 = by_epoch(d, 2)
    base = d["runs"][0]
    bg, fg, dim = "#0d1117", "#e6edf3", "#8b949e"
    cols = {0: "#f85149", 10: "#f0883e", 25: "#a371f7", 50: "#3fb950"}
    fig = plt.figure(figsize=(16, 8.4))
    fig.patch.set_facecolor(bg)
    fig.text(0.05, 0.87, "Replay data vs forgetting, measured", fontsize=48, fontweight="bold", color=fg, va="center")
    fig.text(0.05, 0.775, "SmolLM2-135M fine-tuned on this blog with llama.cpp, 0 to 50% general text mixed in",
             fontsize=22, color=dim, va="center")
    metrics = [
        ("held-out posts PPL", lambda r: r["ppl_heldout"]["ppl"], "{:.1f}", True),
        ("general-text KL drift", lambda r: r["general"]["kld_mean"], "{:.2f}", False),
        ("HellaSwag acc %", lambda r: r["hellaswag"]["acc"], "{:.1f}", True),
    ]
    for j, (name, fn, fmt, has_base) in enumerate(metrics):
        ax = fig.add_axes([0.05 + j * 0.315, 0.13, 0.26, 0.47])
        ax.set_facecolor(bg)
        rows = ([("base", base, "#6e7681")] if has_base else []) + [(f"{r['replay_pct']}%", r, cols[r["replay_pct"]]) for r in e2]
        vals = [fn(r) for _, r, _ in rows]
        ax.bar(range(len(rows)), vals, color=[c for *_, c in rows], width=0.72)
        for i, v in enumerate(vals):
            ax.text(i, v + max(vals) * 0.03, fmt.format(v), ha="center", fontsize=16, color=fg, fontweight="bold")
        ax.set_ylim(0, max(vals) * 1.22)
        ax.set_xticks(range(len(rows)), [n for n, *_ in rows], color=dim, fontsize=15)
        ax.tick_params(axis="x", length=0)
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_title(name, fontsize=19, color=fg, pad=10)
    fig.text(0.05, 0.045, "bars: base model, then replay share after 2 epochs at lr 1e-5", fontsize=16, color=dim, va="center")
    fig.text(0.95, 0.045, "lower PPL and KL are better", fontsize=16, color=dim, va="center", ha="right")
    save(fig, "fine-tuning-replay-mix-forgetting.webp", OUT_HEAD, (1600, 840))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    with open(DATA, encoding="utf-8") as fh:
        d = json.load(fh)
    hero(d)
    mix_layout(d)
    tradeoff(d)
    terminal(d, a.work)
    if any(r["lr"] not in (None, MAIN_LR) for r in d["runs"]):
        lr_control(d)


if __name__ == "__main__":
    main()
