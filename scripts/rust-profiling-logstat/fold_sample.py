#!/usr/bin/env python3
"""Fold a macOS `sample` call-graph report into flamegraph "folded stacks".

Usage: python3 fold_sample.py <sample-report.txt> [thread-filter] > out.folded

`/usr/bin/sample <pid> <seconds> 1 -file report.txt` ships with macOS and
needs no root (unlike dtrace, which cargo-flamegraph uses on macOS). Its
report is an indented call tree with a sample count per frame; this turns it
into the `frame;frame;frame count` lines that flamegraph.pl, inferno and
flamegraph_svg.py read. Rust symbols are demangled (legacy `$LT$`/`$GT$`
escapes and the trailing `::h<hash>`; v0 `_R...` symbols through c++filt), and sibling lines that differ only by
call-site offset are merged into one frame.
"""
import re
import subprocess
import sys
from functools import lru_cache
from collections import defaultdict

LINE = re.compile(r"^(?P<prefix>[\s+!:|]*)(?P<count>\d+) (?P<frame>.+)$")
ESCAPES = {
    "$LT$": "<", "$GT$": ">", "$u20$": " ", "$C$": ",", "$RF$": "&", "$BP$": "*",
    "$u7b$": "{", "$u7d$": "}", "$u5b$": "[", "$u5d$": "]", "$u27$": "'", "$SP$": "@",
}


@lru_cache(maxsize=None)
def demangle_v0(sym):
    """std ships v0-mangled (`_RNv...`) symbols; Xcode's c++filt reads them."""
    try:
        out = subprocess.run(["c++filt", sym], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return sym
    # drop the crate disambiguator hashes c++filt leaves in some paths
    return re.sub(r"\[[0-9a-f]+\]", "", out)


def clean(frame):
    name = frame.split("  (in ")[0].strip()
    if name.startswith("_R"):
        return demangle_v0(name)
    if name.startswith("_$LT$") or "$" in name:
        name = name.lstrip("_")
        for k, v in ESCAPES.items():
            name = name.replace(k, v)
        name = name.replace("..", "::")
    name = re.sub(r"::h[0-9a-f]{16}$", "", name)
    name = name.replace("DYLD-STUB$$", "stub:")
    return name


def fold(path, thread_filter="main-thread"):
    out = defaultdict(int)
    stack = []  # (depth, name, count, child_total)
    in_graph = False
    keep = False

    def pop_to(depth):
        while stack and stack[-1][0] >= depth:
            d, name, count, child = stack.pop()
            self_count = count - child
            if self_count > 0 and keep:
                out[";".join(s[1] for s in stack) + (";" if stack else "") + name] += self_count

    for raw in open(path, encoding="utf-8", errors="replace"):
        line = raw.rstrip("\n")
        if line.startswith("Call graph:"):
            in_graph = True
            continue
        if not in_graph:
            continue
        if not line.strip():
            pop_to(-1)
            if out:
                break
            continue
        m = LINE.match(line)
        if not m:
            continue
        depth = len(m["prefix"])
        count = int(m["count"])
        if depth <= 4 and m["frame"].startswith("Thread_"):
            pop_to(-1)
            keep = thread_filter in m["frame"]
            continue
        pop_to(depth)
        if stack:
            d, n, c, child = stack[-1]
            stack[-1] = (d, n, c, child + count)
        stack.append((depth, clean(m["frame"]), count, 0))
    pop_to(-1)
    return out


if __name__ == "__main__":
    folded = fold(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "main-thread")
    for k in sorted(folded):
        print(k, folded[k])
