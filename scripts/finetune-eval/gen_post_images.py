#!/usr/bin/env python3
"""Draw the webp images for the "fine-tuning evaluation, measured" post.

    python3 scripts/finetune-eval/gen_post_images.py --work <sweep work dir>

Every number comes from scripts/data/finetune-eval-smollm2-135m.json (written by
scripts/finetune-eval/summarise.py from the llama-finetune / llama-perplexity logs), and the terminal
image prints lines copied from <work>/logs/*.general.log; nothing is typed in by hand.

Outputs:
  assets/img/headers/ai/fine-tuning-evaluation-measured.webp             (1600x840, 40:21)
  assets/img/posts/ai/fine-tuning-eval-three-perplexities.webp           (1400x760)
  assets/img/posts/ai/fine-tuning-eval-forgetting-benchmarks.webp        (1400x700)
  assets/img/posts/ai/fine-tuning-eval-kl-divergence-terminal.webp       (1400x?)
  assets/img/posts/ai/fine-tuning-eval-training-loss.webp                (1400x620)
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
DATA = os.path.join(ROOT, "scripts", "data", "finetune-eval-smollm2-135m.json")
OUT_HEAD = os.path.join(ROOT, "assets", "img", "headers", "ai")
OUT_POSTS = os.path.join(ROOT, "assets", "img", "posts", "ai")

INK, MUTED, GRID = "#1f2328", "#57606a", "#d0d7de"
BLUE, ORANGE, GREEN, PURPLE, GREY, RED = "#0969da", "#d1601f", "#1a7f37", "#8250df", "#8c959f", "#cf222e"
LR_COLOUR = {"1e-6": GREEN, "3e-6": BLUE, "1e-5": RED}

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


def label(r, short=False):
    if r["tag"] == "base":
        return "base"
    return f"{r['lr']}\nep {r['epoch']}"


def tidy(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def colour(r):
    return GREY if r["tag"] == "base" else LR_COLOUR.get(r["lr"], PURPLE)


def three_perplexities(d):
    runs = d["runs"]
    fig, axes = plt.subplots(1, 3, figsize=(14, 7.6), sharey=False)
    specs = [
        ("ppl_seen", "Text it trained on", "100 KB of the training posts"),
        ("ppl_heldout", "Held-out posts", f"{d['corpora']['posts_heldout']} posts it never saw"),
        ("general", "General English", "240 Wikipedia paragraphs (XQuAD)"),
    ]
    for ax, (key, title, sub) in zip(axes, specs):
        vals = [r[key]["ppl"] for r in runs]
        errs = [r[key]["pm"] for r in runs]
        x = range(len(runs))
        ax.bar(x, vals, yerr=errs, color=[colour(r) for r in runs], width=0.7, capsize=3, ecolor=INK)
        base = runs[0][key]["ppl"]
        ax.axhline(base, color=GREY, linestyle="--", linewidth=1)
        for i, v in enumerate(vals):
            ax.text(i, v + max(vals) * 0.025, f"{v:.1f}", ha="center", fontsize=11.5, color=INK, fontweight="bold")
        ax.set_xticks(list(x), [label(r) for r in runs], fontsize=9.5)
        ax.set_ylim(0, max(vals) * 1.15)
        ax.set_title(f"{title}\n", loc="left")
        ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=11.5, color=MUTED)
        tidy(ax)
    axes[0].set_ylabel("perplexity (lower is better)")
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(color=GREY, label="base")] + [Patch(color=c, label=f"lr {k}") for k, c in LR_COLOUR.items()],
               loc="upper right", ncol=4, frameon=False, fontsize=11.5)
    fig.text(0.01, 0.012, "SmolLM2-135M-Instruct, full fine-tune with llama-finetune on this blog's posts; "
             "llama-perplexity ctx 512; error bars = ± reported by llama-perplexity; dashed = base",
             fontsize=10.5, color=MUTED)
    fig.subplots_adjust(left=0.06, right=0.99, top=0.88, bottom=0.17, wspace=0.22)
    save(fig, "fine-tuning-eval-three-perplexities.webp", OUT_POSTS, (1400, 760))


def forgetting_benchmarks(d):
    runs = d["runs"]
    tuned = runs[1:]
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(14, 7.0))
    x = range(len(tuned))
    kl = [r["general"]["kld_mean"] for r in tuned]
    a1.bar(x, kl, color=[colour(r) for r in tuned], width=0.7)
    for i, v in enumerate(kl):
        a1.text(i, v + max(kl) * 0.025, f"{v:.3f}", ha="center", fontsize=11.5, fontweight="bold", color=INK)
    a1.set_xticks(list(x), [label(r) for r in tuned], fontsize=9.5)
    a1.set_ylim(0, max(kl) * 1.15)
    a1.set_title("Drift from base on general text\n", loc="left")
    a1.text(0, 1.02, "mean KL divergence per token (nats)", transform=a1.transAxes, fontsize=11.5, color=MUTED)
    tidy(a1)

    same = [r["general"]["same_top_p"] for r in tuned]
    a2.bar(x, same, color=[colour(r) for r in tuned], width=0.7)
    for i, v in enumerate(same):
        a2.text(i, v + 1.5, f"{v:.1f}%", ha="center", fontsize=11.5, fontweight="bold", color=INK)
    a2.set_xticks(list(x), [label(r) for r in tuned], fontsize=9.5)
    a2.set_ylim(0, 105)
    a2.set_title("Same next-token pick as base\n", loc="left")
    a2.text(0, 1.02, "share of general-text tokens, top-1 agreement", transform=a2.transAxes, fontsize=11.5, color=MUTED)
    tidy(a2)

    xa = range(len(runs))
    hs = [r["hellaswag"]["acc"] for r in runs]
    hs_err = [[r["hellaswag"]["acc"] - r["hellaswag"]["lo"] for r in runs],
              [r["hellaswag"]["hi"] - r["hellaswag"]["acc"] for r in runs]]
    wg = [r["winogrande"]["acc"] for r in runs]
    wg_err = [r["winogrande"]["pm"] for r in runs]
    off = 0.2
    a3.errorbar([i - off for i in xa], hs, yerr=hs_err, fmt="o", color=ORANGE, capsize=4, label="HellaSwag (1000 tasks)")
    a3.errorbar([i + off for i in xa], wg, yerr=wg_err, fmt="s", color=PURPLE, capsize=4, label="Winogrande (1266 tasks)")
    a3.axhline(25, color=ORANGE, linestyle=":", linewidth=1)
    a3.axhline(50, color=PURPLE, linestyle=":", linewidth=1)
    a3.set_xticks(list(xa), [label(r, short=True) for r in runs], fontsize=9.5)
    a3.set_ylim(20, 62)
    a3.set_ylabel("accuracy %")
    a3.set_title("General benchmarks\n", loc="left")
    a3.text(0, 1.02, "dotted = chance level; whiskers as printed", transform=a3.transAxes, fontsize=11.5, color=MUTED)
    a3.legend(loc="lower left", frameon=False, fontsize=10.5)
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(color=c, label=f"lr {k}") for k, c in LR_COLOUR.items()],
               loc="upper right", ncol=3, frameon=False, fontsize=11.5)
    tidy(a3)
    fig.text(0.01, 0.012, "Same checkpoints as the perplexity chart. KL and top-1 agreement from "
             "llama-perplexity --kl-divergence against the base model's saved logits.", fontsize=10.5, color=MUTED)
    fig.subplots_adjust(left=0.05, right=0.99, top=0.87, bottom=0.17, wspace=0.25)
    save(fig, "fine-tuning-eval-forgetting-benchmarks.webp", OUT_POSTS, (1400, 700))


def training_loss(d):
    fig, ax = plt.subplots(figsize=(14, 6.2))
    n = None
    for r in d["runs"][1:]:
        pts = r["training"]["running_loss"]
        n = pts[-1][0]
        x0 = (r["epoch"] - 1) * n
        lab = None
        if r["epoch"] == max(q["epoch"] for q in d["runs"] if q["lr"] == r["lr"]):
            lab = (f"lr {r['lr']}: epoch {r['epoch']} ends at train {pts[-1][1]:.2f}, "
                   f"val {r['training']['val']['loss']:.2f}")
        ax.plot([x0 + p[0] for p in pts], [p[1] for p in pts], color=colour(r), linewidth=2.4, label=lab)
    ax.axvline(n, color=GREY, linestyle=":", linewidth=1.2)
    ax.text(n + 8, ax.get_ylim()[1], "epoch 2 starts", va="top", fontsize=11, color=MUTED)
    ax.set_xlabel("training chunk (256 tokens, stride 128), epochs 1 and 2")
    ax.set_ylabel("running mean train loss")
    ax.set_title("What llama-finetune prints while it trains\n", loc="left")
    ax.text(0, 1.02, "running mean of the epoch's loss, reset each epoch; val = the last 5% of the training file",
            transform=ax.transAxes, fontsize=11.5, color=MUTED)
    ax.legend(frameon=False, loc="lower left", fontsize=11.5)
    tidy(ax)
    fig.subplots_adjust(left=0.07, right=0.99, top=0.86, bottom=0.12)
    save(fig, "fine-tuning-eval-training-loss.webp", OUT_POSTS, (1400, 620))


def terminal(d, work):
    F_MONO = "/System/Library/Fonts/Menlo.ttc"
    F_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
    BG, PANEL, BORDER = (13, 17, 23), (22, 27, 34), (48, 54, 61)
    FG, MUT, BL, GR, RD, YE = (230, 237, 243), (139, 148, 158), (88, 166, 255), (63, 185, 80), (248, 81, 73), (210, 153, 34)
    keep = ("Mean PPL(Q)", "Mean PPL(base)", "Mean    KLD", "99.0%   KLD", "Median  KLD", "Same top p")
    good = max((r for r in d["runs"][1:]), key=lambda r: -r["ppl_heldout"]["ppl"])
    bad = max((r for r in d["runs"][1:]), key=lambda r: r["general"]["kld_mean"])
    lines = []
    for r, col in ((good, GR), (bad, RD)):
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
    title = "llama-perplexity --kl-divergence: two fine-tunes vs the base model on general text"
    dr.text((width / 2 - dr.textlength(title, font=tf) / 2, 26), title, font=tf, fill=MUT)
    y = top + 20
    for text, c in lines:
        if dr.textlength(text, font=mono) > width - 72:
            raise SystemExit("terminal line too wide: %r" % text)
        dr.text((36, y), text, font=mono, fill=c)
        y += line_h
    path = os.path.join(OUT_POSTS, "fine-tuning-eval-kl-divergence-terminal.webp")
    img.save(path, "WEBP", quality=90, method=6)
    print("wrote", os.path.relpath(path, ROOT), img.size)


def hero(d):
    runs = {r["tag"]: r for r in d["runs"]}
    base = runs["base"]
    good = min(d["runs"][1:], key=lambda r: r["ppl_heldout"]["ppl"])
    bad = max(d["runs"][1:], key=lambda r: r["general"]["kld_mean"])
    bg, fg, dim = "#0d1117", "#e6edf3", "#8b949e"
    fig = plt.figure(figsize=(16, 8.4))
    fig.patch.set_facecolor(bg)
    fig.text(0.05, 0.87, "Fine-tuning evaluation, measured", fontsize=50, fontweight="bold", color=fg, va="center")
    fig.text(0.05, 0.775, "SmolLM2-135M tuned on this blog with llama.cpp: one model, four scorecards",
             fontsize=24, color=dim, va="center")
    metrics = [
        ("trained-on text PPL", "ppl_seen", lambda r: r["ppl_seen"]["ppl"], "{:.1f}"),
        ("held-out posts PPL", "ppl_heldout", lambda r: r["ppl_heldout"]["ppl"], "{:.1f}"),
        ("general text PPL", "general", lambda r: r["general"]["ppl"], "{:.1f}"),
        ("HellaSwag acc %", "hs", lambda r: r["hellaswag"]["acc"], "{:.1f}"),
    ]
    cols = [("base", base, "#6e7681"), (f"lr {good['lr']}, ep {good['epoch']}", good, "#3fb950"),
            (f"lr {bad['lr']}, ep {bad['epoch']}", bad, "#f85149")]
    for j, (name, key, fn, fmt) in enumerate(metrics):
        ax = fig.add_axes([0.05 + j * 0.235, 0.1, 0.19, 0.5])
        ax.set_facecolor(bg)
        vals = [fn(r) for _, r, _ in cols]
        ax.bar(range(3), vals, color=[c for *_, c in cols], width=0.7)
        for i, v in enumerate(vals):
            ax.text(i, v + max(vals) * 0.03, fmt.format(v), ha="center", fontsize=19, color=fg, fontweight="bold")
        ax.set_ylim(0, max(vals) * 1.22)
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_title(name, fontsize=19, color=fg, pad=10)
    for i, (nm, _, c) in enumerate(cols):
        fig.text(0.05 + i * 0.2, 0.045, "■ " + nm, fontsize=18, color=c, va="center")
    fig.text(0.95, 0.045, "lower PPL is better", fontsize=16, color=dim, va="center", ha="right")
    save(fig, "fine-tuning-evaluation-measured.webp", OUT_HEAD, (1600, 840))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    with open(DATA, encoding="utf-8") as fh:
        d = json.load(fh)
    hero(d)
    three_perplexities(d)
    forgetting_benchmarks(d)
    training_loss(d)
    terminal(d, a.work)


if __name__ == "__main__":
    main()
