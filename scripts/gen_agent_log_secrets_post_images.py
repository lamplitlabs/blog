#!/usr/bin/env python3
"""Build the webp images for the "secrets in agent logs, measured" post.

Usage:
  python3 scripts/gen_agent_log_secrets_post_images.py --work <scratch-dir> [--shot <encode-decode.png>]

Reads scripts/data/agent-log-secret-leaks.json (aggregates written by
scripts/agent_log_secret_leak_bench.py) and the bench's <scratch-dir>/capture/
files; every number and every terminal line is taken from those, nothing is
typed in by hand. --shot is a 1280x720 browser screenshot of the Lamplit Labs
Encode / Decode tool (https://tools.lamplitlabs.com/encode-decode) decoding a
Basic auth header from the corpus; it is cropped, not edited.

Outputs:
  assets/img/headers/ai/ai-security-secrets-in-agent-logs-measured.webp  (1600x840, 40:21)
  assets/img/posts/ai/agent-log-secrets-detection-matrix.webp
  assets/img/posts/ai/agent-log-secrets-gitleaks-one-session.webp
  assets/img/posts/ai/agent-log-secrets-stream-token-split.webp
  assets/img/posts/ai/agent-log-secrets-base64-decode-lamplit-tool.webp
"""
import argparse
import io
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "scripts", "data", "agent-log-secret-leaks.json")
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
BLUE = (88, 166, 255)
GREEN = (63, 185, 80)
ORANGE = (240, 136, 62)
RED = (248, 81, 73)
YELLOW = (210, 153, 34)

STRATEGIES = [
    ("naive_redaction", "Exact-value\nredaction\nat write time"),
    ("gitleaks", "gitleaks,\ndefault rules,\nstored JSONL"),
    ("gitleaks_decoded_view_tuned", "gitleaks,\ntuned config,\ndecoded view"),
    ("full_redaction", "Encoding-aware\nredaction +\nstream holdback"),
    ("full_plus_gitleaks_tuned", "Encoding-aware\nredaction + tuned\ndecoded scan"),
]
HEADER_LABELS = [
    "Exact-value redaction",
    "gitleaks, stored JSONL",
    "gitleaks, tuned, decoded",
    "Encoding-aware redaction",
    "... + tuned decoded scan",
]


def font(path, size):
    return ImageFont.truetype(path, size)


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


def pct(n, d):
    return 100.0 * n / d


# ------------------------------------------------------------ header (40:21)
def header(d):
    tot, ev = d["totals"], d["events"]
    fig = plt.figure(figsize=(16, 8.4), dpi=100)
    fig.patch.set_facecolor("#0d1117")
    fig.text(0.05, 0.885, "Secrets in AI agent logs, measured", color="#e6edf3", fontsize=40, weight="bold")
    fig.text(0.05, 0.815, "%d fake secrets planted in %d agent sessions (%s log records), %d leak shapes x %d each" % (
        ev, d["sessions"], format(d["records"], ","), len(d["shapes"]), d["events_per_shape"]),
        color="#8b949e", fontsize=20)
    ax = fig.add_axes([0.36, 0.17, 0.58, 0.58])
    ax.set_facecolor("#0d1117")
    labels = HEADER_LABELS
    vals = [tot[k] for k, _ in STRATEGIES]
    colours = ["#f85149", "#f0883e", "#d29922", "#58a6ff", "#3fb950"]
    ys = list(range(len(vals)))[::-1]
    ax.barh(ys, [pct(v, ev) for v in vals], color=colours, height=0.62)
    for y, v in zip(ys, vals):
        ax.text(pct(v, ev) + 1.2, y, "%d%%  (%d/%d)" % (round(pct(v, ev)), v, ev), va="center", color="#e6edf3", fontsize=19, weight="bold")
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, color="#e6edf3", fontsize=19)
    ax.set_xlim(0, 125)
    ax.set_xticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(axis="y", length=0, pad=14)
    fig.text(0.05, 0.075, "Share of planted secrets redacted before the write or flagged by the scan. gitleaks %s; tuned = "
             "+1 rule, +1 allowlist (false positives %s -> %d)." % (
                 d["gitleaks_version"], format(d["gitleaks_findings_outside_leak_events_decoded_view"], ","),
                 d["gitleaks_findings_outside_leak_events_decoded_view_tuned"]),
             color="#8b949e", fontsize=14.5)
    save_fig(fig, os.path.join(OUT_HEAD, "ai-security-secrets-in-agent-logs-measured.webp"), size=(1600, 840))


# ------------------------------------------------------------ detection matrix
def matrix(d):
    rows = d["shapes"]
    n = d["events_per_shape"]
    fig = plt.figure(figsize=(12, 9.205), dpi=100)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0.335, 0.115, 0.645, 0.70])
    cmap = LinearSegmentedColormap.from_list("rg", ["#ffd8d3", "#fff1c2", "#c9f0d3"])
    grid = [[r[k] / n for k, _ in STRATEGIES] for r in rows]
    ax.imshow(grid, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i, r in enumerate(rows):
        for j, (k, _) in enumerate(STRATEGIES):
            v = r[k]
            ax.text(j, i, "%d/%d" % (v, n), ha="center", va="center", fontsize=14,
                    color="#1f2328", weight="bold" if v in (0, n) else "normal")
    ax.set_xticks(range(len(STRATEGIES)))
    ax.set_xticklabels([lbl for _, lbl in STRATEGIES], fontsize=12, color="#1f2328")
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(["%s%s" % (r["label"], "" if r["known_to_runtime"] else " *") for r in rows], fontsize=12.5, color="#1f2328")
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks([x - 0.5 for x in range(1, len(STRATEGIES))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(rows))], minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    tot, ev = d["totals"], d["events"]
    for j, (k, _) in enumerate(STRATEGIES):
        fig.text(0.335 + 0.645 * (j + 0.5) / len(STRATEGIES), 0.075, "%d/%d\n%d%%" % (tot[k], ev, round(pct(tot[k], ev))),
                 ha="center", va="center", fontsize=13.5, weight="bold", color="#1f2328")
    fig.text(0.32, 0.075, "All shapes", ha="right", va="center", fontsize=13.5, weight="bold", color="#1f2328")
    fig.text(0.015, 0.965, "Planted secrets redacted before the write or flagged by the scan, by leak shape", fontsize=16, weight="bold", color="#1f2328")
    fig.text(0.015, 0.012, "%d sessions, %s JSONL records, seed %d. Redaction knows only the secrets in the runtime's env/vault;\n"
             "* = a key hard-coded in a repository file the agent read, unknown to the runtime." % (d["sessions"], format(d["records"], ","), d["seed"]),
             fontsize=10.5, color="#57606a")
    save_fig(fig, os.path.join(OUT_POSTS, "agent-log-secrets-detection-matrix.webp"), size=(1200, 920))


# ------------------------------------------------------------ terminal panel
def terminal(lines, out, width=1400, title="zsh"):
    mono = font(F_MONO, 20)
    line_h = 29
    top = 56
    height = top + 28 + line_h * len(lines) + 24
    img = Image.new("RGB", (width, height), BG)
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle((12, 12, width - 12, height - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    for i, c in enumerate((RED, ORANGE, GREEN)):
        dr.ellipse((34 + i * 26, 30, 48 + i * 26, 44), fill=c)
    tf = font(F_REG, 18)
    dr.text((width / 2 - dr.textlength(title, font=tf) / 2, 26), title, font=tf, fill=MUTED)
    y = top + 20
    for text, colour in lines:
        if dr.textlength(text, font=mono) > width - 72:
            raise SystemExit("terminal line too wide: %r" % text)
        dr.text((36, y), text, font=mono, fill=colour)
        y += line_h
    save_pil(img, os.path.join(OUT_POSTS, out))


def one_session(d, work):
    cap = os.path.join(work, "capture")
    with open(os.path.join(cap, "gitleaks-one-session-planted.json")) as fh:
        planted = json.load(fh)
    fname = planted["file"]
    with open(os.path.join(cap, "gitleaks-one-session.txt")) as fh:
        out = fh.read().splitlines()
    with open(os.path.join(work, "logs-none", fname)) as fh:
        records = fh.read().splitlines()
    lines = [("$ gitleaks dir %s --redact -v" % fname, BLUE)]
    keep = ("Finding:", "RuleID:", "Tags:", "Line:")
    for ln in out:
        if ln.startswith(keep):
            colour = FG
            if ln.startswith("RuleID:"):
                colour = YELLOW if "generic-api-key" in ln else GREEN
            lines.append((ln.replace("\t", "    "), colour))
        elif ln == "" and lines[-1][0] != "":
            lines.append(("", FG))
        elif " WRN " in ln or " INF " in ln:
            lines.append((ln.split(" ", 1)[1], MUTED))
    missed = [p for p in planted["planted"] if p["shape"] == "traceback_dsn"][0]
    ln = missed["lines"][0]
    lines.append(("", FG))
    lines.append(("$ sed -n %dp %s | jq -r .content     # planted leak, not reported" % (ln, fname), BLUE))
    content = json.loads(records[ln - 1])["content"].splitlines()
    for c in content:
        lines.append((c, RED if c.startswith("dsn") else FG))
    terminal(lines, "agent-log-secrets-gitleaks-one-session.webp", title="gitleaks %s on one agent session log" % d["gitleaks_version"])


# ------------------------------------------------------------ stream token split
def token_split(d, work):
    with open(os.path.join(work, "capture", "sse-example.json")) as fh:
        ex = json.load(fh)
    W = 1400
    pieces = ex["pieces"]
    a, b = ex["secret_start"], ex["secret_end"]
    chip_f = font(F_MONO, 22)
    small = font(F_REG, 17)
    head_f = font(F_BOLD, 26)
    img = Image.new("RGB", (W, 900), (255, 255, 255))
    dr = ImageDraw.Draw(img)
    dr.text((40, 30), "One streamed reply, one log record per token", font=head_f, fill=(31, 35, 40))
    dr.text((40, 70), "Split by the real tokenizer (%s)." % ex["tokenizer"].replace("llama-tokenize, ", "llama.cpp llama-tokenize, "),
            font=small, fill=(87, 96, 106))
    x, y = 40, 120
    pos = 0
    secret_tokens = 0
    longest = 0
    for p in pieces:
        in_secret = pos < b and pos + len(p) > a
        shown = p.replace(" ", "\u2423")
        w = dr.textlength(shown, font=chip_f) + 18
        if x + w > W - 40:
            x, y = 40, y + 52
        fill, edge = ((255, 235, 233), (207, 34, 46)) if in_secret else ((246, 248, 250), (208, 215, 222))
        dr.rounded_rectangle((x, y, x + w, y + 40), radius=6, fill=fill, outline=edge, width=2)
        dr.text((x + 9, y + 7), shown, font=chip_f, fill=(31, 35, 40))
        x += w + 8
        if in_secret:
            secret_tokens += 1
            longest = max(longest, len(p))
        pos += len(p)
    y += 64
    msg = ("The fake GitHub token spans %d of %d tokens; the longest piece is %d characters. "
           "No single record matches a scanner rule." % (secret_tokens, len(pieces), longest))
    dr.text((40, y), msg, font=small, fill=(31, 35, 40))
    y += 30
    first = next(i for i, p in enumerate(pieces) if p.startswith("gh"))
    recs = "  ".join('{"delta": %s}' % json.dumps(p) for p in pieces[first:first + 4])
    dr.text((40, y), "Stored log records:  " + recs + "  ...", font=font(F_MONO, 16), fill=(87, 96, 106))
    y += 56

    # tokens per secret kind (median), from the bench data
    names = {"aws_key_id": "AWS access key id", "db_password": "database password", "stripe_live": "Stripe live key",
             "github_pat": "GitHub PAT", "aws_secret": "AWS secret key", "slack_bot": "Slack bot token",
             "anthropic": "Anthropic API key", "jwt": "service JWT", "openai": "OpenAI project key"}
    stats = d["sse_tokens_per_secret"]
    order = sorted(stats, key=lambda k: stats[k]["median"])
    dr.text((40, y), "Tokens (= log records) a secret is spread across, median per secret type", font=font(F_BOLD, 20), fill=(31, 35, 40))
    y += 40
    maxv = max(stats[k]["median"] for k in order)
    bar_x = 300
    for k in order:
        v = stats[k]["median"]
        dr.text((40, y + 2), names[k], font=small, fill=(31, 35, 40))
        bw = int((W - bar_x - 260) * v / maxv)
        dr.rectangle((bar_x, y, bar_x + bw, y + 24), fill=(9, 105, 218))
        dr.text((bar_x + bw + 10, y + 2), "%g tokens, %g chars" % (v, d["secret_length_chars"][k]), font=small, fill=(31, 35, 40))
        y += 34
    y += 10
    img = img.crop((0, 0, W, y + 20))
    save_pil(img, os.path.join(OUT_POSTS, "agent-log-secrets-stream-token-split.webp"))


# ------------------------------------------------------------ tool screenshot
def tool_shot(shot):
    im = Image.open(shot).convert("RGB")
    if im.size != (1280, 720):
        raise SystemExit("expected a 1280x720 screenshot, got %s" % (im.size,))
    save_pil(im.crop((190, 72, 1090, 420)), os.path.join(OUT_POSTS, "agent-log-secrets-base64-decode-lamplit-tool.webp"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--shot")
    a = ap.parse_args()
    with open(DATA) as fh:
        d = json.load(fh)
    os.makedirs(OUT_HEAD, exist_ok=True)
    os.makedirs(OUT_POSTS, exist_ok=True)
    header(d)
    matrix(d)
    one_session(d, a.work)
    token_split(d, a.work)
    if a.shot:
        tool_shot(a.shot)


if __name__ == "__main__":
    main()
