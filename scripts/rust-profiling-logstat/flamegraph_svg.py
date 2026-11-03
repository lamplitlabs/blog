#!/usr/bin/env python3
"""Render folded stacks as a flame graph SVG (flamegraph.pl layout, stdlib only).

Usage: python3 flamegraph_svg.py <in.folded> <out.svg> "<title>" [width]

Input lines are `frame;frame;frame count`, as written by fold_sample.py,
inferno-collapse-* or stackcollapse-perf.pl. Frames are sorted
alphabetically per level (as flamegraph.pl does), so the x axis is not time:
width is the share of samples. Colours are a stable hash of the frame name:
warm for this crate's code, blue-grey for the allocator and libc, sand for std
and core. Each box carries a <title> tooltip with samples and percent.
"""
import html
import sys
import zlib

FRAME_H = 22
FONT = 13
PAD_TOP = 54
PAD_BOTTOM = 26
ROOT = "logstat::main"  # frames above it (start, main, std::rt::lang_start...) are dropped


def load(path):
    stacks = []
    for line in open(path):
        line = line.rstrip()
        if not line:
            continue
        stack, _, n = line.rpartition(" ")
        frames = stack.split(";")
        if ROOT in frames:
            frames = frames[frames.index(ROOT):]
        stacks.append((frames, int(n)))
    return stacks


def build(stacks):
    def node():
        return {"n": 0, "kids": {}}

    root = node()
    for frames, n in stacks:
        root["n"] += n
        cur = root
        for f in frames:
            cur = cur["kids"].setdefault(f, node())
            cur["n"] += n
    return root


def colour(name):
    h = zlib.crc32(name.encode()) / 0xFFFFFFFF
    if name.startswith("logstat::"):
        return (int(205 + 50 * h), int(80 + 90 * h), int(30 + 40 * h))
    if any(k in name for k in ("malloc", "free", "xzm", "alloc", "memcmp", "memmove", "memcpy", "stub:", "_platform")):
        return (int(90 + 40 * h), int(140 + 40 * h), int(190 + 40 * h))
    if any(k in name for k in ("hash", "sip", "Hash")):
        return (int(130 + 40 * h), int(190 + 40 * h), int(110 + 40 * h))
    return (int(215 + 30 * h), int(170 + 50 * h), int(90 + 50 * h))


def short(name):
    # Trim generic noise so more of the frame fits in its box.
    for a, b in (("core::iter::adapters::", ""), ("core::iter::traits::iterator::", ""),
                 ("hashbrown::raw::", ""), ("hashbrown::map::", ""), ("alloc::", ""),
                 ("core::str::", "str::"), ("<core::hash::sip::Hasher<S> as core::hash::Hasher>::write", "SipHasher::write")):
        name = name.replace(a, b)
    return name


def render(root, out, title, width=1200, min_px=0.6):
    total = root["n"]
    rows = []

    def walk(n, name, x, depth):
        w = n["n"] / total * (width - 20)
        if w < min_px:
            return 0
        if depth >= 0:
            rows.append((name, x, depth, w, n["n"]))
        cx = x
        for k in sorted(n["kids"]):
            walk(n["kids"][k], k, cx, depth + 1)
            cx += n["kids"][k]["n"] / total * (width - 20)
        return w

    rows.append((f"all ({total} samples)", 10.0, 0, width - 20, total))
    cx = 10.0
    for k in sorted(root["kids"]):
        walk(root["kids"][k], k, cx, 1)
        cx += root["kids"][k]["n"] / total * (width - 20)

    depth = max(r[2] for r in rows) + 1
    height = PAD_TOP + depth * FRAME_H + PAD_BOTTOM
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="Menlo,monospace">',
         f'<rect width="100%" height="100%" fill="#f8f8f4"/>',
         f'<text x="{width/2}" y="26" font-size="18" text-anchor="middle" font-family="Helvetica,Arial,sans-serif" font-weight="bold">{html.escape(title)}</text>',
         f'<text x="10" y="{height-8}" font-size="12" fill="#555" font-family="Helvetica,Arial,sans-serif">width = share of 1 ms samples (macOS sample); x order is alphabetical, not time; frames above logstat::main trimmed</text>']
    for name, x, d, w, n in rows:
        y = height - PAD_BOTTOM - (d + 1) * FRAME_H
        r, g, b = colour(name) if d else (200, 200, 200)
        pct = 100.0 * n / total
        label = short(name)
        fits = int((w - 6) / (FONT * 0.6))
        text = ""
        if fits >= 3:
            text = label if len(label) <= fits else label[: max(fits - 2, 1)] + ".."
        o.append(f'<g><title>{html.escape(name)} ({n} samples, {pct:.1f}%)</title>'
                 f'<rect x="{x:.2f}" y="{y}" width="{max(w - 0.5, 0.1):.2f}" height="{FRAME_H - 1}" rx="1.5" fill="rgb({r},{g},{b})"/>'
                 + (f'<text x="{x + 3:.2f}" y="{y + FRAME_H - 7}" font-size="{FONT}">{html.escape(text)}</text>' if text else "")
                 + "</g>")
    o.append("</svg>")
    open(out, "w").write("\n".join(o))
    return height


if __name__ == "__main__":
    w = int(sys.argv[4]) if len(sys.argv) > 4 else 1200
    h = render(build(load(sys.argv[1])), sys.argv[2], sys.argv[3], w)
    print(f"wrote {sys.argv[2]} {w}x{h}")
