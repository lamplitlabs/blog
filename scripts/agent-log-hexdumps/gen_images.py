#!/usr/bin/env python3
"""Build the webp images for the "secrets in agent-log hexdumps" post.

Usage:
  python3 scripts/agent-log-hexdumps/gen_images.py --work <scratch-dir>

Reads scripts/data/agent-log-hexdumps.json and <scratch-dir>/capture/example.json,
both written by scripts/agent-log-hexdumps/bench.py with the same --work. Every
number and every terminal line comes from those files. The fake token in the
example is masked after its first 8 characters before it is drawn.

Outputs:
  assets/img/headers/ai/ai-security-agent-log-hexdump-secrets-measured.webp  (1600x840, 40:21)
  assets/img/posts/ai/agent-log-hexdumps-xxd-gitleaks-terminal.webp
  assets/img/posts/ai/agent-log-hexdumps-defence-matrix.webp
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gen_agent_log_secrets_post_images as g  # noqa: E402
from gen_agent_log_secrets_post_images import plt, pct, save_fig, LinearSegmentedColormap  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "scripts", "data", "agent-log-hexdumps.json")
OUT_HEAD = os.path.join(ROOT, "assets", "img", "headers", "ai")
OUT_POSTS = os.path.join(ROOT, "assets", "img", "posts", "ai")

MATRIX_COLS = [
    ("gitleaks_stored", "gitleaks,\ndefault rules,\nstored JSONL"),
    ("gitleaks_view_tuned", "gitleaks,\ntuned config,\ndecoded view"),
    ("redact", "Encoding-aware\nknown-value\nredaction"),
    ("undump_scan", "Undump, then\ngitleaks\n(tuned)"),
    ("undump_redact", "Undump, then\nknown-value\nredaction"),
]


def header(d):
    n = d["dump_events"]
    tot = d["totals_dump_formats"]
    fig = plt.figure(figsize=(16, 8.4), dpi=100)
    fig.patch.set_facecolor("#0d1117")
    fig.text(0.05, 0.885, "Secrets in agent-log hexdumps, measured", color="#e6edf3", fontsize=40, weight="bold")
    fig.text(0.05, 0.815, "%d fake secrets, one .env each, dumped by %d real commands (xxd, hexdump, od) into agent logs" % (
        n, len(d["formats"]) - 2), color="#8b949e", fontsize=20)
    ax = fig.add_axes([0.36, 0.17, 0.58, 0.58])
    ax.set_facecolor("#0d1117")
    keys = ["gitleaks_stored", "gitleaks_view_tuned", "redact", "undump_scan", "undump_redact"]
    labels = ["gitleaks, stored log", "gitleaks, tuned, decoded", "Encoding-aware redaction",
              "Undump + gitleaks", "Undump + redaction"]
    colours = ["#f85149", "#f0883e", "#d29922", "#58a6ff", "#3fb950"]
    vals = [tot[k] for k in keys]
    ys = list(range(len(vals)))[::-1]
    ax.barh(ys, [max(pct(v, n), 0.4) for v in vals], color=colours, height=0.62)
    for y, v in zip(ys, vals):
        ax.text(pct(v, n) + 1.2, y, "%d%%  (%d/%d)" % (round(pct(v, n)), v, n), va="center", color="#e6edf3",
                fontsize=19, weight="bold")
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, color="#e6edf3", fontsize=19)
    ax.set_xlim(0, 125)
    ax.set_xticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(axis="y", length=0, pad=14)
    fig.text(0.05, 0.075, "Secrets the stored log no longer gives back, or that the scan flagged. Undump = parse the dump "
             "back to bytes first. gitleaks %s, %s." % (d["gitleaks_version"], d["platform"]),
             color="#8b949e", fontsize=14.5)
    save_fig(fig, os.path.join(OUT_HEAD, "ai-security-agent-log-hexdump-secrets-measured.webp"), size=(1600, 840))


def matrix(d):
    rows = d["formats"]
    n = d["events_per_format"]
    fig = plt.figure(figsize=(12, 8.4), dpi=100)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0.25, 0.10, 0.73, 0.71])
    cmap = LinearSegmentedColormap.from_list("rg", ["#ffd8d3", "#fff1c2", "#c9f0d3"])
    grid = [[r["caught"][k] / n for k, _ in MATRIX_COLS] for r in rows]
    ax.imshow(grid, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i, r in enumerate(rows):
        for j, (k, _) in enumerate(MATRIX_COLS):
            v = r["caught"][k]
            ax.text(j, i, "%d/%d" % (v, n), ha="center", va="center", fontsize=14, color="#1f2328",
                    weight="bold" if v in (0, n) else "normal")
    ax.set_xticks(range(len(MATRIX_COLS)))
    ax.set_xticklabels([lbl for _, lbl in MATRIX_COLS], fontsize=12, color="#1f2328")
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r["cmd"] for r in rows], fontsize=13, color="#1f2328", family="monospace")
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks([x - 0.5 for x in range(1, len(MATRIX_COLS))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(rows))], minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.axhline(1.5, color="#1f2328", linewidth=1.5)
    fig.text(0.015, 0.965, "Fake secrets caught, by the command that printed the .env and by defence", fontsize=16,
             weight="bold", color="#1f2328")
    fig.text(0.015, 0.03, "%d events per command (5 of each of 9 secret kinds), seed %d. Caught = the stored log no longer "
             "gives the secret back,\nor gitleaks flagged the record. cat and base64 are controls; the line separates them "
             "from the 9 dump formats." % (n, d["seed"]), fontsize=10.5, color="#57606a")
    save_fig(fig, os.path.join(OUT_POSTS, "agent-log-hexdumps-defence-matrix.webp"), size=(1200, 840))


def mask(text, token):
    return text.replace(token, token[:8] + "*" * (len(token) - 8))


def terminal(work):
    with open(os.path.join(work, "capture", "example.json")) as fh:
        ex = json.load(fh)
    with open(os.path.join(work, "example", ".env")) as fh:
        env = fh.read()
    token = re.search(r"GITHUB_TOKEN=(\S+)", env).group(1)
    # The token spans several dump rows; mask its bytes in the ASCII column too.
    rows = ex["out"].rstrip("\n").splitlines()
    ascii_col = "".join(r[51:] for r in rows)
    start = ascii_col.index(token[:12])
    keep = 8
    masked_rows = []
    pos = 0
    for r in rows:
        col = r[51:]
        chars = list(col)
        hexpart = r[10:49]
        hexchars = list(hexpart)
        for k in range(len(col)):
            p = pos + k
            if start + keep <= p < start + len(token):
                chars[k] = "*"
                hc = (k // 2) * 5 + (k % 2) * 2
                hexchars[hc:hc + 2] = ["*", "*"]
        masked_rows.append(r[:10] + "".join(hexchars) + r[49:51] + "".join(chars))
        pos += len(col)
    lines = [("$ xxd .env        # what the agent ran; the tool result is stored as one JSONL record", g.MUTED)]
    lines += [(r, g.FG) for r in masked_rows]
    lines.append(("", g.FG))
    lines.append(("$ gitleaks dir session.jsonl --redact", g.MUTED))
    for ln in ex["gitleaks_stored"].strip().splitlines():
        ln = re.sub(r"^\d+:\d+[AP]M ", "", ln)
        lines.append((ln, g.GREEN if "no leaks" in ln else g.FG))
    lines.append(("", g.FG))
    lines.append(("$ gitleaks dir session-undumped.txt --redact -v -c agent-logs-gitleaks.toml   # after undump()", g.MUTED))
    for ln in ex["gitleaks_undumped"].strip().splitlines():
        if not ln.strip() or ln.startswith("Fingerprint") or ln.startswith("Entropy"):
            continue
        ln = re.sub(r"^\d+:\d+[AP]M ", "", ln)
        lines.append((ln, g.RED if ("leaks found" in ln or ln.startswith("RuleID")) else g.FG))
    lines.append(("", g.FG))
    lines.append(("stored record after undump + known-value redaction:", g.MUTED))
    lines.append((ex["stored_after"], g.BLUE))
    for text, _ in lines:
        if token in text:
            raise SystemExit("unmasked token in terminal line")
    g.OUT_POSTS = OUT_POSTS
    g.terminal(lines, "agent-log-hexdumps-xxd-gitleaks-terminal.webp", width=1400, title="zsh - one agent tool result")


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
    terminal(os.path.abspath(a.work))


if __name__ == "__main__":
    main()
