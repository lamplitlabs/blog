#!/usr/bin/env python3
"""Replay the 12 agent PRs through four merge policies, in seeded random arrival orders.

Every merge is a real `git merge` in a scratch repo and every CI verdict is a real
gofmt + go vet + go test -race run on the merged tree (cached by tree hash).
A PR that conflicts textually, or whose merged tree is red where the policy tests it,
is "bounced" back to its author for this pass.

Policies:
  stale   - required check green on the PR's own base, "require up to date" OFF:
            merge if git can, then CI runs on main afterwards.
  strict  - "require branches to be up to date" ON, every open PR updates (merges main in)
            and re-runs CI after each landing, as auto-updating agents do.
  queue1  - merge queue, one entry built at a time (main + PR).
  queue4  - merge queue building up to 4 entries at once, each on main + the entries ahead of it.

Usage: python3 scripts/agent-pr-merge-queue/simulate.py [WORK] [ORDERS]   (default .tmp/merge-queue 100)
Writes WORK/simulate.json.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ci  # noqa: E402

work = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".tmp/merge-queue")
N = int(sys.argv[2]) if len(sys.argv) > 2 else 100
repo = os.path.join(work, "repo")
if not os.path.exists(repo):
    ci.make_repo(work)
runner = ci.CI(repo, os.path.join(work, "ci-cache.json"))
T = [ci.short(t) for t in ci.tickets()]
MAIN = ci.git(repo, "rev-parse", "main").stdout.strip()


def stale(order):
    head, st = MAIN, {"landed": [], "bounced": [], "ci_runs": len(order), "ci_rounds": 1,
                      "red_main_commits": 0, "first_red_at": None, "red_causes": []}
    red = False
    for p in order:
        nxt, files = ci.merge(repo, head, p)
        if nxt is None:
            st["bounced"].append({"pr": p, "why": "textual", "files": files})
            continue
        head = nxt
        st["landed"].append(p)
        r = runner.run(head)          # post-merge CI on main
        st["ci_runs"] += 1
        st["ci_rounds"] += 1
        if not r["ok"]:
            st["red_main_commits"] += 1
            if not red:
                st["first_red_at"] = len(st["landed"])
                st["red_causes"].append({"pr": p, "first": r["first"]})
            red = True
    st["main_red_at_end"] = red
    return st


def strict(order):
    head, st = MAIN, {"landed": [], "bounced": [], "ci_runs": len(order), "ci_rounds": 1, "red_main_commits": 0}
    open_prs = list(order)
    while open_prs:
        # every open PR merges main in and re-runs CI (one parallel round)
        results = []
        for p in open_prs:
            nxt, files = ci.merge(repo, head, p)
            if nxt is None:
                results.append((p, None, files))
            else:
                results.append((p, nxt, runner.run(nxt)))
                st["ci_runs"] += 1
        st["ci_rounds"] += 1
        landed_one = False
        keep = []
        for p, nxt, r in results:
            if nxt is None:
                st["bounced"].append({"pr": p, "why": "textual", "files": r})
            elif not r["ok"]:
                st["bounced"].append({"pr": p, "why": r["stage"], "first": r["first"]})
            elif not landed_one:      # first green PR in arrival order wins the race
                head = nxt
                st["landed"].append(p)
                landed_one = True
            else:
                keep.append(p)
        open_prs = keep
    return st


def queue(order, k):
    head, st = MAIN, {"landed": [], "bounced": [], "ci_runs": len(order), "ci_rounds": 1,
                      "red_main_commits": 0, "wasted_runs": 0}
    q = list(order)
    while q:
        batch, trees, base = [], [], head
        for p in list(q):
            if len(batch) == k:
                break
            nxt, files = ci.merge(repo, base, p)
            if nxt is None:            # conflicts with what is ahead of it: removed without a build
                q.remove(p)
                st["bounced"].append({"pr": p, "why": "textual", "files": files})
                continue
            batch.append(p)
            trees.append(nxt)
            base = nxt
        if not batch:
            break
        res = [runner.run(t) for t in trees]
        st["ci_runs"] += len(batch)
        st["ci_rounds"] += 1
        for i, (p, t, r) in enumerate(zip(batch, trees, res)):
            q.remove(p)
            if r["ok"]:
                head = t
                st["landed"].append(p)
                continue
            st["bounced"].append({"pr": p, "why": r["stage"], "first": r["first"]})
            # entries behind it were built on top of the failed entry: their runs are wasted and
            # they stay at the head of the queue (still in q) to be rebuilt on the new base
            st["wasted_runs"] += len(batch) - i - 1
            break
    return st


rng = random.Random(20261123)
out = {"tickets": T, "orders": []}
for n in range(N):
    order = T[:]
    rng.shuffle(order)
    row = {"order": order, "stale": stale(order), "strict": strict(order),
           "queue1": queue(order, 1), "queue4": queue(order, 4)}
    out["orders"].append(row)
    print(n, " ".join(f'{k}:{len(row[k]["landed"])}/{row[k]["ci_runs"]}/{row[k]["red_main_commits"]}'
                      for k in ("stale", "strict", "queue1", "queue4")), flush=True)
    json.dump(out, open(os.path.join(work, "simulate.json"), "w"), indent=1)
out["unique_trees_tested"] = len(runner.cache)
json.dump(out, open(os.path.join(work, "simulate.json"), "w"), indent=1)
