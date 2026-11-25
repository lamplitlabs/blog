#!/usr/bin/env python3
"""Write each agent workspace's change as patches/<ticket>.patch (git diff against the base tag).

Usage: python3 scripts/agent-pr-merge-queue/collect.py [WORK] [OUTDIR]
       (default .tmp/merge-queue-runs patches; the split arm: .tmp/merge-queue-runs-split patches-split)
"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".tmp/merge-queue-runs")
OUT = os.path.join(HERE, sys.argv[2] if len(sys.argv) > 2 else "patches")
os.makedirs(OUT, exist_ok=True)
for ws in sorted(glob.glob(os.path.join(WORK, "T*"))):
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
    diff = subprocess.run(["git", "diff", "--cached", "base", "--", ".", ":!TICKET.md", ":!AGENTS.md"],
                          cwd=ws, check=True, capture_output=True, text=True).stdout
    open(os.path.join(OUT, os.path.basename(ws) + ".patch"), "w").write(diff)
    print(os.path.basename(ws), len(diff.splitlines()), "lines")
