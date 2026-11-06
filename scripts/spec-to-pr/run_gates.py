#!/usr/bin/env python3
"""Run the five PR gates over every agent workspace and write one JSON record per run.

Usage:
  python3 scripts/spec-to-pr/run_gates.py --runs .tmp/spec-to-pr-runs \
      --out scripts/spec-to-pr/data/gates-raw.json

A workspace is what setup_runs.py created plus the coding agent's uncommitted
changes. Gates, in the order a PR would meet them:

  own_tests      the agent's suite (base tests + its new tests) passes        - what "CI green" means today
  scope          only the files the ticket allows changed; no existing test edited
  diff_coverage  share of added executable lines in invoicing/ that the agent's tests run (stdlib trace)
  mutation       share of AST mutants on the added lines that the agent's tests kill
  acceptance     the hidden acceptance tests written from the full spec's rules and examples

Python 3.9+, standard library only. Mutants run in a scratch copy, never in the workspace.
"""
import argparse
import ast
import copy
import dis
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
TEST_CMD = [PY, "-m", "unittest", "discover", "-s", "tests", "-t", "."]
# Mutants must not reuse cached bytecode: a mutant such as `==` -> `!=` has the same
# byte size as the original, and CPython's .pyc check is (mtime in whole seconds, size),
# so a mutant written within the same second silently runs the previous module.
# Our first run scored killed mutants as survivors that way.
MUTANT_CMD = [PY, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", "."]
# Mutants must not reuse cached bytecode: a mutant such as `==` -> `!=` has the same
# byte size as the original, and CPython's .pyc check is (mtime in whole seconds, size),
# so a mutant written within the same second silently runs the previous module.
# Our first run scored 9 killed mutants as survivors that way.
MUTANT_CMD = [PY, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", "."]
ALLOWED = {
    "T1": {"invoicing/fees.py"},
    "T2": {"invoicing/payments.py"},
    "T3": {"invoicing/export.py"},
    "T4": {"invoicing/discounts.py"},
    "T5": {"invoicing/logs.py"},
    "T6": {"invoicing/store.py"},
}
COVERAGE_MIN = 90.0
MUTATION_MIN = 80.0

TRACE_SCRIPT = r'''
import json, sys, trace, unittest
t = trace.Trace(count=1, trace=0, ignoredirs=[sys.prefix, sys.exec_prefix])
def run():
    suite = unittest.defaultTestLoader.discover("tests", top_level_dir=".")
    unittest.TextTestRunner(stream=open("/dev/null", "w")).run(suite)
t.runfunc(run)
hits = {}
for (fn, ln), c in t.results().counts.items():
    if "/invoicing/" in fn:
        hits.setdefault(fn.split("/invoicing/")[-1], []).append(ln)
print(json.dumps(hits))
'''


def sh(cmd, cwd, timeout=60):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout + p.stderr, time.time() - t0
    except subprocess.TimeoutExpired:
        return 124, "timeout", time.time() - t0


def changed_files(ws):
    _, out, _ = sh(["git", "status", "--porcelain", "--untracked-files=all"], ws)
    files = []
    for line in out.splitlines():
        status, path = line[:2], line[3:]
        files.append((status.strip(), path))
    return files


def added_lines(ws, path):
    """Line numbers of path added relative to the base commit."""
    rc, out, _ = sh(["git", "diff", "--no-color", "-U0", "HEAD", "--", path], ws)
    if not out.strip():  # untracked: every line is new
        with open(os.path.join(ws, path)) as f:
            return set(range(1, len(f.read().splitlines()) + 1))
    lines = set()
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", out, re.M):
        start, n = int(m.group(1)), int(m.group(2) or 1)
        lines.update(range(start, start + n))
    return lines


def executable_lines(src):
    lines = set()

    def walk(code):
        lines.update(ln for _, ln in dis.findlinestarts(code) if ln)
        for c in code.co_consts:
            if hasattr(c, "co_code"):
                walk(c)
    walk(compile(src, "<m>", "exec"))
    # docstrings and bare constants compile to nothing worth covering
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            lines.discard(node.lineno)
    return lines


# --- mutation -------------------------------------------------------------
CMP_SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
            ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.In: ast.NotIn, ast.NotIn: ast.In,
            ast.Is: ast.IsNot, ast.IsNot: ast.Is}
BIN_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult,
            ast.FloorDiv: ast.Mult, ast.Mod: ast.FloorDiv, ast.Pow: ast.Mult}


def mutation_sites(tree, lines):
    sites = []
    for node in ast.walk(tree):
        ln = getattr(node, "lineno", None)
        if ln not in lines:
            continue
        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                if type(op) in CMP_SWAP:
                    sites.append(("cmp", ln, id(node), i))
        elif isinstance(node, ast.BinOp) and type(node.op) in BIN_SWAP:
            sites.append(("bin", ln, id(node), 0))
        elif isinstance(node, ast.BoolOp):
            sites.append(("bool", ln, id(node), 0))
        elif isinstance(node, ast.Constant) and type(node.value) is int and not isinstance(node.value, bool):
            sites.append(("int", ln, id(node), 0))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and re.fullmatch(r"\d+(\.\d+)?", node.value):
            sites.append(("numstr", ln, id(node), 0))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            sites.append(("not", ln, id(node), 0))
    return sites


def apply_mutant(src, lines, k):
    tree = ast.parse(src)
    site = mutation_sites(tree, lines)[k]
    kind, _, nid, i = site
    for node in ast.walk(tree):
        if id(node) != nid:
            continue
        if kind == "cmp":
            node.ops[i] = CMP_SWAP[type(node.ops[i])]()
        elif kind == "bin":
            node.op = BIN_SWAP[type(node.op)]()
        elif kind == "bool":
            node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        elif kind == "int":
            node.value = node.value + 1
        elif kind == "numstr":
            node.value = str(int(float(node.value)) + 1) if "." not in node.value else node.value + "1"
        elif kind == "not":
            # replace `not x` with `x` by turning the UnaryOp into its operand via a parent rewrite
            node.op = ast.UAdd() if False else node.op
            return None  # handled below
    return ast.unparse(tree)


class _DropNot(ast.NodeTransformer):
    def __init__(self, nid):
        self.nid = nid

    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        return node.operand if id(node) == self.nid else node


def mutant_source(src, lines, k):
    tree = ast.parse(src)
    sites = mutation_sites(tree, lines)
    kind, ln, nid, i = sites[k]
    if kind == "not":
        tree = _DropNot(nid).visit(tree)
        ast.fix_missing_locations(tree)
        return ast.unparse(tree), sites[k]
    return apply_mutant(src, lines, k), sites[k]


def mutation_gate(ws, path, lines):
    with open(os.path.join(ws, path)) as f:
        src = f.read()
    n = len(mutation_sites(ast.parse(src), lines))
    if n == 0:
        return {"mutants": 0, "killed": 0, "score": None, "survivors": []}
    scratch = tempfile.mkdtemp(prefix="spec2pr-mut-")
    try:
        dst = os.path.join(scratch, "ws")
        shutil.copytree(ws, dst, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        killed, survivors = 0, []
        for k in range(n):
            msrc, site = mutant_source(src, lines, k)
            with open(os.path.join(dst, path), "w") as f:
                f.write(msrc)
            for root, dirs, _ in os.walk(dst):
                if "__pycache__" in dirs:
                    shutil.rmtree(os.path.join(root, "__pycache__"))
            rc, _, _ = sh(MUTANT_CMD, dst, timeout=20)
            if rc != 0:
                killed += 1
            else:
                survivors.append({"kind": site[0], "line": site[1]})
        return {"mutants": n, "killed": killed, "score": round(100.0 * killed / n, 1), "survivors": survivors}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def acceptance_gate(ws, ticket):
    scratch = tempfile.mkdtemp(prefix="spec2pr-acc-")
    try:
        dst = os.path.join(scratch, "ws")
        shutil.copytree(ws, dst, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        name = f"test_accept_{ticket.lower()}.py"
        shutil.copy(os.path.join(HERE, "acceptance", name), os.path.join(dst, "tests", name))
        rc, out, _ = sh([PY, "-m", "unittest", "-v", f"tests.{name[:-3]}"], dst)
        results = {}
        for m in re.finditer(r"^(test_\w+) \([\w.]+\) \.\.\. (ok|FAIL|ERROR)", out, re.M):
            results[m.group(1)] = m.group(2)
        passed = sum(1 for v in results.values() if v == "ok")
        return {"passed": passed, "total": len(results), "results": results}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def gate_run(ws):
    name = os.path.basename(ws)
    ticket_full, variant, rep = name.split(".")
    ticket = ticket_full.split("-")[0]
    rec = {"run": name, "ticket": ticket, "ticket_name": ticket_full, "variant": variant, "rep": rep, "gates": {}}
    timings = {}

    t0 = time.time()
    rc, out, _ = sh(TEST_CMD, ws)
    m = re.search(r"Ran (\d+) tests?", out)
    rec["gates"]["own_tests"] = {"pass": rc == 0, "tests": int(m.group(1)) if m else 0}
    timings["own_tests"] = time.time() - t0

    t0 = time.time()
    files = changed_files(ws)
    src_files = [p for _, p in files if p.startswith("invoicing/")]
    test_files = [p for _, p in files if p.startswith("tests/")]
    edited_tests = [p for s, p in files if p.startswith("tests/") and s != "??"]
    outside = [p for p in src_files if p not in ALLOWED[ticket]] + \
              [p for _, p in files if not p.startswith(("invoicing/", "tests/"))]
    rec["gates"]["scope"] = {"pass": not outside and not edited_tests, "changed": [p for _, p in files],
                             "outside": outside, "edited_existing_tests": edited_tests}
    timings["scope"] = time.time() - t0

    t0 = time.time()
    rc, out, _ = sh([PY, "-c", TRACE_SCRIPT], ws)
    hits = json.loads(out.strip().splitlines()[-1]) if rc == 0 else {}
    cov_total = cov_hit = 0
    missed = []
    added = {}
    for p in src_files:
        with open(os.path.join(ws, p)) as f:
            src = f.read()
        add = added_lines(ws, p)
        added[p] = add
        exe = executable_lines(src) & add
        hit = set(hits.get(p.split("invoicing/")[-1], [])) & exe
        cov_total += len(exe)
        cov_hit += len(hit)
        missed += [f"{p}:{ln}" for ln in sorted(exe - hit)]
    pct = round(100.0 * cov_hit / cov_total, 1) if cov_total else 100.0
    rec["gates"]["diff_coverage"] = {"pass": pct >= COVERAGE_MIN, "pct": pct, "lines": cov_total, "missed": missed}
    timings["diff_coverage"] = time.time() - t0

    t0 = time.time()
    mut = {"mutants": 0, "killed": 0, "survivors": []}
    for p in src_files:
        r = mutation_gate(ws, p, added[p])
        mut["mutants"] += r["mutants"]
        mut["killed"] += r["killed"]
        mut["survivors"] += [dict(s, file=p) for s in r["survivors"]]
    mut["score"] = round(100.0 * mut["killed"] / mut["mutants"], 1) if mut["mutants"] else 100.0
    mut["pass"] = mut["score"] >= MUTATION_MIN
    rec["gates"]["mutation"] = mut
    timings["mutation"] = time.time() - t0

    t0 = time.time()
    acc = acceptance_gate(ws, ticket)
    acc["pass"] = acc["total"] > 0 and acc["passed"] == acc["total"]
    rec["gates"]["acceptance"] = acc
    timings["acceptance"] = time.time() - t0

    _, diff, _ = sh(["git", "diff", "--no-color", "--stat", "HEAD"], ws)
    _, numstat, _ = sh(["git", "diff", "--numstat", "HEAD"], ws)
    lines_added = sum(int(l.split()[0]) for l in numstat.splitlines() if l.split()[0].isdigit())
    rec["diff_lines_added"] = lines_added + sum(
        len(open(os.path.join(ws, p)).read().splitlines()) for s, p in files if s == "??")
    rec["timings_s"] = {k: round(v, 3) for k, v in timings.items()}
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    recs = []
    for name in sorted(os.listdir(a.runs)):
        ws = os.path.join(a.runs, name)
        if not os.path.isdir(os.path.join(ws, ".git")):
            continue
        # git status lists intent-to-add files as "A"; reset the index so new files read as "??"
        sh(["git", "reset", "-q"], ws)
        r = gate_run(ws)
        g = r["gates"]
        print(f"{name:28s} own={g['own_tests']['pass']!s:5} scope={g['scope']['pass']!s:5} "
              f"cov={g['diff_coverage']['pct']:5.1f} mut={g['mutation']['score']:5.1f} "
              f"({g['mutation']['killed']}/{g['mutation']['mutants']}) "
              f"acc={g['acceptance']['passed']}/{g['acceptance']['total']}", flush=True)
        recs.append(r)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump({"python": sys.version.split()[0], "coverage_min": COVERAGE_MIN,
                   "mutation_min": MUTATION_MIN, "runs": recs}, f, indent=1)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
