#!/usr/bin/env python3
"""Build the webp images for the continuous batching post.

Reads the measured numbers from scripts/data/continuous-batching-llama-cpp-m2pro.json
(written by scripts/summarise_continuous_batching_runs.py from three runs each of
llama-batched-bench and of scripts/llama_server_loadgen.py against llama-server) and
draws every chart from medians of those runs; nothing is typed in by hand.

Outputs:
  assets/img/headers/performance/continuous-batching-llm-serving-llama-cpp-measured.webp  (1600x840, 40:21)
  assets/img/posts/performance/continuous-batching-decode-sweep.webp
  assets/img/posts/performance/continuous-batching-static-vs-continuous-timeline.webp
  assets/img/posts/performance/continuous-batching-scheduler-latency-throughput.webp
"""
import io
import json
import os
import statistics as st

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "scripts", "data", "continuous-batching-llama-cpp-m2pro.json")
OUT_HEAD = os.path.join(ROOT, "assets", "img", "headers", "performance")
OUT_POSTS = os.path.join(ROOT, "assets", "img", "posts", "performance")
SLUG = "continuous-batching-llm-serving-llama-cpp-measured"

INK = "#1f2328"
MUTED = "#57606a"
GRID = "#d0d7de"
BLUE = "#0969da"
ORANGE = "#d1601f"
GREEN = "#1a7f37"
PURPLE = "#8250df"
GREY = "#8c959f"

LABELS = {
    "serial": "serial\n1 slot",
    "static8": "static\n8 slots",
    "cont8": "cont.\n8 slots",
    "cont8b64": "cont. 8\n-ub 64",
    "cont16": "cont.\n16 slots",
    "cont16kvu": "cont. 16\n-kvu",
}
ORDER = ["serial", "static8", "cont8", "cont8b64", "cont16", "cont16kvu"]

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 13,
    "axes.edgecolor": GRID,
    "axes.labelcolor": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.titleweight": "bold",
    "axes.titlesize": 15,
    "axes.titlecolor": INK,
})


def load():
    with open(DATA) as f:
        return json.load(f)


def save(fig, path, size=None, quality=88):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    im = Image.open(buf).convert("RGB")
    if size and im.size != size:
        raise SystemExit(f"{path}: rendered {im.size}, expected {size}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path, "WEBP", quality=quality, method=6)
    print("wrote", os.path.relpath(path, ROOT), im.size)


def bench_medians(d):
    by_pl = {}
    for run in d["bench"]:
        for row in run:
            by_pl.setdefault(row["pl"], []).append(row)
    out = []
    for pl in sorted(by_pl):
        rows = by_pl[pl]
        tg = [r["speed_tg"] for r in rows]
        out.append({"pl": pl, "tg": st.median(tg), "tg_runs": tg, "per_seq": st.median(tg) / pl,
                    "step_ms": 1000 * st.median([r["t_tg"] for r in rows]) / rows[0]["tg"]})
    return out


def load_medians(d):
    out = {}
    for name, cfg in d["load"].items():
        keys = [k for k, v in cfg["runs"][0].items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        out[name] = {k: st.median([r[k] for r in cfg["runs"]]) for k in keys}
        out[name]["n_runs"] = len(cfg["runs"])
        out[name]["gap_q"] = {q: st.median([r["gap_quantiles_ms"][q] for r in cfg["runs"]])
                              for q in cfg["runs"][0]["gap_quantiles_ms"]}
    return out


def decode_sweep(d):
    b = bench_medians(d)
    pls = [r["pl"] for r in b]
    xs = list(range(len(pls)))
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8.4), sharex=True,
                                   gridspec_kw={"height_ratios": [1.15, 1], "hspace": 0.12})
    fig.patch.set_facecolor("white")
    ax1.bar(xs, [r["tg"] for r in b], color=BLUE, width=0.62, zorder=2)
    for x, r in zip(xs, b):
        ax1.scatter([x] * len(r["tg_runs"]), r["tg_runs"], s=14, color=INK, zorder=3)
        ax1.text(x, r["tg"] + 12, f"{r['tg']:.0f}", ha="center", va="bottom", fontsize=13, color=INK, fontweight="bold")
    ax1.set_ylabel("aggregate decode tokens/s")
    ax1.set_ylim(0, max(r["tg"] for r in b) * 1.18)
    ax1.set_title("llama-batched-bench: more sequences per step, more tokens per second in total", loc="left")
    ax1.grid(axis="y", color=GRID, zorder=0)

    ax2.plot(xs, [r["per_seq"] for r in b], color=ORANGE, marker="o", lw=2.5, zorder=3, label="tokens/s each sequence sees")
    for x, r in zip(xs, b):
        ax2.text(x - 0.1, r["per_seq"] + 2, f"{r['per_seq']:.0f}", ha="right", va="bottom", fontsize=12, color=ORANGE)
    ax2.set_ylabel("tokens/s per sequence", color=ORANGE)
    ax2.set_ylim(0, max(r["per_seq"] for r in b) * 1.25)
    ax2.grid(axis="y", color=GRID, zorder=0)
    ax3 = ax2.twinx()
    ax3.plot(xs, [r["step_ms"] for r in b], color=PURPLE, marker="s", lw=2, ls="--", zorder=3, label="decode step time (ms)")
    for x, r in zip(xs, b):
        ax3.text(x + 0.08, r["step_ms"], f"{r['step_ms']:.0f} ms", ha="left", va="top", fontsize=11, color=PURPLE)
    ax3.set_ylabel("ms per decode step", color=PURPLE)
    ax3.set_ylim(0, max(r["step_ms"] for r in b) * 1.2)
    for s in ("top",):
        ax3.spines[s].set_visible(False)
    ax2.set_xticks(xs, [str(p) for p in pls])
    ax2.set_xlabel("sequences decoded together (-npl); prompt 256, generate 128; bars = median of 3 runs, dots = each run")
    h1, l1 = ax2.get_legend_handles_labels()
    h2, l2 = ax3.get_legend_handles_labels()
    ax2.legend(h1 + h2, l1 + l2, loc="upper center", frameon=False, fontsize=12, ncol=2)
    for ax in (ax1, ax2):
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.text(0.01, 0.005, "SmolLM3-arch 3.1B Q4_K_M GGUF, llama.cpp b11669, Apple M2 Pro (Metal), flash attention, unified KV",
             fontsize=10.5, color=MUTED)
    fig.subplots_adjust(left=0.08, right=0.92, top=0.94, bottom=0.1)
    save(fig, os.path.join(OUT_POSTS, "continuous-batching-decode-sweep.webp"), (1200, 840))


def timeline(d):
    fig, axes = plt.subplots(1, 2, figsize=(12, 8), sharey=True, gridspec_kw={"wspace": 0.06})
    fig.patch.set_facecolor("white")
    m = load_medians(d)
    end = max(max(r[2] for r in d["load"][n]["timeline_run1"]) for n in ("static8", "cont8"))
    for ax, name, title in zip(axes, ("static8", "cont8"),
                               ("static batching (-nocb), 8 slots", "continuous batching, 8 slots")):
        rows = d["load"][name]["timeline_run1"]
        for i, (arrive, first, done, n) in enumerate(rows):
            ax.barh(i, first - arrive, left=arrive, height=0.8, color="#f5c26b", zorder=2)
            ax.barh(i, done - first, left=first, height=0.8, color=BLUE if name == "cont8" else ORANGE, zorder=2)
        ax.set_xlim(0, end * 1.02)
        ax.set_ylim(len(rows) - 0.4, -0.6)
        ax.set_title(title, loc="left")
        ax.set_xlabel("seconds since the first request")
        ax.grid(axis="x", color=GRID, zorder=0)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        mm = m[name]
        ax.text(0.98, 0.03,
                f"median of 3 runs\nTTFT p50 {mm['ttft_p50_s']:.1f} s, p95 {mm['ttft_p95_s']:.1f} s\n"
                f"all 48 done after {mm['makespan_s']:.0f} s\n{mm['throughput_tok_s']:.0f} tokens/s",
                transform=ax.transAxes, ha="right", va="bottom", fontsize=12.5, color=INK,
                bbox={"facecolor": "white", "edgecolor": GRID, "boxstyle": "round,pad=0.4"})
    axes[0].set_ylabel("request (arrival order), 48 requests over 36 s")
    fig.legend(handles=[Patch(color="#f5c26b", label="waiting for a slot / prefill (until first token)"),
                        Patch(color=ORANGE, label="streaming tokens (static)"),
                        Patch(color=BLUE, label="streaming tokens (continuous)")],
               loc="lower center", ncol=3, frameon=False, fontsize=12)
    fig.suptitle("Same 48 requests, same model, same 8 slots: only the scheduler changes (run 1 of 3)",
                 x=0.01, ha="left", fontsize=15, fontweight="bold", color=INK)
    fig.subplots_adjust(left=0.07, right=0.99, top=0.9, bottom=0.14)
    save(fig, os.path.join(OUT_POSTS, "continuous-batching-static-vs-continuous-timeline.webp"), (1200, 800))


def scheduler_bars(d):
    m = load_medians(d)
    names = [n for n in ORDER if n in m]
    xs = list(range(len(names)))
    colors = [GREY if n == "serial" else ORANGE if n == "static8" else BLUE for n in names]
    fig, axes = plt.subplots(2, 2, figsize=(12, 9), gridspec_kw={"hspace": 0.55, "wspace": 0.22})
    fig.patch.set_facecolor("white")
    panels = [
        (axes[0][0], "ttft_p95_s", "time to first token, p95 (s)", "{:.1f}", True),
        (axes[0][1], "throughput_tok_s", "throughput (tokens/s)", "{:.0f}", False),
        (axes[1][0], "tpot_p50_ms", "time per output token, p50 (ms)", "{:.0f}", True),
        (axes[1][1], "gap_p99_ms", "inter-token gap, p99 (ms)", "{:.0f}", True),
    ]
    for ax, key, title, fmt, lower_better in panels:
        vals = [m[n][key] for n in names]
        ax.bar(xs, vals, color=colors, width=0.66, zorder=2)
        for x, v in zip(xs, vals):
            ax.text(x, v, fmt.format(v), ha="center", va="bottom", fontsize=12, color=INK, fontweight="bold")
        ax.set_title(title + (", lower is better" if lower_better else ", higher is better"), loc="left", fontsize=13.5)
        ax.set_xticks(xs, [LABELS[n] for n in names], fontsize=9.5)
        ax.set_ylim(0, max(vals) * 1.2)
        ax.grid(axis="y", color=GRID, zorder=0)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.suptitle("llama-server under one open-loop load: 48 requests, 63-204 token prompts, 32-512 token outputs",
                 x=0.01, ha="left", fontsize=15, fontweight="bold", color=INK)
    fig.text(0.01, 0.005, "Each bar is the median of 3 runs. 3.1B Q4_K_M GGUF on an Apple M2 Pro, llama.cpp b11669, 16k context, flash attention.",
             fontsize=10.5, color=MUTED)
    fig.subplots_adjust(left=0.06, right=0.99, top=0.91, bottom=0.1)
    save(fig, os.path.join(OUT_POSTS, "continuous-batching-scheduler-latency-throughput.webp"), (1200, 900))


def hero(d):
    """1600x840 (40:21) header: Chirpy crops anything else."""
    m = load_medians(d)
    b = {r["pl"]: r for r in bench_medians(d)}
    bg = "#0d1117"
    fg = "#e6edf3"
    dim = "#8b949e"
    fig = plt.figure(figsize=(16, 8.4))
    fig.patch.set_facecolor(bg)
    fig.text(0.05, 0.86, "Continuous batching, measured", fontsize=50, fontweight="bold", color=fg, va="center")
    fig.text(0.05, 0.765, "llama.cpp on an Apple M2 Pro: 3 runs each, medians", fontsize=25, color=dim, va="center")

    ax = fig.add_axes([0.21, 0.13, 0.30, 0.5])
    ax.set_facecolor(bg)
    names = ["serial", "static8", "cont8", "cont16kvu"]
    vals = [m[n]["ttft_p95_s"] for n in names]
    cols = ["#6e7681", "#f0883e", "#58a6ff", "#58a6ff"]
    ax.barh(range(len(names)), vals, color=cols, height=0.62)
    for i, v in enumerate(vals):
        ax.text(v + max(vals) * 0.02, i, f"{v:.1f} s", va="center", fontsize=21, color=fg, fontweight="bold")
    ax.set_yticks(range(len(names)), ["serial", "static, 8", "continuous, 8", "continuous, 16 -kvu"], fontsize=19, color=fg)
    ax.invert_yaxis()
    ax.set_xlim(0, max(vals) * 1.32)
    ax.set_xticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    ax.set_title("time to first token, p95", loc="left", fontsize=21, color=dim, pad=12, x=-0.5)

    ax2 = fig.add_axes([0.6, 0.13, 0.35, 0.5])
    ax2.set_facecolor(bg)
    pls = [1, 8, 32, 64]
    tv = [b[p]["tg"] for p in pls]
    ax2.bar(range(len(pls)), tv, color="#3fb950", width=0.6)
    for i, v in enumerate(tv):
        ax2.text(i, v + max(tv) * 0.03, f"{v:.0f}", ha="center", fontsize=21, color=fg, fontweight="bold")
    ax2.set_xticks(range(len(pls)), [f"batch {p}" for p in pls], fontsize=18, color=fg)
    ax2.set_yticks([])
    ax2.set_ylim(0, max(tv) * 1.25)
    for s in ax2.spines.values():
        s.set_visible(False)
    ax2.tick_params(length=0)
    ax2.set_title("decode tokens/s, all sequences", loc="left", fontsize=21, color=dim, pad=12)
    save(fig, os.path.join(OUT_HEAD, SLUG + ".webp"), (1600, 840), quality=90)


if __name__ == "__main__":
    data = load()
    decode_sweep(data)
    timeline(data)
    scheduler_bars(data)
    hero(data)
