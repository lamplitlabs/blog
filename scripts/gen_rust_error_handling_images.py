#!/usr/bin/env python3
"""Build the webp images for the "Rust error handling: thiserror vs anyhow, measured" post.

Usage:
  python3 scripts/gen_rust_error_handling_images.py <work-dir>

<work-dir> is the output of `bash scripts/rust-error-handling/measure.sh <work-dir>`.
Terminal panels show lines of the real show.txt, show-bt.txt and e0004.txt files,
cut to the panel width but not otherwise edited; charts read
scripts/data/rust-error-handling-m2pro.json (written by
scripts/rust-error-handling/summarise.py from the same work dir). Nothing is
typed in by hand.
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

WORK = sys.argv[1] if len(sys.argv) > 1 else "errbench-work"
DATA = "scripts/data/rust-error-handling-m2pro.json"
OUT_POSTS = "assets/img/posts/languages"
OUT_HEADER = "assets/img/headers/languages"

F_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
F_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
F_MONO = "/System/Library/Fonts/Menlo.ttc"

BG = (13, 17, 23)
PANEL = (22, 27, 34)
BORDER = (48, 54, 61)
GRID = (33, 38, 45)
FG = (230, 237, 243)
MUTED = (139, 148, 158)
BLUE = (88, 166, 255)
GREEN = (63, 185, 80)
ORANGE = (240, 136, 62)
RED = (248, 81, 73)
PURPLE = (188, 140, 255)
RUST = (222, 165, 132)

D = json.load(open(DATA))
COL = {"typed": GREEN, "hybrid": BLUE, "anyhow": ORANGE, "eager": RED}
NAME = {
    "typed": "thiserror end to end",
    "hybrid": "thiserror inside, anyhow at the caller",
    "anyhow": "anyhow + .with_context(|| ...)",
    "eager": "anyhow + .context(format!(...))",
}


def font(path, size):
    return ImageFont.truetype(path, size)


def save(img, path, quality=85):
    img.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    print("wrote", path, img.size, os.path.getsize(path), "bytes")


def t(variant, permille, bt=False):
    return next(x for x in D["timing"]
                if x["variant"] == variant and x["fault_permille"] == permille and x["backtrace"] == bt)


def alloc(variant, permille, bt=False):
    return next(x for x in D["allocs"]
                if x["variant"] == variant and x["fault_permille"] == permille and x["backtrace"] == bt)


def host_line():
    h = D["host"]
    return (f'{h["cpu"]}, {h["os"]}, {h["rustc"].split(" (")[0]}, anyhow {h["crates"]["anyhow"]}, '
            f'thiserror {h["crates"]["thiserror"]}, --release')


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
    tw = d.textlength(title, font=font(F_REG, 18))
    d.text((width / 2 - tw / 2, 26), title, font=font(F_REG, 18), fill=MUTED)
    y = top + 16
    for ln in lines:
        d.text((36, y), ln, font=mono, fill=colour(ln) if colour else FG)
        y += line_h
    save(img, os.path.join(OUT_POSTS, out))


def show_panel():
    rows = open(os.path.join(WORK, "show.txt")).read().rstrip("\n").splitlines()
    cut = 124
    lines = ["$ RUST_LIB_BACKTRACE=0 ./errbench show"] + [ln[:cut] + (" ..." if len(ln) > cut else "") for ln in rows]

    def colour(ln):
        if ln.startswith("$"):
            return BLUE
        if ln.startswith("input"):
            return MUTED
        if "downcast_ref" in ln:
            return ORANGE if "None" in ln else GREEN
        if ln.startswith("typed"):
            return GREEN
        if ln.startswith(("anyhow", "line 17", "Caused", "    ")):
            return RUST
        if ln.startswith("hybrid"):
            return BLUE
        return FG

    terminal(lines, "rust-error-handling-show.webp", colour=colour, size=17,
             title="one bad log line, rendered by each error type")


def backtrace_panel():
    rows = open(os.path.join(WORK, "show-bt.txt")).read().splitlines()
    start = rows.index("anyhow             {:?}  ->")
    stop = next(i for i in range(start, len(rows)) if rows[i].startswith("hybrid"))
    block = [ln.rstrip() for ln in rows[start + 1: stop] if ln.strip()]
    st_i = block.index("Stack backtrace:")
    frames = sum(1 for ln in block[st_i + 1:] if ln.strip()[:1].isdigit() and ":" in ln.strip()[:5])
    keep = block[:6 + 2 * 9]
    cut = 128
    home = os.path.expanduser("~")
    lines = ["$ RUST_LIB_BACKTRACE=1 ./errbench show     # the same anyhow error, {:?}, backtrace captured"]
    lines += [ln.replace(home, "~")[:cut] for ln in keep]
    lines += [f"   ... {len(block) - len(keep)} more lines: {frames} frames in all, "
              f'{D["debug_format_anyhow"][1]["output_bytes"]:,} bytes for one error']

    def colour(ln):
        if ln.startswith("$"):
            return BLUE
        if "errbench::" in ln or "parse_anyhow" in ln or "num_anyhow" in ln or "call_anyhow" in ln:
            return ORANGE
        if ln.lstrip().startswith("at "):
            return MUTED
        if ln.startswith("   ..."):
            return MUTED
        return FG

    terminal(lines, "rust-error-handling-backtrace.webp", colour=colour, size=16,
             title="anyhow Debug output with RUST_LIB_BACKTRACE=1")


def e0004_panel():
    rows = open(os.path.join(WORK, "e0004.txt")).read().rstrip("\n").splitlines()
    lines = ["$ cargo build      # ParseError gained a Truncated(usize) variant"] + rows

    def colour(ln):
        if ln.startswith("$"):
            return BLUE
        if ln.startswith("error"):
            return RED
        if ln.startswith(("note", "help", "   = note")):
            return BLUE
        if "not covered" in ln:
            return ORANGE
        return FG

    terminal(lines, "rust-error-handling-e0004.webp", colour=colour,
             title="rustc on a match over a thiserror enum", size=17)


# ------------------------------------------------------------ cost per line vs fault rate
def cost_chart():
    W, H = 1500, 860
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, W - 12, H - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    lines = D["lines_per_pass"]
    d.text((40, 32), f"Nanoseconds per log line vs share of bad lines ({lines:,} lines, median of 5 runs)",
           font=font(F_BOLD, 30), fill=FG)
    d.text((40, 76), host_line(), font=font(F_REG, 20), fill=MUTED)
    rates = [0, 10, 50, 250, 1000]
    # two panels: backtraces off (all four) and on (anyhow-backed three)
    panels = [(False, "backtrace capture off (RUST_LIB_BACKTRACE=0)", 60, 720, 300, 450),
              (True, "capture on (RUST_LIB_BACKTRACE=1)", 790, 1450, 0, 3500)]
    for bt, title, x0, x1, lo, hi in panels:
        y0, y1 = 190, 720
        d.text((x0, 130), title, font=font(F_BOLD, 22), fill=FG)
        pr = [r for r in rates if not (bt and r == 1000)]
        steps = 5 if not bt else 7  # off: 30 ns a step from 300 (y axis does not start at 0)
        for i in range(steps + 1):
            v = lo + (hi - lo) * i / steps
            y = y1 - (y1 - y0) * i / steps
            d.line((x0 + 60, y, x1, y), fill=GRID, width=1)
            d.text((x0, y - 10), f"{v:,.0f}", font=font(F_REG, 17), fill=MUTED)
        for i, r in enumerate(pr):
            x = x0 + 90 + (x1 - x0 - 130) * i / (len(pr) - 1)
            d.text((x - 22, y1 + 12), f"{r / 10:g}%", font=font(F_REG, 18), fill=MUTED)
        for v in ("typed", "hybrid", "anyhow", "eager"):
            if bt and v == "typed":
                continue
            pts = []
            for i, r in enumerate(pr):
                x = x0 + 90 + (x1 - x0 - 130) * i / (len(pr) - 1)
                ns = t(v, r, bt)["ns_per_line_median"]
                pts.append((x, y1 - (y1 - y0) * (ns - lo) / (hi - lo)))
            d.line(pts, fill=COL[v], width=4)
            for x, y in pts:
                d.ellipse((x - 6, y - 6, x + 6, y + 6), fill=COL[v])
            lx, ly = pts[-1]
            ns = t(v, pr[-1], bt)["ns_per_line_median"]
            off = {"typed": 18, "hybrid": -2, "anyhow": -24, "eager": -46}[v] if not bt else \
                {"hybrid": 14, "anyhow": -14, "eager": -40}[v]
            d.text((lx - 70, ly + off), f"{ns:,.0f}", font=font(F_BOLD, 18), fill=COL[v])
        d.text((x0 + 60, y1 + 42), "share of lines that fail to parse", font=font(F_REG, 18), fill=MUTED)
    y = 790
    x = 60
    for v in ("typed", "hybrid", "anyhow", "eager"):
        d.rounded_rectangle((x, y + 4, x + 22, y + 22), radius=4, fill=COL[v])
        d.text((x + 32, y), NAME[v], font=font(F_REG, 20), fill=FG)
        x += 40 + d.textlength(NAME[v], font=font(F_REG, 20)) + 30
    save(img, os.path.join(OUT_POSTS, "rust-error-handling-cost-per-line.webp"))


# ------------------------------------------------------------ table: allocations, env, build
def table():
    W = 1500
    rows_a = [("typed", False), ("hybrid", False), ("anyhow", False), ("eager", False),
              ("hybrid", True), ("anyhow", True), ("eager", True)]
    H = 300 + 50 * len(rows_a) + 360
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, W - 12, H - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    d.text((40, 32), "What one error costs: heap allocations, bytes and time", font=font(F_BOLD, 30), fill=FG)
    d.text((40, 76), host_line() + "; allocations from a counting #[global_allocator]", font=font(F_REG, 20), fill=MUTED)
    cols = [("error handling", 40), ("backtrace", 640), ("allocs / error", 800), ("bytes / error", 990),
             ("happy-path allocs / line", 1180)]
    for n, x in cols:
        d.text((x, 130), n, font=font(F_REG, 19), fill=MUTED)
    d.line((40, 162, W - 40, 162), fill=BORDER, width=2)
    y = 178
    for v, bt in rows_a:
        a = alloc(v, 1000, bt)
        z = alloc(v, 0, bt)
        d.text((40, y), NAME[v], font=font(F_BOLD, 22), fill=COL[v])
        d.text((640, y), "on" if bt else "off", font=font(F_MONO, 22), fill=RED if bt else FG)
        d.text((800, y), f'{a["allocs_per_error"]:g}', font=font(F_MONO, 22), fill=FG)
        d.text((990, y), f'{a["bytes_per_error"]:,.0f}', font=font(F_MONO, 22), fill=FG)
        d.text((1180, y), f'{z["allocs_per_line"]:.0f}', font=font(F_MONO, 22),
               fill=RED if z["allocs_per_line"] >= 0.5 else FG)
        y += 50
    d.line((40, y + 4, W - 40, y + 4), fill=BORDER, width=2)
    y += 26
    env = {e["env"]: e["ns_per_line_median"] for e in D["env_sweep_anyhow_5pct"]}
    d.text((40, y), "anyhow at 5% bad lines, ns per line, by environment:", font=font(F_BOLD, 22), fill=FG)
    y += 40
    for e, ns in env.items():
        d.text((60, y), f"{e:<38}", font=font(F_MONO, 20), fill=FG)
        d.text((620, y), f"{ns:,.0f} ns", font=font(F_MONO, 20), fill=RED if ns > 1.5 * env["unset"] else GREEN)
        y += 32
    dbg = {x["backtrace"]: x for x in D["debug_format_anyhow"]}
    y += 16
    d.text((40, y), f'format!("{{e:?}}") of one anyhow error: {dbg[False]["later_print_us_median"]:.1f} us without a backtrace, '
           f'{dbg[True]["later_print_us_median"]:.0f} us with one ({dbg[True]["first_print_us_median"] / 1000:.1f} ms the first time, '
           f'symbolication)', font=font(F_REG, 21), fill=FG)
    b = {x["crate"]: x for x in D["build"]}
    y += 40
    d.text((40, y), f'clean release build of a one-file crate: no deps {b["none"]["clean_release_build_s_median"]:.1f} s, '
           f'anyhow {b["anyhow"]["clean_release_build_s_median"]:.1f} s, thiserror {b["thiserror"]["clean_release_build_s_median"]:.1f} s '
           f'(syn + proc-macro), both {b["both"]["clean_release_build_s_median"]:.1f} s',
           font=font(F_REG, 19), fill=MUTED)
    y += 32
    d.text((40, y), f'stripped binary size: '
           f'+{(b["anyhow"]["stripped_binary_bytes"] - b["none"]["stripped_binary_bytes"]) / 1024:.0f} KiB for anyhow, '
           f'+{(b["thiserror"]["stripped_binary_bytes"] - b["none"]["stripped_binary_bytes"]) / 1024:.1f} KiB for thiserror',
           font=font(F_REG, 19), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "rust-error-handling-allocs-table.webp"))


# ------------------------------------------------------------ header (40:21)
def header():
    W, H = 1600, 840  # 40:21, the theme's .preview-img aspect ratio, so nothing is cropped
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 40):
        d.line((x, 0, x, H), fill=(20, 25, 32), width=1)
    for y in range(0, H, 40):
        d.line((0, y, W, y), fill=(20, 25, 32), width=1)
    d.text((80, 70), "#[derive(thiserror::Error)]   vs   anyhow::Result<T>", font=font(F_MONO, 30), fill=RUST)
    d.text((80, 120), "Rust error handling, measured:", font=font(F_BOLD, 72), fill=FG)
    d.text((80, 205), "the backtrace costs, not the crate", font=font(F_BOLD, 72), fill=FG)
    bars = [
        ("thiserror, 5% bad lines", t("typed", 50)["ns_per_line_median"], GREEN),
        ("anyhow, 5% bad lines", t("anyhow", 50)["ns_per_line_median"], ORANGE),
        ("anyhow + .context(format!())", t("eager", 50)["ns_per_line_median"], RED),
        ("anyhow + RUST_BACKTRACE=1", t("anyhow", 50, True)["ns_per_line_median"], PURPLE),
    ]
    mx = max(b[1] for b in bars)
    y = 340
    for label, ns, c in bars:
        d.text((80, y + 6), label, font=font(F_REG, 28), fill=FG)
        bw = max(6, 760 * ns / mx)
        d.rounded_rectangle((560, y, 560 + bw, y + 44), radius=6, fill=c)
        d.text((560 + bw + 14, y + 6), f"{ns:,.0f} ns/line", font=font(F_BOLD, 28), fill=FG)
        y += 70
    d.text((80, y + 30), "same parser, same error text, 200,000 log lines per pass", font=font(F_BOLD, 34), fill=GREEN)
    d.text((80, y + 84), f'{D["host"]["cpu"]}, {D["host"]["rustc"].split(" (")[0]}, median of 5 runs',
           font=font(F_REG, 26), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, "rust-error-handling-thiserror-vs-anyhow.webp"), quality=90)


if __name__ == "__main__":
    os.makedirs(OUT_POSTS, exist_ok=True)
    os.makedirs(OUT_HEADER, exist_ok=True)
    show_panel()
    backtrace_panel()
    e0004_panel()
    cost_chart()
    table()
    header()
