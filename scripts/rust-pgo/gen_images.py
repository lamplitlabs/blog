#!/usr/bin/env python3
"""Build the webp images for the "Rust PGO vs Go PGO" post.

Usage: python3 scripts/rust-pgo/gen_images.py <work-dir>

Reads scripts/data/rust-pgo-vs-go-m2pro.json (from summarise.py) and, from
<work-dir>, the rustc remarks, Go's pgodebug output and the flame-graph
screenshots in shots/ (chrome-headless-shell --screenshot of rs-off.svg and
rs-pgo.svg, see the post). Charts are drawn from the JSON; the compiler panel
prints captured lines (rows selected, symbols shortened by a regex, numbers
untouched). Screenshots are pasted 1:1, not resized. Webp quality 85.
"""
import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

WORK = sys.argv[1] if len(sys.argv) > 1 else "rust-pgo-work"
DATA = "scripts/data/rust-pgo-vs-go-m2pro.json"
OUT_POSTS = "assets/img/posts/performance"
OUT_HEADER = "assets/img/headers/performance"

F_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
F_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
F_MONO = "/System/Library/Fonts/Menlo.ttc"

BG = (13, 17, 23)
PANEL = (22, 27, 34)
BORDER = (48, 54, 61)
FG = (230, 237, 243)
MUTED = (139, 148, 158)
GREEN = (63, 185, 80)
ORANGE = (240, 136, 62)
RED = (248, 81, 73)
GO_CYAN = (0, 173, 216)
RUST = (222, 165, 132)
RUST_DARK = (183, 65, 14)

D = json.load(open(DATA))
C = D["cells"]


def font(path, size):
    return ImageFont.truetype(path, size)


def save(img, path, quality=85):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    print("wrote", path, img.size, os.path.getsize(path), "bytes")


def frame(w, h):
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, w - 12, h - 12), radius=12, fill=PANEL, outline=BORDER, width=2)
    return img, d


def cell(v, c="api"):
    return C[f"{v}/{c}"]


def signed(x):
    return f"{x:+.1f}%"


# ------------------------------------------------------------ header (40:21)
def header():
    W, H = 1600, 840
    img, d = frame(W, H)
    d.text((64, 50), "Rust PGO vs Go PGO", font=font(F_BOLD, 64), fill=FG)
    d.text((64, 132), f"the same log router, measured on an M2 Pro ({D['host']['rustc'].split(' (')[0]}, {D['host']['go']})",
           font=font(F_REG, 30), fill=MUTED)
    d.text((64, 200), "change vs each language's default build, api config, median of 10 runs",
           font=font(F_REG, 26), fill=MUTED)
    rows = [("Go  -pgo=cpu.pprof", "go-pgo", GO_CYAN),
            ("Rust  -Cprofile-use", "rs-pgo", RUST),
            ("Rust  fat LTO, no PGO", "rs-lto", RUST_DARK)]
    x_label, x_ins, x_cyc = 64, 720, 1160
    y = 268
    d.text((x_ins, y), "instructions / line", font=font(F_BOLD, 28), fill=FG)
    d.text((x_cyc, y), "cycles / line", font=font(F_BOLD, 28), fill=FG)
    y += 60
    scale = 22  # px per percent
    for label, v, col in rows:
        c = cell(v)
        d.text((x_label, y + 14), label, font=font(F_BOLD, 34), fill=col)
        for x0, key in ((x_ins, "instructions_per_line_vs_off_pct"), (x_cyc, "cycles_per_line_vs_off_pct")):
            val = c[key]
            zero = x0 + 230
            w = int(abs(val) * scale)
            good = val < 0
            bar = (zero - w, y + 10, zero, y + 58) if good else (zero, y + 10, zero + w, y + 58)
            d.rectangle(bar, fill=GREEN if good else RED)
            d.line((zero, y, zero, y + 68), fill=MUTED, width=2)
            tx = zero - w - 130 if good else zero + w + 12
            d.text((max(tx, x0 - 10), y + 16), signed(val), font=font(F_BOLD, 30), fill=FG)
        y += 110
    rp = cell("rs-pgo")
    d.text((64, H - 150), f"Rust PGO ran {-rp['instructions_per_line_vs_off_pct']:.1f}% fewer instructions, "
           f"but IPC fell {cell('rs-off')['ipc_median']:.2f} -> {rp['ipc_median']:.2f}.",
           font=font(F_REG, 32), fill=FG)
    n_builds = len({k.split("/")[0] for k in C})
    d.text((64, H - 100), f"All {n_builds} builds print the same checksum per config.", font=font(F_REG, 32), fill=MUTED)
    save(img, os.path.join(OUT_HEADER, "rust-pgo-vs-go-pgo.webp"))


# ------------------------------------------------------------ results table
def results():
    order = [("go-off", "Go default build"), ("go-pgo", "Go -pgo (10-pass profile)"),
             ("rs-off", "Rust release (default profile)"), ("rs-lto", "Rust fat LTO + 1 CGU"),
             ("rs-pgo", "Rust -Cprofile-use"), ("rs-pgo-lto", "Rust PGO + fat LTO"),
             ("rs-pgo-noicp", "Rust PGO, -disable-icp"), ("rs-pgo-nomemop", "Rust PGO, -disable-memop-opt"),
             ("rs-pgo-exttsp", "Rust PGO, ext-TSP block layout"),
             ("rs-pgo-outline", "Rust PGO, HistSink::write inline(never)"),
             ("rs-pgo-short", "Rust PGO, 1% profile (10k lines)"), ("rs-pgo-batchprof", "Rust PGO, batch profile")]
    W = 1600
    rowh = 54
    H = 200 + rowh * len(order) + 90
    img, d = frame(W, H)
    d.text((48, 36), "Instructions and cycles per routed line (api config), median of 10 interleaved runs",
           font=font(F_BOLD, 30), fill=FG)
    d.text((48, 82), "Change is against the same language's default build. Green: fewer; red: more. "
           "ns/line is the best of 5 passes.", font=font(F_REG, 22), fill=MUTED)
    cols = [(48, "build"), (720, "instr/line"), (900, "change"), (1060, "cycles/line"), (1240, "change"),
            (1390, "IPC"), (1490, "ns/line")]
    y = 130
    for x, t in cols:
        d.text((x, y), t, font=font(F_BOLD, 22), fill=MUTED)
    y += 44
    for i, (v, label) in enumerate(order):
        c = cell(v)
        if i % 2 == 0:
            d.rectangle((24, y - 6, W - 24, y + rowh - 10), fill=(27, 33, 41))
        col = GO_CYAN if v.startswith("go") else RUST
        d.text((48, y + 4), label, font=font(F_REG, 26), fill=col)
        mono = font(F_MONO, 24)
        d.text((720, y + 6), f"{c['instructions_per_line_median']:,.0f}", font=mono, fill=FG)
        for x, key in ((900, "instructions_per_line_vs_off_pct"), (1240, "cycles_per_line_vs_off_pct")):
            val = c[key]
            fill = MUTED if v.endswith("-off") else (GREEN if val < -0.5 else RED if val > 0.5 else MUTED)
            d.text((x, y + 6), "-" if v.endswith("-off") else signed(val), font=mono, fill=fill)
        d.text((1060, y + 6), f"{c['cycles_per_line_median']:.0f}", font=mono, fill=FG)
        d.text((1390, y + 6), f"{c['ipc_median']:.2f}", font=mono, fill=FG)
        d.text((1490, y + 6), f"{c['best_ns_per_line_median']:.0f}", font=mono, fill=FG)
        y += rowh
    d.text((48, y + 20), f"{D['host']['cpu']}, {D['host']['rustc'].split(' (')[0]} (LLVM {D['host']['llvm']}), {D['host']['go']}. "
           "Counters from /usr/bin/time -l, load-only run subtracted.", font=font(F_REG, 22), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "rust-pgo-vs-go-results.webp"))


# ------------------------------------------------------------ compiler decisions
def short_sym(s):
    s = re.sub(r"_ZN\d+_\$LT\$logroute\.\.(\w+)\$u20\$as\$u20\$logroute\.\.(\w+)\$GT\$\d+(\w+?)17h[0-9a-f]+E",
               lambda m: f"<{m.group(1)} as {m.group(2)}>::{m.group(3)}", s)
    return s


def compiler():
    rust = []
    for line in open(os.path.join(WORK, "remarks-pgo.txt")):
        if "pgo-icall-prom (success)" in line:
            rust.append(short_sym(line.replace("note: ", "").strip()))
    rust = [re.sub(r"^src/main\.rs:(\d+):\d+ pgo-icall-prom \(success\): Promote indirect call to ", r"main.rs:\1 promote ", l)
            for l in rust]
    go = sorted({l.strip() for l in open(os.path.join(WORK, "pgodebug-api.txt")) if "hot-budget check allows" in l})
    go = [re.sub(r"hot-budget check allows inlining for call (\S+) \(cost (\d+)\) at example\.com/logroute/main\.go:(\d+):\d+ in function (\S+)",
                 r"main.go:\3 inline \1 (cost \2) into \4", l) for l in go]
    devirt = [re.sub(r"example\.com/logroute/main\.go:(\d+):\d+: PGO devirtualizing interface call (\S+) to (\S+)",
                     r"main.go:\1 devirtualize \2 -> \3", l.strip())
              for l in open(os.path.join(WORK, "devirt-api.txt")) if l.strip()]
    go = devirt + go
    W = 1600
    lh = 34
    H = 120 + 70 + lh * len(rust) + 110 + lh * len(go) + 150
    img, d = frame(W, H)
    d.text((48, 36), "What each compiler did with the same workload's profile", font=font(F_BOLD, 32), fill=FG)
    y = 110
    d.text((48, y), "rustc -Cprofile-use -Cremark=pgo-icall-prom  (indirect-call promotion, LLVM)",
           font=font(F_BOLD, 24), fill=RUST)
    y += 50
    mono = font(F_MONO, 21)
    for l in rust:
        d.text((64, y), l, font=mono, fill=FG)
        y += lh
    y += 40
    d.text((48, y), "go build -pgo  (-gcflags=-m devirtualizations, then -d=pgodebug=1 hot-budget inlines)",
           font=font(F_BOLD, 24), fill=GO_CYAN)
    y += 50
    for l in go:
        d.text((64, y), l, font=mono, fill=FG)
        y += lh
    y += 30
    r = D["remarks"]
    d.text((48, y), f"Inlining remarks in logroute (default -> PGO): {r['off']['inline_success']} -> {r['pgo']['inline_success']} inlined, "
           f"{r['off']['inline_missed']} -> {r['pgo']['inline_missed']} not inlined.", font=font(F_REG, 24), fill=MUTED)
    d.text((48, y + 40), "Both compilers guard the same hottest targets (RoutePrefix, HistSink); rustc also guards SlowerThan.",
           font=font(F_REG, 24), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "rust-pgo-vs-go-compiler-decisions.webp"))


# ------------------------------------------------------------ flame graphs
def flames():
    a = Image.open(os.path.join(WORK, "shots", "rs-off.png")).convert("RGB")
    b = Image.open(os.path.join(WORK, "shots", "rs-pgo.png")).convert("RGB")
    pad, lab = 24, 50
    W = max(a.width, b.width) + 2 * pad
    H = a.height + b.height + 2 * lab + 3 * pad
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    y = pad
    for im, t in ((a, "Default release build: HistSink::write, the hash-map entry and RoutePrefix::matches are separate frames"),
                  (b, "PGO build, same input: everything hot is inlined into main; only memcmp is left outside")):
        d.text((pad, y + 10), t, font=font(F_BOLD, 24), fill=FG)
        y += lab
        img.paste(im, (pad, y))
        y += im.height + pad
    save(img, os.path.join(OUT_POSTS, "rust-pgo-vs-go-flamegraphs.webp"))


if __name__ == "__main__":
    header()
    results()
    compiler()
    flames()
