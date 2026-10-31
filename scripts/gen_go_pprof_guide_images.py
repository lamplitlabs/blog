#!/usr/bin/env python3
"""Build the webp images for the Go pprof profiling guide post.

Usage: python3 scripts/gen_go_pprof_guide_images.py <capture-dir>

The capture directory holds the output of running the post's gateway-demo
(the Go program shown in the post) under load with `go build -trimpath`:
  shot-flame.png          headless-browser screenshot of `go tool pprof -http` flame graph (CPU, slow build)
  shot-mutex-source.png   pprof web UI source view of the mutex profile
  shot-goroutine-graph.png pprof web UI flame graph of the goroutine profile after load stopped
  run-repeats.txt         load-generator summaries of 12 s runs per mode, two runs each
  diff-full.txt           `go tool pprof -top -cum -diff_base=cpu-slow.pb.gz ... cpu-fast.pb.gz`

Screenshots are cropped and re-encoded; terminal panels are drawn from the
captured text verbatim (rows selected, not edited). Webp quality 82.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

SRC = sys.argv[1] if len(sys.argv) > 1 else "pprof-capture"
OUT_POSTS = "assets/img/posts/languages"
OUT_HEADER = "assets/img/headers/languages"

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
GO_CYAN = (0, 173, 216)


def font(path, size):
    return ImageFont.truetype(path, size)


def save(img, path):
    img.convert("RGB").save(path, "WEBP", quality=82)
    print("wrote", path, img.size, os.path.getsize(path), "bytes")


def read(name):
    with open(os.path.join(SRC, name)) as fh:
        return fh.read().splitlines()


# ------------------------------------------------------------ screenshots
def crop_shot(name, box, out):
    im = Image.open(os.path.join(SRC, name)).convert("RGB")
    save(im.crop(box), os.path.join(OUT_POSTS, out))


# ------------------------------------------------------------ terminal panels
def terminal(lines, out, width=1400, title="zsh", colour=None):
    mono = font(F_MONO, 21)
    line_h = 30
    top = 56
    height = top + 28 + line_h * len(lines) + 24
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, width - 12, height - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    for i, c in enumerate((RED, ORANGE, GREEN)):
        d.ellipse((34 + i * 26, 30, 48 + i * 26, 44), fill=c)
    d.text((width / 2 - 40, 26), title, font=font(F_REG, 18), fill=MUTED)
    y = top + 20
    for ln in lines:
        fill = colour(ln) if colour else FG
        d.text((36, y), ln, font=mono, fill=fill)
        y += line_h
    save(img, os.path.join(OUT_POSTS, out))


def run_summary():
    """Table of the repeat load runs (no profiler attached), parsed from run-repeats.txt."""
    import re
    rows = []
    for ln in read("run-repeats.txt"):
        m = re.match(r"(\w+) r(\d): requests=(\d+)\s+throughput=(\d+) req/s latency p50=([\d.]+)ms p99=([\d.]+)ms "
                     r"goroutines still alive after load stopped=(\d+)", ln)
        if m:
            rows.append(m.groups())
    W = 1400
    H = 150 + 62 * len(rows) + 70
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, W - 12, H - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    d.text((40, 32), "gateway-demo load runs: 256 workers, 12 s each, no profiler attached", font=font(F_BOLD, 28), fill=FG)
    cols = [("mode", 40), ("run", 230), ("requests", 330), ("req/s", 520), ("p50", 690), ("p99", 860),
            ("goroutines left after load", 1030)]
    hf, cf = font(F_REG, 22), font(F_MONO, 24)
    for name, x in cols:
        d.text((x, 96), name, font=hf, fill=MUTED)
    d.line((40, 132, W - 40, 132), fill=BORDER, width=2)
    y = 150
    for mode, run, req, rps, p50, p99, alive in rows:
        c = {"slow": RED, "noleak": ORANGE, "fast": GREEN}.get(mode, FG)
        vals = [mode, run, "{:,}".format(int(req)), "{:,}".format(int(rps)), p50 + " ms", p99 + " ms", "{:,}".format(int(alive))]
        for (name, x), v in zip(cols, vals):
            d.text((x, y), v, font=cf, fill=c if name in ("mode", "p99", "goroutines left after load") else FG)
        y += 62
    d.text((40, y + 10), "slow = all three bugs   noleak = only the goroutine leak fixed   fast = all three fixed",
           font=font(F_REG, 22), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "go-pprof-guide-load-results.webp"))


def diff_top():
    rows = read("diff-full.txt")
    header = [r for r in rows[:6] if r.startswith(("Type", "Duration"))]
    wanted = [
        "runtime.scanstack",
        "runtime.mallocgc",
        "main.redactSlow",
        "runtime.gcAssistAlloc",
        "runtime.gcBgMarkWorker",
        "regexp.MustCompile",
        "context.WithTimeout",
        "main.(*quotaSlow).charge",
        "regexp.(*Regexp).ReplaceAllString",
        "main.(*quotaFast).charge",
    ]
    picked = []
    for w in wanted:
        for r in rows:
            if r.rstrip().endswith("  " + w):
                picked.append(r.rstrip())
                break
    col = [r for r in rows if r.strip().startswith("flat")]
    lines = ["$ go tool pprof -top -cum -diff_base=cpu-slow.pb.gz gateway-demo cpu-fast.pb.gz"]
    lines += header + ["(rows selected from the full output; negative = CPU removed by the fix)"]
    lines += col[:1] + picked

    def colour(ln):
        if ln.startswith("$"):
            return BLUE
        if ln.startswith(("Type", "Duration", "(rows")):
            return MUTED
        parts = ln.split()
        if len(parts) >= 4 and parts[3].startswith("-"):
            return GREEN
        if len(parts) >= 4 and parts[3][0].isdigit() and parts[0] != "flat":
            return ORANGE
        return FG

    terminal(lines, "go-pprof-guide-diff-base.webp", colour=colour)


# ------------------------------------------------------------ header
def header():
    W, H = 1500, 788  # 40:21, the theme's .preview-img aspect ratio, so nothing is cropped
    oy = 74
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 40):
        d.line((x, 0, x, H), fill=(20, 25, 32), width=1)
    for y in range(0, H, 40):
        d.line((0, y, W, y), fill=(20, 25, 32), width=1)
    d.text((70, 60 + oy), "go tool pprof", font=font(F_MONO, 34), fill=GO_CYAN)
    d.text((70, 110 + oy), "One service, three profiles,", font=font(F_BOLD, 64), fill=FG)
    d.text((70, 185 + oy), "three different bugs", font=font(F_BOLD, 64), fill=FG)

    cards = [
        ("CPU profile", "regexp.MustCompile", "per request", ORANGE),
        ("Mutex profile", "171 s of delay", "one global lock", RED),
        ("Goroutine profile", "318,985 goroutines", "leaked on timeout", RED),
    ]
    x = 70
    for title, big, small, c in cards:
        d.rounded_rectangle((x, 300 + oy, x + 430, 470 + oy), radius=14, fill=PANEL, outline=c, width=3)
        d.text((x + 24, 318 + oy), title, font=font(F_REG, 26), fill=MUTED)
        d.text((x + 24, 360 + oy), big, font=font(F_BOLD, 36), fill=FG)
        d.text((x + 24, 414 + oy), small, font=font(F_REG, 26), fill=c)
        x += 460
    d.text((70, 520 + oy), "After the fixes:  p99 24.0 ms \u2192 5.1 ms   \u2022   +27% throughput   \u2022   0 leaked goroutines",
           font=font(F_BOLD, 32), fill=GREEN)
    d.text((70, 575 + oy), "Go 1.27.2, Apple M2 Pro, 256 concurrent workers, 12 s load runs (mean of 2)", font=font(F_REG, 24), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, "go-pprof-profiling-guide.webp"))


if __name__ == "__main__":
    crop_shot("shot-flame.png", (0, 0, 1500, 620), "go-pprof-guide-cpu-flamegraph.webp")
    crop_shot("shot-mutex-source.png", (0, 200, 1500, 640), "go-pprof-guide-mutex-source.webp")
    crop_shot("shot-goroutine-graph.png", (0, 0, 1500, 190), "go-pprof-guide-goroutine-leak.webp")
    run_summary()
    diff_top()
    header()
