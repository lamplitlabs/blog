#!/usr/bin/env python3
"""Where the second of `go test -race` goes: GORACE=atexit_sleep_ms.

Usage:
  python3 scripts/ai-sdlc-flaky-gates/timing.py <work-dir> [reps]

Run after measure.py (reuses <work-dir>/bin and <work-dir>/trees). For every case
it runs the plain binary, the race binary with the default GORACE, and the race
binary with GORACE=atexit_sleep_ms=0 (with -test.count=1 and =10), interleaved, `reps` times each (default 40),
all with -test.shuffle=<rep>. The race runtime sleeps atexit_sleep_ms (1000 ms by
default) before a clean exit so late reports can still print; the verdicts must
not change when the sleep is removed. Writes <work-dir>/timing.jsonl.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from corpus import CASES  # noqa: E402

WORK = os.path.abspath(sys.argv[1])
REPS = int(sys.argv[2]) if len(sys.argv) > 2 else 40
VARIANTS = [("plain", "plain", None, 1), ("race", "race", None, 1), ("race_nosleep", "race", "atexit_sleep_ms=0", 1),
            ("stress10_nosleep", "race", "atexit_sleep_ms=0", 10)]

log = open(os.path.join(WORK, "timing.jsonl"), "w")
for rep in range(1, REPS + 1):
    for c in CASES:
        for name, kind, gorace, count in VARIANTS:
            env = dict(os.environ)
            env.pop("GORACE", None)
            if gorace:
                env["GORACE"] = gorace
            cmd = [os.path.join(WORK, "bin", f"{c['id']}.{kind}.test"), f"-test.count={count}", f"-test.shuffle={rep}"]
            t0 = time.perf_counter()
            p = subprocess.run(cmd, cwd=os.path.join(WORK, "trees", c["id"]), env=env, capture_output=True, text=True)
            log.write(json.dumps({"case": c["id"], "variant": name, "rep": rep, "rc": p.returncode,
                                  "s": round(time.perf_counter() - t0, 4)}) + "\n")
    log.flush()
print("done", REPS, "reps")
