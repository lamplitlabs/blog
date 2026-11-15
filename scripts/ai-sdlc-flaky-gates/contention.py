#!/usr/bin/env python3
"""Run the race test binaries on a busy runner: P copies at once, all cases.

Usage:
  python3 scripts/ai-sdlc-flaky-gates/contention.py <work-dir> [rounds] [parallel]

Run after measure.py (it reuses <work-dir>/bin and <work-dir>/trees). Each round
starts `parallel` (default: CPU count) race binaries at the same time, drawn
round-robin from all cases, so a shared CI runner with neighbours is imitated
by this suite's own neighbours. Every binary runs with -test.shuffle=<seed>.
Appends to <work-dir>/contention.jsonl (one line per run, resumable by round).
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from corpus import CASES  # noqa: E402

WORK = os.path.abspath(sys.argv[1])
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 60
PAR = int(sys.argv[3]) if len(sys.argv) > 3 else os.cpu_count()
FAILRX = re.compile(r"--- FAIL: (\S+)")


def main():
    logp = os.path.join(WORK, "contention.jsonl")
    done = set()
    if os.path.exists(logp):
        done = {json.loads(l)["round"] for l in open(logp)}
    log = open(logp, "a")
    ids = [c["id"] for c in CASES]
    for rnd in range(1, ROUNDS + 1):
        if rnd in done:
            continue
        procs = []
        for k in range(PAR):
            cid = ids[(rnd * PAR + k) % len(ids)]
            seed = rnd * PAR + k
            cmd = [os.path.join(WORK, "bin", f"{cid}.race.test"), "-test.count=1", "-test.v", f"-test.shuffle={seed}"]
            procs.append((cid, seed, time.perf_counter(),
                          subprocess.Popen(cmd, cwd=os.path.join(WORK, "trees", cid), stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True)))
        for cid, seed, t0, p in procs:
            out, _ = p.communicate(timeout=600)
            rec = {"round": rnd, "case": cid, "seed": seed, "parallel": PAR, "rc": p.returncode,
                   "s": round(time.perf_counter() - t0, 4), "fails": sorted(set(FAILRX.findall(out))),
                   "race": "WARNING: DATA RACE" in out, "load1": round(os.getloadavg()[0], 2)}
            log.write(json.dumps(rec) + "\n")
            if p.returncode and cid.startswith("T"):
                os.makedirs(os.path.join(WORK, "samples"), exist_ok=True)
                sp = os.path.join(WORK, "samples", f"{cid}.loaded.txt")
                if not os.path.exists(sp) and "TestCompleteSlowUpstream" in rec["fails"]:
                    open(sp, "w").write(f"{cid}.race.test -test.count=1 -test.v -test.shuffle={seed}  "
                                        f"# {PAR} binaries at once\n" + out)
        log.flush()
        print(f"round {rnd}/{ROUNDS} load {os.getloadavg()[0]:.1f}", flush=True)


if __name__ == "__main__":
    main()
