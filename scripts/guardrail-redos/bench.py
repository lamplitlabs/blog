#!/usr/bin/env python3
"""Time the guardrail rules in rules.json with CPython's `re` (a backtracking engine).

Usage: python3 bench.py <rules.json> <benign.txt> [budget_ms]

Prints tab-separated rows (same columns as bench.mjs, bench.go and the Rust bench):
  kind engine rule variant n bytes ms matched
kind=attack: one attack string per ladder step, median of up to 5 timings; the
ladder for a (rule, variant) stops after the first step slower than budget_ms.
kind=pos:    every positive example of the rule (n = how many matched, bytes = how many).
kind=natural: an ordinary line grown one word at a time (n = words), same stop rule.
kind=benign: the whole benign corpus, line by line (n = lines, bytes = bytes, matched =
             lines that matched or were changed), median of 5.
"""
import json
import re
import signal
import statistics
import sys
import time

rules_path, benign_path = sys.argv[1], sys.argv[2]
budget = float(sys.argv[3]) if len(sys.argv) > 3 else None
cfg = json.load(open(rules_path))
budget = budget or cfg["budget_ms"]
benign = open(benign_path, encoding="utf-8").read().splitlines()
engine = f"python{sys.version_info.major}.{sys.version_info.minor}-re"


def compile_rule(rule, variant):
    flags = re.IGNORECASE if "i" in rule["flags"] else 0
    return re.compile(rule[variant], flags)


def run(rx, mode, s):
    if mode == "search":
        return rx.search(s) is not None
    out = rx.sub("#", s)
    return out != s


class Capped(Exception):
    pass


def _alarm(signum, frame):
    raise Capped()


signal.signal(signal.SIGALRM, _alarm)
CAP_S = cfg.get("cap_s", 120)


def timed(rx, mode, s):
    """One timing. CPython's sre engine polls for signals while it backtracks, so a
    SIGALRM after CAP_S seconds stops a runaway match; that row reports the cap."""
    signal.setitimer(signal.ITIMER_REAL, CAP_S)
    t = time.perf_counter_ns()
    try:
        m = run(rx, mode, s)
    except Capped:
        return CAP_S * 1000.0, "capped"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    return (time.perf_counter_ns() - t) / 1e6, m


def row(*cols):
    print("\t".join(str(c) for c in cols), flush=True)


for rule in cfg["rules"]:
    for variant in ("naive", "hardened"):
        rx = compile_rule(rule, variant)
        mode = rule["mode"]
        hits = sum(run(rx, mode, p) for p in rule["positives"])
        row("pos", engine, rule["name"], variant, hits, len(rule["positives"]), 0, hits == len(rule["positives"]))
        a = rule["attack"]
        for n in cfg["ladder"]:
            s = a["prefix"] + a["unit"] * n + a["suffix"]
            first, m = timed(rx, mode, s)
            samples = [first]
            reps = 5 if first < 50 else 3 if first < 300 else 1
            for _ in range(reps - 1):
                samples.append(timed(rx, mode, s)[0])
            ms = statistics.median(samples)
            row("attack", engine, rule["name"], variant, n, len(s.encode()), f"{ms:.4f}", m)
            if ms > budget:
                break
        nat = rule["natural"]
        for k in range(1, len(nat["words"]) + 1):
            s = nat["prefix"] + nat["sep"].join(nat["words"][:k]) + nat["suffix"]
            first, m = timed(rx, mode, s)
            samples = [first] + [timed(rx, mode, s)[0] for _ in range(4 if first < 50 else 0)]
            ms = statistics.median(samples)
            row("natural", engine, rule["name"], variant, k, len(s.encode()), f"{ms:.4f}", m)
            if ms > budget:
                break
        samples = []
        for _ in range(5):
            t = time.perf_counter_ns()
            hits = sum(run(rx, mode, line) for line in benign)
            samples.append((time.perf_counter_ns() - t) / 1e6)
        row("benign", engine, rule["name"], variant, len(benign),
            sum(len(x.encode()) + 1 for x in benign), f"{statistics.median(samples):.4f}", hits)
