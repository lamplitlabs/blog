#!/usr/bin/env python3
"""Create one git workspace per ticket for the coding-agent runs.

Usage: python3 scripts/agent-pr-merge-queue/setup_runs.py [WORK] [default.md|split.md]
       (default .tmp/merge-queue-runs default.md; the split arm used .tmp/merge-queue-runs-split)

Each workspace is the quota service from ../ai-review-gates/svc committed as
"base", plus agents-md/<arm> as AGENTS.md and the ticket as TICKET.md (both committed, so the
agent's diff is only its own change). After the agent ran, collect.py writes
`git diff base` of every workspace to patches/<ticket>.patch (patches-split/ for the second arm).
"""
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SVC = os.path.join(HERE, "..", "ai-review-gates", "svc")
WORK = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".tmp/merge-queue-runs")
# second arm: agents-md/split.md (merge-friendly rules) instead of agents-md/default.md
AGENTS = sys.argv[2] if len(sys.argv) > 2 else "default.md"


def git(ws, *args):
    return subprocess.run(["git", "-c", "user.name=harness", "-c", "user.email=harness@example.invalid",
                           "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
                          cwd=ws, check=True, capture_output=True, text=True).stdout


for t in sorted(glob.glob(os.path.join(HERE, "tickets", "T*.md"))):
    name = os.path.basename(t)[:-3]
    ws = os.path.join(WORK, name)
    if os.path.exists(ws):
        print("exists", ws)
        continue
    shutil.copytree(SVC, ws)
    shutil.copy(os.path.join(HERE, "agents-md", AGENTS), os.path.join(ws, "AGENTS.md"))
    shutil.copy(t, os.path.join(ws, "TICKET.md"))
    git(ws, "init", "-q", "-b", "main")
    git(ws, "add", "-A")
    git(ws, "commit", "-q", "-m", "base")
    git(ws, "tag", "base")
    print("ready", ws)
