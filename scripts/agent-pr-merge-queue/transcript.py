#!/usr/bin/env python3
"""Record two real terminal sessions for the post's terminal image: a clean `git merge` of two
agent PRs that no longer compiles (default arm), and one whose tests contradict (split arm).

Usage: python3 scripts/agent-pr-merge-queue/transcript.py [WORK]   (default .tmp/merge-queue-transcript)
Writes scripts/data/agent-pr-merge-queue-transcript.json.
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ci  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".tmp/merge-queue-transcript")
SESSIONS = [("patches", "T01", "T02"), ("patches-split", "T11", "T06")]
out = []
for patches, a, b in SESSIONS:
    ci.PATCHES = os.path.join(HERE, patches)
    work = os.path.join(WORK, patches)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    repo = ci.make_repo(work)
    lines = []
    for cmd in (["git", "merge", "--no-ff", "-q", "-m", f"Merge {a}", a],
                ["git", "merge", "--no-ff", "-m", f"Merge {b}", b],
                ["gofmt", "-l", "."], ["go", "vet", "./..."], ["go", "test", "-race", "./..."]):
        p = subprocess.run((ci.GIT + cmd[1:]) if cmd[0] == "git" else cmd, cwd=repo,
                           capture_output=True, text=True, env=ci.ENV)
        lines.append("$ " + " ".join(cmd))
        lines += [l for l in (p.stdout + p.stderr).splitlines() if l.strip()]
        if p.returncode:
            lines.append(f"[exit {p.returncode}]")
            break
    out.append({"arm": patches, "a": a, "b": b, "lines": lines})
    print("\n".join(lines), "\n")
json.dump(out, open(os.path.join(HERE, "..", "data", "agent-pr-merge-queue-transcript.json"), "w"), indent=1)
