#!/usr/bin/env python3
"""Run every case in corpus.py's test binary many times and record each verdict.

Usage:
  python3 scripts/ai-sdlc-flaky-gates/measure.py <work-dir> [plain-reps] [race-reps]

Needs Go 1.24+ on PATH; nothing is downloaded (the service uses the standard
library only). For each case it copies scripts/ai-review-gates/svc into
<work-dir>/trees/<id>, applies the edits, and builds two test binaries once:
plain (`go test -c`) and race (`go test -c -race`). It then runs them in rounds,
interleaving cases and modes so drift in host load spreads over all of them:

  plain          ./plain.test -test.count=1
  shuffle        ./plain.test -test.count=1 -test.shuffle=<seed>
  race           ./race.test  -test.count=1
  race_shuffle   ./race.test  -test.count=1 -test.shuffle=<seed>
  stress10       ./race.test  -test.count=10 -test.shuffle=<seed>   (race-reps / 4 runs)

Shuffle seeds are 1, 2, 3, ... per (case, mode), so any failing run can be
replayed. Each run records exit code, wall seconds and the names of failing
tests. Appends to <work-dir>/runs.jsonl (resumable: finished (case, mode, rep)
triples are skipped) and writes <work-dir>/meta.json; summarise.py does the rest.
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from corpus import CASES  # noqa: E402

SVC = os.path.join(HERE, "..", "ai-review-gates", "svc")
WORK = os.path.abspath(sys.argv[1])
PLAIN_REPS = int(sys.argv[2]) if len(sys.argv) > 2 else 200
RACE_REPS = int(sys.argv[3]) if len(sys.argv) > 3 else 100
MODES = {
    "plain": ("plain", [], PLAIN_REPS),
    "shuffle": ("plain", ["shuffle"], PLAIN_REPS),
    "race": ("race", [], RACE_REPS),
    "race_shuffle": ("race", ["shuffle"], RACE_REPS),
    "stress10": ("race", ["shuffle", "count10"], max(1, RACE_REPS // 4)),
}
ENV = dict(os.environ, GOFLAGS="-mod=mod", GOTOOLCHAIN="local", CGO_ENABLED="1")
FAILRX = re.compile(r"--- FAIL: (\S+)")


def apply(case):
    dst = os.path.join(WORK, "trees", case["id"])
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(SVC, dst)
    for f, old, new in case["edits"]:
        path = os.path.join(dst, f)
        src = open(path).read()
        n = src.count(old)
        if n != 1:
            raise SystemExit(f"{case['id']}: edit target occurs {n} times in {f}: {old[:60]!r}")
        open(path, "w").write(src.replace(old, new))
    return dst


def build(case):
    tree = apply(case)
    out = {}
    for kind, extra in (("plain", []), ("race", ["-race"])):
        b = os.path.join(WORK, "bin", f"{case['id']}.{kind}.test")
        t0 = time.perf_counter()
        p = subprocess.run(["go", "test", "-c", *extra, "-o", b, "."], cwd=tree, env=ENV,
                           capture_output=True, text=True)
        if p.returncode:
            raise SystemExit(f"{case['id']} {kind}: build failed\n{p.stdout}{p.stderr}")
        out[kind] = {"bin": b, "build_s": round(time.perf_counter() - t0, 3)}
    vet = subprocess.run(["go", "vet", "."], cwd=tree, env=ENV, capture_output=True, text=True)
    out["vet"] = {"rc": vet.returncode, "first": next((l for l in vet.stderr.splitlines() if l and not l.startswith("#")), "")}
    return out


def main():
    os.makedirs(os.path.join(WORK, "bin"), exist_ok=True)
    gov = subprocess.run(["go", "version"], capture_output=True, text=True, env=ENV).stdout.strip()
    cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    bins = {c["id"]: build(c) for c in CASES}
    json.dump({"go": gov, "cpu": cpu or platform.processor(), "os": platform.platform(), "ncpu": os.cpu_count(),
               "modes": {m: {"bin": k, "flags": f, "reps": r} for m, (k, f, r) in MODES.items()},
               "builds": {i: {k: v for k, v in b.items()} for i, b in bins.items()}},
              open(os.path.join(WORK, "meta.json"), "w"), indent=1)
    logp = os.path.join(WORK, "runs.jsonl")
    done = set()
    if os.path.exists(logp):
        for line in open(logp):
            r = json.loads(line)
            done.add((r["case"], r["mode"], r["rep"]))
    log = open(logp, "a")
    rounds = max(r for _, _, r in MODES.values())
    for rep in range(1, rounds + 1):
        for c in CASES:
            for mode, (kind, flags, reps) in MODES.items():
                if rep > reps or (c["id"], mode, rep) in done:
                    continue
                cmd = [bins[c["id"]][kind]["bin"], "-test.count=" + ("10" if "count10" in flags else "1"), "-test.v"]
                if "shuffle" in flags:
                    cmd.append(f"-test.shuffle={rep}")
                tree = os.path.join(WORK, "trees", c["id"])
                t0 = time.perf_counter()
                p = subprocess.run(cmd, cwd=tree, capture_output=True, text=True, env=ENV, timeout=300)
                dt = time.perf_counter() - t0
                out = p.stdout + p.stderr
                fails = sorted(set(FAILRX.findall(out)))
                rec = {"case": c["id"], "mode": mode, "rep": rep, "rc": p.returncode, "s": round(dt, 4),
                       "fails": fails, "race": "WARNING: DATA RACE" in out,
                       "load1": round(os.getloadavg()[0], 2)}
                if p.returncode and not os.path.exists(os.path.join(WORK, "samples", f"{c['id']}.{mode}.txt")):
                    os.makedirs(os.path.join(WORK, "samples"), exist_ok=True)
                    open(os.path.join(WORK, "samples", f"{c['id']}.{mode}.txt"), "w").write(
                        " ".join(os.path.basename(x) if i == 0 else x for i, x in enumerate(cmd)) + "\n" + out)
                log.write(json.dumps(rec) + "\n")
                log.flush()
        print(f"round {rep}/{rounds} load {os.getloadavg()[0]:.1f}", flush=True)


if __name__ == "__main__":
    main()
