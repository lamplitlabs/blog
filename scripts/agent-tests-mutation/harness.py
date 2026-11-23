#!/usr/bin/env python3
"""Harness for the "agent-written Go tests, measured with mutation testing" post.

Usage (the agents themselves are run by hand between these steps, see the post's
Reproduce section):

  python3 harness.py setup   <work> <run> <arm> [from-run]   # make a workspace
  python3 harness.py prompt  <work> <run>                    # print the agent prompt
  python3 harness.py measure <work> <run> [rep]              # coverage, mutants, seeded defects
  python3 harness.py human   <work> [rep]                    # the same for the hand-written suite

Arms:
  plain     source files only, "write unit tests for this package"
  coverage  same, plus "CI fails below 90% statement coverage"
  mutants   start from <from-run>'s tests ("human" = the hand-written suite in
            svc/), plus MUTANTS.md: the surviving mutants
            gomut reported for them; "add or fix tests so these mutants are killed".
            Runs named mutants-rN start from "human"; runs named plainmut-rN
            start from plain-rN (summarise.py groups arms by the run-name prefix).

A workspace is <work>/ws/<run>: the non-test files of ../ai-review-gates/svc
(the 282-line token-budget service from the gates post), go.mod and TASK.md.
The agent never sees the seeded defect corpus or the hand-written tests.

measure copies only the workspace's *_test.go files next to a pristine copy of
the service source (so an agent that edited the source gains nothing), then:
  - go test -cover, test count
  - gomut (./gomut): every mutant, its state and the test that killed it
  - every source edit of the 26 seeded defects and 4 behaviour-preserving
    changes of ../ai-review-gates/corpus.py (test-file edits dropped): does
    `go test -count=1` (default vet on, as CI runs it) fail, and does `go test -race`?
Results go to <work>/results/<run>.json (<run>.rep<N>.json for a repeat);
summarise.py collects them.
"""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GATES_DIR = os.path.join(HERE, "..", "ai-review-gates")
SVC = os.path.join(GATES_DIR, "svc")
sys.path.insert(0, GATES_DIR)
from corpus import PATCHES  # noqa: E402

ENV = dict(os.environ, GOFLAGS="-mod=mod", GOTOOLCHAIN="local")
# behaviour-preserving source changes from the corpus; a suite that fails on
# them is brittle (B05 changes a default on purpose, B02/B06 touch tests only)
BENIGN = ["B01", "B03", "B04", "B07", "B08"]

TASK = {
    "plain": """# Task

This directory is a small Go package (`quota`): a token-budget service for an LLM
gateway. It has no tests yet.

Write unit tests for this package. Put them in `*_test.go` files in this
directory, package `quota`, standard library only. Run them with `go test ./...`;
they must pass.

Do not change the non-test `.go` files or `go.mod`.
""",
    "coverage": """# Task

This directory is a small Go package (`quota`): a token-budget service for an LLM
gateway. It has no tests yet.

Write unit tests for this package. Put them in `*_test.go` files in this
directory, package `quota`, standard library only. Run them with `go test ./...`;
they must pass.

CI fails the build below 90% statement coverage, so check it with
`go test -cover ./...` and reach at least 90%.

Do not change the non-test `.go` files or `go.mod`.
""",
    "mutants": """# Task

This directory is a small Go package (`quota`): a token-budget service for an LLM
gateway, with a unit test suite that passes.

CI now runs mutation testing on it. `MUTANTS.md` lists the mutants that
survived: small changes to the source (a flipped comparison, a removed
statement, an error replaced by nil) that the tests did not notice.

Add or fix tests so that as many of these mutants as possible are killed. A
mutant you are sure cannot change observable behaviour may be left alive; say
which and why in your report. Tests stay in `*_test.go` files in this
directory, package `quota`, standard library only, and `go test ./...` must
pass.

Do not change the non-test `.go` files or `go.mod`.
""",
}

PROMPT = """You are a coding agent working in one Go package.

Workspace: {ws}

Rules:
- Work ONLY inside that workspace directory. Do not read, list or search any other path (not the parent directory, not other workspaces, not the rest of the clone).
- Read TASK.md in the workspace first; it is your whole specification.
- Use the bash tool for go commands, e.g. cd {ws} && go test -cover ./...  (GOTOOLCHAIN=local is fine; no network is needed).
- Do not change the non-test .go files or go.mod. Do not create files outside the workspace.
- Do not ask questions; make reasonable decisions where the task is silent.

When finished, report: the test files you wrote or changed, the number of test functions, the final `go test -cover` line, and (if TASK.md asks) which mutants you left alive and why.
"""


def run(cmd, cwd, timeout=600):
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout + p.stderr, round(time.time() - t0, 2)


def src_files():
    return sorted(f for f in os.listdir(SVC) if f.endswith(".go") and not f.endswith("_test.go"))


def ws_path(work, rid):
    return os.path.join(os.path.abspath(work), "ws", rid)


def gomut_bin(work):
    b = os.path.join(os.path.abspath(work), "bin", "gomut")
    if not os.path.exists(b):
        os.makedirs(os.path.dirname(b), exist_ok=True)
        rc, out, _ = run(["go", "build", "-o", b, "."], os.path.join(HERE, "gomut"))
        if rc:
            raise SystemExit(out)
    return b


def survivors_md(res):
    lines = ["# Surviving mutants", "",
             f"gomut: {res['tests']} tests, statement coverage {res['coverage_pct']}%, "
             f"mutation score {res['mutation_score_pct']}% "
             f"({res['counts'].get('LIVED', 0)} lived, {res['counts'].get('NOT COVERED', 0)} not covered).", "",
             "| # | file:line | operator | change | source line | state |", "|---|---|---|---|---|---|"]
    for m in res["mutants"]:
        if m["status"] not in ("LIVED", "NOT COVERED"):
            continue
        repl = m["repl"] if m["repl"] else "(statement removed)"
        orig = m["orig"].replace("|", "\\|")
        lines.append(f"| {m['id']} | {m['file']}:{m['line']} | {m['op'].lower()} | `{orig}` -> `{repl}` "
                     f"| `{m['snippet'].replace('|', chr(92) + '|')}` | {m['status'].lower()} |")
    return "\n".join(lines) + "\n"


def setup(work, rid, arm, from_run=None):
    ws = ws_path(work, rid)
    shutil.rmtree(ws, ignore_errors=True)
    os.makedirs(ws)
    for f in src_files() + ["go.mod"]:
        shutil.copy(os.path.join(SVC, f), ws)
    if arm == "mutants":
        src = SVC if from_run == "human" else ws_path(work, from_run)
        for f in sorted(os.listdir(src)):
            if f.endswith("_test.go"):
                shutil.copy(os.path.join(src, f), ws)
        res = json.load(open(os.path.join(os.path.abspath(work), "results", from_run + ".json")))
        open(os.path.join(ws, "MUTANTS.md"), "w").write(survivors_md(res["gomut"]))
    open(os.path.join(ws, "TASK.md"), "w").write(TASK[arm])
    meta = {"run": rid, "arm": arm, "from": from_run}
    os.makedirs(os.path.join(os.path.abspath(work), "meta"), exist_ok=True)
    json.dump(meta, open(os.path.join(os.path.abspath(work), "meta", rid + ".json"), "w"))
    print(ws)


def scratch_tree(work, name, test_dir):
    dst = os.path.join(os.path.abspath(work), "trees", name)
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    for f in src_files() + ["go.mod"]:
        shutil.copy(os.path.join(SVC, f), dst)
    tests = sorted(f for f in os.listdir(test_dir) if f.endswith("_test.go"))
    for f in tests:
        shutil.copy(os.path.join(test_dir, f), dst)
    return dst, tests


def apply_src(tree, edits):
    for f, old, new in edits:
        if f.endswith("_test.go"):
            continue
        path = os.path.join(tree, f)
        s = open(path).read()
        if s.count(old) != 1:
            raise SystemExit(f"edit target occurs {s.count(old)} times in {f}: {old[:60]!r}")
        open(path, "w").write(s.replace(old, new))


def first_fail(out):
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("--- FAIL") or "WARNING: DATA RACE" in s or s.startswith("panic:") \
                or s.startswith("fatal error:") \
                or ".go:" in s and ("error" in s.lower() or "undefined" in s or "vet:" in s or "wrong" in s):
            return s[:160]
    return ""


def measure_tree(work, name, test_dir, title, rep=""):
    tree, tests = scratch_tree(work, name, test_dir)
    src_changed = [f for f in src_files()
                   if os.path.exists(os.path.join(test_dir, f))
                   and open(os.path.join(test_dir, f)).read() != open(os.path.join(SVC, f)).read()]
    rc, out, dt = run(["go", "test", "-count=1", "./..."], tree)
    if rc:
        raise SystemExit(f"{name}: suite fails on the pristine source:\n{out}")
    res = {"run": name, "title": title, "test_files": tests, "source_edited_by_agent": src_changed,
           "test_lines": sum(len(open(os.path.join(tree, f)).read().splitlines()) for f in tests),
           "suite_seconds": dt}
    gj = os.path.join(tree, "..", name + ".gomut.json")
    gh = os.path.join(os.path.abspath(work), "results", name + (".rep" + rep if rep else "") + ".gomut.html")
    rc, out, dt = run([gomut_bin(work), "-dir", tree, "-j", "4", "-title", title, "-json", gj, "-html", gh], tree)
    if rc:
        raise SystemExit(out)
    res["gomut"] = json.load(open(gj))
    res["gomut"]["dir"] = res["gomut"]["dir"] + " (" + name + ")"
    res["gomut_line"] = out.strip()
    defects = []
    base = tree
    for p in PATCHES:
        if p["cls"] == "benign" and p["id"] not in BENIGN:
            continue
        t = os.path.join(os.path.abspath(work), "trees", name + "-" + p["id"])
        shutil.rmtree(t, ignore_errors=True)
        shutil.copytree(base, t)
        apply_src(t, p["edits"])
        # -timeout: a defect that deadlocks the suite (D17, D20 under some
        # tests) fails it through the test binary's own timeout panic
        rc1, o1, d1 = run(["go", "test", "-count=1", "-timeout", "60s", "./..."], t)
        rc2, o2, d2 = run(["go", "test", "-race", "-count=1", "-timeout", "60s", "./..."], t)
        defects.append({"id": p["id"], "cls": p["cls"], "title": p["title"],
                        "test_fails": rc1 != 0, "race_fails": rc2 != 0,
                        "test_timeout": "panic: test timed out" in o1, "race_timeout": "panic: test timed out" in o2,
                        "test_s": d1, "race_s": d2,
                        "test_first": first_fail(o1) if rc1 else "", "race_first": first_fail(o2) if rc2 else ""})
        shutil.rmtree(t)
    res["defects"] = defects
    res["rep"] = rep or "1"
    out_p = os.path.join(os.path.abspath(work), "results", name + (".rep" + rep if rep else "") + ".json")
    json.dump(res, open(out_p, "w"), indent=1)
    caught = sum(d["test_fails"] for d in defects if d["cls"] != "benign")
    raced = sum(d["race_fails"] for d in defects if d["cls"] != "benign")
    brittle = sum(d["test_fails"] for d in defects if d["cls"] == "benign")
    print(f"{res['gomut_line']}\n  seeded defects caught: go test {caught}/26, go test -race {raced}/26; "
          f"benign changes failed: {brittle}/{len(BENIGN)}; source edited: {src_changed}")


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    cmd, work = sys.argv[1], sys.argv[2]
    os.makedirs(os.path.join(os.path.abspath(work), "results"), exist_ok=True)
    if cmd == "setup":
        setup(work, sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else None)
    elif cmd == "prompt":
        print(PROMPT.format(ws=ws_path(work, sys.argv[3])))
    elif cmd == "measure":
        rid = sys.argv[3]
        meta = json.load(open(os.path.join(os.path.abspath(work), "meta", rid + ".json")))
        measure_tree(work, rid, ws_path(work, rid), f"{rid} ({meta['arm']})",
                     sys.argv[4] if len(sys.argv) > 4 else "")
    elif cmd == "human":
        measure_tree(work, "human", SVC, "human (hand-written suite)", sys.argv[3] if len(sys.argv) > 3 else "")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
