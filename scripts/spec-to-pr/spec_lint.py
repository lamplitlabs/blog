#!/usr/bin/env python3
"""Spec gate: refuse to hand a ticket to a coding agent until it can be checked.

Usage:
  python3 scripts/spec-to-pr/spec_lint.py scripts/spec-to-pr/specs/*.md

Four rules, each a plain text check on the ticket markdown:
  S1 examples   at least two concrete examples ("->" or "e.g.")
  S2 edges      says what happens on bad or empty input ("raises", or a "No ..."/"past the end" rule)
  S3 scope      names the files the change may touch (a "Scope:" line)
  S4 rules      at least three bullet rules (lines starting with "- ")
Exit status 1 when any ticket fails a rule.

The first version counted only "->" for S1 and only "raises" for S2; it failed
four of the six full tickets on wording alone, so both rules were widened
(see the post). It is a text heuristic, not a parser: it checks that a ticket
*says* these things, not that what it says is right.
"""
import re
import sys


def lint(text):
    fails = []
    if len(re.findall(r"->|\be\.g\.", text)) < 2:
        fails.append("S1 examples: fewer than 2 concrete examples")
    if not re.search(r"\braises?\b|^- No \w+|past the end", text, re.M):
        fails.append("S2 edges: nothing on bad or empty input")
    if not re.search(r"^Scope:", text, re.M):
        fails.append("S3 scope: no 'Scope:' line naming the files to touch")
    if len(re.findall(r"^- ", text, re.M)) < 3:
        fails.append("S4 rules: fewer than 3 bullet rules")
    return fails


def main(paths):
    bad = 0
    for p in paths:
        fails = lint(open(p).read())
        name = p.rsplit("/", 1)[-1]
        if fails:
            bad += 1
            print(f"FAIL {name}")
            for f in fails:
                print(f"     {f}")
        else:
            print(f"ok   {name}")
    print(f"{len(paths) - bad}/{len(paths)} tickets ready for an agent")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
