#!/usr/bin/env python3
"""Build the webp images for the "Tokio performance pitfalls, measured" post.

Usage:
  python3 scripts/gen_rust_tokio_pitfalls_images.py <work-dir>

<work-dir> is the output of `bash scripts/rust-tokio-pitfalls/measure.sh <work-dir>`.
The terminal panel shows lines of the real results.txt (one repetition, cut to the
panel width, not otherwise edited); charts read scripts/data/rust-tokio-pitfalls-m2pro.json
(written by scripts/rust-tokio-pitfalls/summarise.py from the same work dir).
Nothing is typed in by hand.
"""
import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

WORK = sys.argv[1] if len(sys.argv) > 1 else "tokiobench-work"
DATA = "scripts/data/rust-tokio-pitfalls-m2pro.json"
OUT_POSTS = "assets/img/posts/performance"
OUT_HEADER = "assets/img/headers/performance"

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


def font(path, size):
    return ImageFont.truetype(path, size)


def save(img, path, quality=85):
    img.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    print("wrote", path, img.size, os.path.getsize(path), "bytes")


def row(exp, **kw):
    return next(x for x in D[exp] if all(x.get(k) == v for k, v in kw.items()))


def host_line():
    h = D["host"]
    return (f'{h["cpu"]}, {h["os"]}, {h["rustc"].split(" (")[0]}, tokio {h["crates"]["tokio"]}, '
            f'{h["tokio_worker_threads"]} worker threads, median of {D["reps"]} runs')


def frame(W, H, title, sub=None):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, W - 12, H - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    d.text((40, 32), title, font=font(F_BOLD, 30), fill=FG)
    d.text((40, 76), sub or host_line(), font=font(F_REG, 20), fill=MUTED)
    return img, d


def fmt_us(us):
    if us >= 1000:
        return f"{us / 1000:,.1f} ms"
    return f"{us:,.0f} us"


# ------------------------------------------------------------ blocking: p99 vs burst size
BURSTS = [1, 2, 3, 4, 6, 8]
BCOL = {"inline": RED, "block_in_place": ORANGE, "spawn_blocking": GREEN}
BNAME = {
    "inline": "CPU work inline in the async task",
    "block_in_place": "tokio::task::block_in_place",
    "spawn_blocking": "tokio::task::spawn_blocking",
}


def blocking_chart():
    W, H = 1500, 900
    img, d = frame(W, H, "p99 latency of a 40 us request while 37 ms CPU jobs arrive in bursts")
    d.text((40, 106), "4,000 light requests/s, 20 heavy jobs/s in every case; only the burst size changes. Log scale.",
           font=font(F_REG, 20), fill=MUTED)
    x0, x1, y0, y1 = 150, 1180, 170, 740
    lo, hi = 1, 5  # log10(us): 10 us .. 100 ms
    for e in range(lo, hi + 1):
        y = y1 - (y1 - y0) * (e - lo) / (hi - lo)
        d.line((x0, y, x1, y), fill=GRID, width=1)
        d.text((x0 - 100, y - 11), fmt_us(10 ** e), font=font(F_REG, 18), fill=MUTED)
    base = row("blocking", variant="none")["p99_us"]
    yb = y1 - (y1 - y0) * (math.log10(base) - lo) / (hi - lo)
    d.line((x0, yb, x1, yb), fill=BLUE, width=2)
    d.text((x0 + 10, yb - 28), f"no heavy jobs: p99 {fmt_us(base)}", font=font(F_REG, 18), fill=BLUE)

    def xp(i):
        return x0 + 40 + (x1 - x0 - 80) * i / (len(BURSTS) - 1)

    for i, b in enumerate(BURSTS):
        d.text((xp(i) - 6, y1 + 14), str(b), font=font(F_BOLD, 20), fill=FG)
    d.text((x0 + 200, y1 + 50), "heavy jobs arriving at the same moment (4 = one per worker thread)",
           font=font(F_REG, 19), fill=MUTED)
    ends = []
    for v in ("inline", "block_in_place", "spawn_blocking"):
        pts = []
        for i, b in enumerate(BURSTS):
            us = row("blocking", variant=v, burst=b)["p99_us"]
            pts.append((xp(i), y1 - (y1 - y0) * (math.log10(us) - lo) / (hi - lo), us))
        d.line([(x, y) for x, y, _ in pts], fill=BCOL[v], width=4)
        for x, y, _ in pts:
            d.ellipse((x - 6, y - 6, x + 6, y + 6), fill=BCOL[v])
        ends.append((v, pts[-1]))
    # end labels, spread so they do not overlap
    ends.sort(key=lambda e: e[1][1])
    last = -100
    for v, (x, y, us) in ends:
        ly = max(y - 12, last + 30)
        d.text((x + 16, ly), fmt_us(us), font=font(F_BOLD, 20), fill=BCOL[v])
        last = ly
    y = 830
    x = 60
    for v in ("inline", "block_in_place", "spawn_blocking"):
        d.rounded_rectangle((x, y + 4, x + 22, y + 22), radius=4, fill=BCOL[v])
        d.text((x + 32, y), BNAME[v], font=font(F_REG, 20), fill=FG)
        x += 40 + d.textlength(BNAME[v], font=font(F_REG, 20)) + 40
    save(img, os.path.join(OUT_POSTS, "rust-tokio-pitfalls-blocking-p99.webp"))


# ------------------------------------------------------------ three small pitfalls as bars
def bars_chart():
    W, H = 1500, 1000
    img, d = frame(W, H, "The quieter pitfalls: lock choice, task granularity, file I/O")

    def panel(x0, title, unit, items, y_top=150):
        d.text((x0, y_top), title, font=font(F_BOLD, 23), fill=FG)
        mx = max(v for _, v, _ in items)
        y = y_top + 50
        for label, v, c in items:
            d.text((x0, y), label, font=font(F_REG, 19), fill=FG)
            bw = max(4, 270 * v / mx)
            d.rounded_rectangle((x0, y + 28, x0 + bw, y + 58), radius=5, fill=c)
            d.text((x0 + bw + 10, y + 31), f"{v:,.1f} {unit}" if v < 100 else f"{v:,.0f} {unit}",
                   font=font(F_BOLD, 19), fill=FG)
            y += 82
        return y

    m = {v: row("mutex", variant=v)["ns_per_op"] for v in ("std", "parking_lot", "tokio")}
    panel(40, "Shared HashMap, no await under the lock", "ns/op", [
        ("parking_lot::Mutex", m["parking_lot"], GREEN),
        ("std::sync::Mutex", m["std"], BLUE),
        ("tokio::sync::Mutex", m["tokio"], RED),
    ])
    s = {v: row("spawn", variant=v, work=200)["ns_per_item"] for v in ("per_item", "joinset", "chunked", "inline")}
    panel(530, "1M items of ~0.3 us CPU each", "ns/item", [
        ("16 chunked tasks", s["chunked"], GREEN),
        ("inline, one task", s["inline"], BLUE),
        ("tokio::spawn per item", s["per_item"], ORANGE),
        ("JoinSet per item", s["joinset"], RED),
    ])
    f = {v: row("fs", variant=v)["us_per_file"] for v in ("tokio_seq", "tokio_join", "std_inline", "one_blocking")}
    panel(1020, "5,000 cached 4 KiB files", "us/file", [
        ("tokio::fs, spawned per file", f["tokio_join"], BLUE),
        ("std::fs in one spawn_blocking", f["one_blocking"], GREEN),
        ("std::fs inline (blocks a worker)", f["std_inline"], ORANGE),
        ("tokio::fs, awaited in a loop", f["tokio_seq"], RED),
    ])
    h = {v: row("held", variant=v) for v in ("across_await", "scoped")}
    y = 560
    d.line((40, y, W - 40, y), fill=BORDER, width=2)
    d.text((40, y + 24), "tokio::sync::Mutex guard held across a 2 ms upstream call, 500 concurrent tasks",
           font=font(F_BOLD, 23), fill=FG)
    mx = h["across_await"]["wall_ms"]
    yy = y + 80
    for v, label, c in (("scoped", "guard dropped before the call", GREEN),
                        ("across_await", "guard held across .await", RED)):
        r = h[v]
        d.text((40, yy + 4), label, font=font(F_REG, 21), fill=FG)
        bw = max(6, 620 * r["wall_ms"] / mx)
        d.rounded_rectangle((380, yy, 380 + bw, yy + 38), radius=6, fill=c)
        d.text((380 + bw + 14, yy + 6),
               f'{r["wall_ms"]:,.1f} ms for all 500, p99 {r["p99_ms"]:,.1f} ms', font=font(F_BOLD, 21), fill=FG)
        yy += 70
    d.text((40, yy + 20), "Lower is better everywhere. Bars inside one panel share a scale; panels do not.",
           font=font(F_REG, 19), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "rust-tokio-pitfalls-small-ones.webp"))


# ------------------------------------------------------------ terminal panel with real output
def terminal():
    raw = open(os.path.join(WORK, "results.txt")).read().splitlines()
    rep = [i for i, ln in enumerate(raw) if ln.startswith("# rep=")]
    start = rep[len(rep) // 2]  # the middle repetition
    stop = rep[len(rep) // 2 + 1] if len(rep) // 2 + 1 < len(rep) else len(raw)
    block = raw[start + 1:stop]
    keep = []
    for ln in block:
        kv = dict(p.split("=", 1) for p in ln.split())
        e = kv["experiment"]
        if e == "blocking" and kv["burst"] in ("1", "4") or kv["variant"] == "none":
            keep.append(f'blocking {kv["variant"]:<15} burst={kv["burst"]}  p50={kv["p50_us"]:>6} us  '
                        f'p99={kv["p99_us"]:>9} us  max={kv["max_us"]:>9} us  >10ms={kv["over_10ms_pct"]}%')
        elif e == "held":
            keep.append(f'held     {kv["variant"]:<15} tasks={kv["tasks"]}  wall={kv["wall_ms"]} ms  '
                        f'p50={kv["p50_ms"]} ms  p99={kv["p99_ms"]} ms')
        elif e == "mutex":
            keep.append(f'mutex    {kv["variant"]:<15} ops={kv["ops"]}  {kv["ns_per_op"]} ns/op')
    cmd = "$ for v in ...; do ./tokiobench <experiment> $v ...; done   # one repetition, fields picked by the panel script"
    lines = [raw[0], raw[1], cmd] + keep
    size = 17
    while size > 11 and max(ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(ln, font=font(F_MONO, size))
                            for ln in lines) > 1500 - 72:
        size -= 1
    mono = font(F_MONO, size)
    line_h = int(size * 1.5)
    W = 1500
    H = 56 + 24 + line_h * len(lines) + 30
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, W - 12, H - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    for i, c in enumerate((RED, ORANGE, GREEN)):
        d.ellipse((34 + i * 26, 30, 48 + i * 26, 44), fill=c)
    title = "tokiobench, " + raw[start][2:].split(" load")[0] + " of " + str(len(rep))
    tw = d.textlength(title, font=font(F_REG, 18))
    d.text((W / 2 - tw / 2, 26), title, font=font(F_REG, 18), fill=MUTED)
    y = 72
    for ln in lines:
        if ln.startswith("#"):
            c = MUTED
        elif ln.startswith("$"):
            c = BLUE
        elif "inline" in ln and "burst=4" in ln or "across_await" in ln or "tokio " in ln and ln.startswith("mutex"):
            c = RED
        elif "spawn_blocking" in ln or "scoped" in ln or "parking_lot" in ln:
            c = GREEN
        else:
            c = FG
        d.text((36, y), ln, font=mono, fill=c)
        y += line_h
    save(img, os.path.join(OUT_POSTS, "rust-tokio-pitfalls-terminal.webp"))


# ------------------------------------------------------------ header (40:21)
def header():
    W, H = 1600, 840  # 40:21, the theme's .preview-img aspect ratio, so nothing is cropped
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 40):
        d.line((x, 0, x, H), fill=(20, 25, 32), width=1)
    for y in range(0, H, 40):
        d.line((0, y, W, y), fill=(20, 25, 32), width=1)
    d.text((80, 70), "#[tokio::main]   async fn handler() { ... }", font=font(F_MONO, 30), fill=RUST)
    d.text((80, 120), "Tokio performance pitfalls,", font=font(F_BOLD, 72), fill=FG)
    d.text((80, 205), "measured on one laptop", font=font(F_BOLD, 72), fill=FG)
    base = row("blocking", variant="none")["p99_us"]
    bars = [
        ("no heavy jobs", base, BLUE),
        ("spawn_blocking, burst 4", row("blocking", variant="spawn_blocking", burst=4)["p99_us"], GREEN),
        ("block_in_place, burst 4", row("blocking", variant="block_in_place", burst=4)["p99_us"], ORANGE),
        ("CPU inline, burst 4", row("blocking", variant="inline", burst=4)["p99_us"], RED),
    ]
    lo, hi = 1, 5.0  # log10 us
    y = 340
    for label, us, c in bars:
        d.text((80, y + 6), label, font=font(F_REG, 28), fill=FG)
        bw = max(6, 760 * (math.log10(us) - lo) / (hi - lo))
        d.rounded_rectangle((520, y, 520 + bw, y + 44), radius=6, fill=c)
        d.text((520 + bw + 14, y + 6), f"p99 {fmt_us(us)}", font=font(F_BOLD, 28), fill=FG)
        y += 70
    d.text((80, y + 30), "p99 of a 40 us request, 4 worker threads, log-scale bars", font=font(F_BOLD, 34), fill=GREEN)
    d.text((80, y + 84), f'{D["host"]["cpu"]}, {D["host"]["rustc"].split(" (")[0]}, tokio {D["host"]["crates"]["tokio"]}, '
           f'median of {D["reps"]} runs', font=font(F_REG, 26), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, "rust-tokio-performance-pitfalls.webp"), quality=90)


if __name__ == "__main__":
    os.makedirs(OUT_POSTS, exist_ok=True)
    os.makedirs(OUT_HEADER, exist_ok=True)
    blocking_chart()
    bars_chart()
    terminal()
    header()
