#!/usr/bin/env python3
"""Build the webp images for the Rust profiling practical guide post.

Usage:
  BROWSER_PATH=<chrome-headless-shell> \
  python3 scripts/gen_rust_profiling_guide_images.py <work-dir>

<work-dir> is the output of `bash scripts/rust-profiling-logstat/measure.sh <work-dir>`
(the <v>.svg flame graphs and the raw <v>.sample.txt reports); the numbers come
from scripts/data/rust-profiling-logstat-m2pro.json, written by
scripts/rust-profiling-logstat/summarise.py from the same work dir. Nothing is
typed in by hand.

Flame graphs are screenshots of the SVGs rendered by a headless Chromium. The
terminal panel shows lines of the real `sample` report, cut to the panel width
but not otherwise edited. Webp quality 85.
"""
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

WORK = sys.argv[1] if len(sys.argv) > 1 else "logstat-work"
DATA = "scripts/data/rust-profiling-logstat-m2pro.json"
OUT_POSTS = "assets/img/posts/performance"
OUT_HEADER = "assets/img/headers/performance"
BROWSER = os.environ.get(
    "BROWSER_PATH",
    os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-1252/"
                       "chrome-headless-shell-mac-arm64/chrome-headless-shell"),
)

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
RUST = (222, 165, 132)
RUST_DEEP = (206, 92, 43)

D = json.load(open(DATA))
V = D["versions"]
LABEL = {
    "v0": "v0 naive",
    "v1": "v1 HashSet blocklist",
    "v2": "v2 borrowed &str fields",
    "v3": "v3 v2 + FxHash",
    "v4": "v4 v2 + byte scan",
}


def font(path, size):
    return ImageFont.truetype(path, size)


def save(img, path, quality=85):
    img.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    print("wrote", path, img.size, os.path.getsize(path), "bytes")


# ------------------------------------------------------------ flame graph screenshots
def flame_shot(v, out):
    svg = os.path.abspath(os.path.join(WORK, f"{v}.svg"))
    head = open(svg).read(400)
    w = int(head.split('width="')[1].split('"')[0])
    h = int(head.split('height="')[1].split('"')[0])
    png = os.path.abspath(os.path.join(WORK, f"{v}-shot.png"))
    profile_dir = os.path.abspath(os.path.join(WORK, "chrome-profile"))
    subprocess.run([BROWSER, "--headless=new", f"--user-data-dir={profile_dir}", "--hide-scrollbars",
                    "--force-device-scale-factor=1.5", f"--window-size={w},{h}", f"--screenshot={png}",
                    "file://" + svg], check=True, capture_output=True)
    save(Image.open(png), os.path.join(OUT_POSTS, out))


# ------------------------------------------------------------ terminal panel
def terminal(lines, out, width=1500, title="zsh", colour=None, size=19):
    mono = font(F_MONO, size)
    line_h = int(size * 1.45)
    top = 56
    height = top + 24 + line_h * len(lines) + 24
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, width - 12, height - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    for i, c in enumerate((RED, ORANGE, GREEN)):
        d.ellipse((34 + i * 26, 30, 48 + i * 26, 44), fill=c)
    d.text((width / 2 - 20, 26), title, font=font(F_REG, 18), fill=MUTED)
    y = top + 16
    for ln in lines:
        d.text((36, y), ln, font=mono, fill=colour(ln) if colour else FG)
        y += line_h
    save(img, os.path.join(OUT_POSTS, out))


def sample_report():
    rep = open(os.path.join(WORK, "v0.sample.txt")).read().splitlines()
    cg = rep.index("Call graph:")
    graph = [ln.rstrip() for ln in rep[cg + 1: cg + 16]]
    tos = rep.index(next(ln for ln in rep if ln.startswith("Sort by top of stack")))
    top = [ln.rstrip() for ln in rep[tos: tos + 7]]
    cut = 134
    lines = ["$ sample $(pgrep logstat) 4 1 -file v0.sample.txt     # 4 s at 1 ms, no sudo",
             "$ sed -n '/^Call graph/,$p' v0.sample.txt | cut -c1-134"]
    lines += ["Call graph:   (start, main and std::rt frames above logstat::main omitted)"] + [ln[:cut] for ln in graph[6:15]]
    lines += ["...", "$ sed -n '/^Sort by top of stack/,+6p' v0.sample.txt | cut -c1-134"]
    lines += [ln[:cut] for ln in top]

    def colour(ln):
        if ln.startswith("$"):
            return BLUE
        if "is_blocked_v0" in ln:
            return ORANGE
        if "memcmp" in ln:
            return RED
        if ln.startswith(("Call graph", "Sort by", "...")):
            return MUTED
        return FG

    terminal(lines, "rust-profiling-guide-sample-report.webp", colour=colour, size=17, title="macOS sample report for logstat v0")


# ------------------------------------------------------------ results chart
def results():
    vs = list(V)
    W = 1500
    row_h = 92
    H = 190 + row_h * len(vs) + 120
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, W - 12, H - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    lines = D["input"]["lines"]
    d.text((40, 32), f"logstat on {lines:,} log lines: median of 5 interleaved runs, no profiler attached",
           font=font(F_BOLD, 30), fill=FG)
    d.text((40, 78), f'{D["host"]["cpu"]}, {D["host"]["os"]}, {D["host"]["rustc"].split(" (")[0]}, --release, '
           f'same checksum {V["v0"]["checksums"][0]} for every run', font=font(F_REG, 21), fill=MUTED)
    x0, x1 = 420, 1080
    maxw = max(V[v]["wall_ms_median"] for v in vs)
    hf = font(F_REG, 19)
    for name, x in (("version", 40), ("wall time (median, ms)", x0), ("instructions", 1110), ("allocs / line", 1310)):
        d.text((x, 130), name, font=hf, fill=MUTED)
    d.line((40, 162, W - 40, 162), fill=BORDER, width=2)
    y = 180
    for v in vs:
        r = V[v]
        c = {"v0": RED, "v1": ORANGE, "v3": MUTED}.get(v, GREEN)
        d.text((40, y + 8), LABEL[v], font=font(F_BOLD, 24), fill=FG)
        bw = max(4, (x1 - x0 - 110) * r["wall_ms_median"] / maxw)
        d.rounded_rectangle((x0, y + 4, x0 + bw, y + 44), radius=6, fill=c)
        d.text((x0 + bw + 12, y + 10), f'{r["wall_ms_median"]:,.0f} ms', font=font(F_BOLD, 24), fill=FG)
        d.text((40, y + 50), f'range {r["wall_ms_min"]:,.0f}-{r["wall_ms_max"]:,.0f} ms, user CPU {r["user_s_median"]:.2f} s',
               font=font(F_REG, 18), fill=MUTED)
        d.text((1110, y + 10), f'{r["instructions_median"] / 1e9:.2f} G', font=font(F_MONO, 24), fill=FG)
        d.text((1310, y + 10), f'{r["allocs_per_line"]:.1f}', font=font(F_MONO, 24), fill=FG)
        y += row_h
    speed = V["v0"]["wall_ms_median"] / V["v4"]["wall_ms_median"]
    d.text((40, y + 14), f'v0 -> v4: {speed:.1f}x faster, {V["v0"]["instructions_median"] / V["v4"]["instructions_median"]:.1f}x fewer '
           f'instructions. v3 (FxHash) retires {100 * (1 - V["v3"]["instructions_median"] / V["v2"]["instructions_median"]):.0f}% fewer '
           f'instructions than v2 but spends {100 * (V["v3"]["cycles_median"] / V["v2"]["cycles_median"] - 1):.0f}% more cycles.',
           font=font(F_REG, 21), fill=FG)
    d.text((40, y + 50), "instructions and cycles: /usr/bin/time -l; allocations: count-alloc build with a counting #[global_allocator]",
           font=font(F_REG, 18), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "rust-profiling-guide-results.webp"))


# ------------------------------------------------------------ header (40:21)
def header():
    W, H = 1600, 840  # 40:21, the theme's .preview-img aspect ratio, so nothing is cropped
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 40):
        d.line((x, 0, x, H), fill=(20, 25, 32), width=1)
    for y in range(0, H, 40):
        d.line((0, y, W, y), fill=(20, 25, 32), width=1)
    d.text((80, 70), "cargo build --release  +  sample  +  flame graph", font=font(F_MONO, 30), fill=RUST)
    d.text((80, 120), "Profiling Rust, measured:", font=font(F_BOLD, 72), fill=FG)
    speed = V["v0"]["wall_ms_median"] / V["v4"]["wall_ms_median"]
    d.text((80, 205), f"one profile per fix, {speed:.0f}x faster", font=font(F_BOLD, 72), fill=FG)

    # one bar per version, scaled to the median wall time
    vs = list(V)
    maxw = max(V[v]["wall_ms_median"] for v in vs)
    y = 330
    for v in vs:
        r = V[v]
        c = {"v0": RED, "v1": ORANGE, "v3": MUTED}.get(v, GREEN)
        d.text((80, y + 6), LABEL[v], font=font(F_REG, 28), fill=FG)
        bw = max(6, 820 * r["wall_ms_median"] / maxw)
        d.rounded_rectangle((470, y, 470 + bw, y + 44), radius=6, fill=c)
        d.text((470 + bw + 14, y + 6), f'{r["wall_ms_median"]:,.0f} ms', font=font(F_BOLD, 28), fill=FG)
        y += 64
    v0, v4 = V["v0"], V["v4"]
    d.text((80, y + 30), f'{v0["wall_ms_median"] / v4["wall_ms_median"]:.1f}x faster  \u2022  '
           f'{v0["allocs_per_line"]:.1f} \u2192 {v4["allocs_per_line"]:.0f} allocations per line  \u2022  same output',
           font=font(F_BOLD, 36), fill=GREEN)
    d.text((80, y + 86), f'1,000,000 log lines, {D["host"]["cpu"]}, {D["host"]["rustc"].split(" (")[0]}, median of 5 runs',
           font=font(F_REG, 26), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, "rust-profiling-practical-guide.webp"), quality=90)


if __name__ == "__main__":
    os.makedirs(OUT_POSTS, exist_ok=True)
    os.makedirs(OUT_HEADER, exist_ok=True)
    flame_shot("v0", "rust-profiling-guide-flame-v0.webp")
    flame_shot("v1", "rust-profiling-guide-flame-v1.webp")
    flame_shot("v2", "rust-profiling-guide-flame-v2.webp")
    flame_shot("v4", "rust-profiling-guide-flame-v4.webp")
    sample_report()
    results()
    header()
