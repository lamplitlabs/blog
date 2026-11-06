#!/usr/bin/env python3
"""Create one isolated workspace per (ticket, spec variant, repetition).

Usage:
  python3 scripts/spec-to-pr/setup_runs.py --out .tmp/spec-to-pr-runs --reps 2

With --apply-patches each workspace also gets the coding agent's recorded
change from patches/<run>.patch, so the gates can be rerun without the agent:

  python3 scripts/spec-to-pr/setup_runs.py --out .tmp/spec-to-pr-runs --apply-patches

Each workspace is a copy of base/ (the small invoicing service) plus TICKET.md
(the thin or the full spec), turned into a git repo with one base commit so the
gates can diff what the coding agent changed. The hidden acceptance tests and
the reference solution are never copied into a workspace.
"""
import argparse
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
TICKETS = ["T1-late-fee", "T2-charge-retry", "T3-csv-export", "T4-discount", "T5-charge-log", "T6-pagination"]


def git(ws, *args):
    subprocess.run(["git", "-c", "user.name=base", "-c", "user.email=base@example.invalid",
                    "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
                   cwd=ws, check=True, stdout=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--variant", choices=["thin", "full", "both"], default="both",
                    help="create only one variant's workspaces (we ran all thin ones before any full one existed)")
    ap.add_argument("--apply-patches", action="store_true",
                    help="apply the recorded agent change from patches/<run>.patch")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for t in TICKETS:
        for variant in (("thin", "full") if a.variant == "both" else (a.variant,)):
            for r in range(1, a.reps + 1):
                ws = os.path.join(a.out, f"{t}.{variant}.r{r}")
                if os.path.exists(ws):
                    continue
                shutil.copytree(os.path.join(HERE, "base"), ws)
                shutil.copy(os.path.join(HERE, "specs", f"{t}.{variant}.md"), os.path.join(ws, "TICKET.md"))
                git(ws, "init", "-q")
                git(ws, "add", "-A")
                git(ws, "commit", "-q", "-m", "base")
                if a.apply_patches:
                    git(ws, "apply", os.path.join(HERE, "patches", os.path.basename(ws) + ".patch"))
                print(ws)


if __name__ == "__main__":
    main()
