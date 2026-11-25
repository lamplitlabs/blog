#!/usr/bin/env python3
"""Pairwise merge matrix: for every ordered pair (A merged first, then B), does B still merge
textually, and is main green afterwards? Each of the 12 PRs was green on its own base.

Usage: python3 scripts/agent-pr-merge-queue/matrix.py [WORK]   (default .tmp/merge-queue)
Writes WORK/matrix.json.
"""
import itertools
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ci  # noqa: E402

work = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".tmp/merge-queue")
os.makedirs(work, exist_ok=True)
repo = ci.make_repo(work)
runner = ci.CI(repo, os.path.join(work, "ci-cache.json"))
T = [ci.short(t) for t in ci.tickets()]
solo = {}
for t in T:
    solo[t] = runner.run(t)
    print(t, "solo", solo[t]["stage"], solo[t]["seconds"], flush=True)
rows = []
for a, b in itertools.permutations(T, 2):
    first, _ = ci.merge(repo, "main", a)
    second, files = ci.merge(repo, first, b)
    if second is None:
        r = {"a": a, "b": b, "result": "textual", "files": files}
    else:
        c = runner.run(second)
        r = {"a": a, "b": b, "result": c["stage"], "first": c["first"], "seconds": c["seconds"]}
    rows.append(r)
    print(a, "then", b, r["result"], r.get("first", r.get("files")), flush=True)
json.dump({"solo": solo, "pairs": rows}, open(os.path.join(work, "matrix.json"), "w"), indent=1)
