#!/usr/bin/env python3
"""Apply every seeded agent patch to the base Go service and run the CI gates on it.

Usage:
  python3 scripts/ai-review-gates/run_gates.py <work-dir> [reps]

Needs Go (1.24+) and gitleaks 8.x on PATH. Builds gatecheck/ (golang.org/x/tools
analyzers + the policy rules) once, then for every patch in corpus.py:
copies svc/ into <work-dir>/trees/<id>, applies the edits, runs each gate and
records pass/fail, wall time and the first finding line. reps (default 3)
repeats the whole sweep so the timings have a median; a gate whose verdict
differs between reps is kept as flaky (fails k of reps), not averaged away.

Writes <work-dir>/results.json; summarise.py turns it into scripts/data/.
"""
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from corpus import PATCHES  # noqa: E402

WORK = os.path.abspath(sys.argv[1])
REPS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
SVC = os.path.join(HERE, "svc")
GATECHECK = os.path.join(WORK, "bin", "gatecheck")

# Gates in CI order. Each is (id, label, kind) where kind is "block" or "advisory".
GATES = [
    ("build_vet", "go build + go vet", "block"),
    ("test", "go test", "block"),
    ("race", "go test -race", "block"),
    ("diff_coverage", "added lines run by a test", "block"),
    ("analyzers", "nilness, shadow, unusedwrite", "block"),
    ("policy", "policy rules P1-P4", "block"),
    ("secrets", "gitleaks on added lines", "block"),
    ("test_integrity", "test-integrity diff rules", "block"),
    ("expected_moved", "expected value changed", "advisory"),
    ("review_hints", "review hints for the reviewer", "advisory"),
]


def run(cmd, cwd, env=None):
    t0 = time.perf_counter()
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    return p.returncode, (p.stdout + p.stderr), time.perf_counter() - t0


def first_line(out, pat=None):
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("---") or line.startswith("FAIL\t") or line == "FAIL":
            continue
        if line.startswith("ok ") or line.startswith("=== "):
            continue
        if pat and not re.search(pat, line):
            continue
        return line[:200]
    return ""


def apply(pid, edits):
    dst = os.path.join(WORK, "trees", pid)
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(SVC, dst)
    for f, old, new in edits:
        path = os.path.join(dst, f)
        src = open(path).read()
        n = src.count(old)
        if n != 1:
            raise SystemExit(f"{pid}: edit target occurs {n} times in {f}: {old[:60]!r}")
        open(path, "w").write(src.replace(old, new))
    return dst


def unified_diff(tree):
    out = []
    for f in sorted(os.listdir(SVC)):
        a = open(os.path.join(SVC, f)).read().splitlines(keepends=True)
        b = open(os.path.join(tree, f)).read().splitlines(keepends=True)
        out += difflib.unified_diff(a, b, "a/" + f, "b/" + f)
    return "".join(out)


def diff_lines(diff):
    """Yield (file, sign, text) for every added or removed line."""
    cur = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
        elif line.startswith("--- a/"):
            continue
        elif line[:1] in "+-" and cur:
            yield cur, line[0], line[1:]


ASSERT = re.compile(r"\bt\.(Fatal|Fatalf|Error|Errorf|Fail|FailNow)\(")
TESTFN = re.compile(r"^func (Test\w+)\(")
LITERAL = re.compile(r"(?:!=|==)\s*(-?\d+(?:\.\d+)?|\"[^\"]*\")")


def added_line_numbers(diff):
    """{file: set of new-side line numbers} for added lines."""
    out, cur, n = {}, None, 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
        elif line.startswith("@@"):
            n = int(re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line).group(1))
        elif line.startswith("---"):
            continue
        elif line.startswith("+"):
            out.setdefault(cur, set()).add(n)
            n += 1
        elif line.startswith(" "):
            n += 1
    return out


def uncovered_added(diff, prof):
    """Added non-test lines that sit inside a coverage block no test executed."""
    blocks = []
    for line in open(prof).read().splitlines()[1:]:
        m = re.match(r".*/([^/]+\.go):(\d+)\.\d+,(\d+)\.\d+ \d+ (\d+)$", line)
        if m:
            blocks.append((m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))))
    hits = []
    for f, lines in sorted(added_line_numbers(diff).items()):
        if f.endswith("_test.go"):
            continue
        for ln in sorted(lines):
            covering = [c for g, a, b, c in blocks if g == f and a <= ln <= b]
            if covering and max(covering) == 0:
                hits.append(f"{f}:{ln} added but never run by a test")
    return hits


def test_integrity(diff):
    """Block rules from the test-integrity post, Go flavour: a test that loses
    assertions, gains a Skip, or disappears."""
    added = {f: [] for f in os.listdir(SVC)}
    removed = {f: [] for f in os.listdir(SVC)}
    for f, s, t in diff_lines(diff):
        (added if s == "+" else removed).setdefault(f, []).append(t)
    hits = []
    for f in added:
        if not f.endswith("_test.go"):
            continue
        a, r = added[f], removed[f]
        if any("t.Skip" in x for x in a):
            hits.append(f"T02 skip-added: {f}")
        gone = {m.group(1) for x in r for m in [TESTFN.match(x)] if m} - {m.group(1) for x in a for m in [TESTFN.match(x)] if m}
        if gone:
            hits.append(f"T01 test-removed: {f}: {', '.join(sorted(gone))}")
        net = sum(bool(ASSERT.search(x)) for x in r) - sum(bool(ASSERT.search(x)) for x in a)
        if net > 0 and not gone:
            hits.append(f"T03 assertion-removed: {f}: {net} fewer t.Fatal/t.Error call(s)")
    return hits


def expected_moved(diff):
    """Advisory: a comparison literal in a test changed in the same PR as non-test code."""
    prod = any(not f.endswith("_test.go") for f, _, _ in diff_lines(diff))
    if not prod:
        return []
    rem = [(f, t) for f, s, t in diff_lines(diff) if s == "-" and f.endswith("_test.go")]
    add = [(f, t) for f, s, t in diff_lines(diff) if s == "+" and f.endswith("_test.go")]
    hits = []
    for f, old in rem:
        lo = LITERAL.findall(old) or re.findall(r"\(\"\w+\", (\d+)\)", old)
        for g, new in add:
            if g != f:
                continue
            ln = LITERAL.findall(new) or re.findall(r"\(\"\w+\", (\d+)\)", new)
            if lo and ln and lo != ln and difflib.SequenceMatcher(None, old, new).ratio() > 0.8:
                hits.append(f"T05 expected-value-moved: {f}: {lo[0]} -> {ln[0]}")
    return hits


ERR_RETURN = re.compile(r"\breturn\b.*(\berr\b|Errorf|errors\.New)")
UNLOCK = re.compile(r"\.(R?Unlock|Lock)\(\)")
DEFER_CLOSE = re.compile(r"^\s*defer .*\.Close\(\)")
CMP = re.compile(r"(<=|>=|(?<![<>=!:])[<>](?![<>=]))")


def review_hints(diff):
    """Advisory: point the reviewer (human or AI) at the lines worth reading.
    Four diff-only hints, no build needed:
      H1 an error return removed from non-test code (net count of error returns fell)
      H2 lock calls added or removed (lock scope changed)
      H3 a deferred Close moved or removed
      H4 a comparison flipped between strict and non-strict in an edited line"""
    rem = [(f, t) for f, s, t in diff_lines(diff) if s == "-" and not f.endswith("_test.go")]
    add = [(f, t) for f, s, t in diff_lines(diff) if s == "+" and not f.endswith("_test.go")]
    hits = []
    for f in sorted({f for f, _ in rem + add}):
        r = [t for g, t in rem if g == f]
        a = [t for g, t in add if g == f]
        lost = sum(bool(ERR_RETURN.search(x)) for x in r) - sum(bool(ERR_RETURN.search(x)) for x in a)
        if lost > 0:
            hits.append(f"H1 error-return-removed: {f}: {lost} fewer")
        if any(UNLOCK.search(x) for x in r + a):
            hits.append(f"H2 lock-scope-changed: {f}")
        if any(DEFER_CLOSE.search(x) for x in r):
            hits.append(f"H3 deferred-close-moved: {f}")
        for old in r:
            for new in a:
                if difflib.SequenceMatcher(None, old, new).ratio() < 0.85:
                    continue
                ops_o, ops_n = CMP.findall(old), CMP.findall(new)
                if ops_o and len(ops_o) == len(ops_n) and ops_o != ops_n:
                    hits.append(f"H4 boundary-flipped: {f}: {ops_o[0]} -> {ops_n[0]}")
    return hits


def gate(gid, tree, diff, env):
    if gid == "build_vet":
        rc, out, dt = run(["go", "vet", "./..."], tree, env)
        return rc != 0, first_line(out), dt
    if gid == "test":
        rc, out, dt = run(["go", "test", "-count=1", "./..."], tree, env)
        return rc != 0, first_line(out, r"\.go:\d+|panic"), dt
    if gid == "race":
        rc, out, dt = run(["go", "test", "-race", "-count=1", "./..."], tree, env)
        return rc != 0, first_line(out, r"DATA RACE|\.go:\d+|panic"), dt
    if gid == "diff_coverage":
        prof = os.path.join(tree, "cover.out")
        rc, out, dt = run(["go", "test", "-count=1", "-coverprofile=" + prof, "./..."], tree, env)
        if rc != 0 or not os.path.exists(prof):
            # the test gate already owns a failing test; do not count it twice
            return False, "skipped: tests failed", dt
        t0 = time.perf_counter()
        hits = uncovered_added(diff, prof)
        return bool(hits), "; ".join(hits[:3]), dt + time.perf_counter() - t0
    if gid in ("analyzers", "policy"):
        flags = ["-policy"] if gid == "policy" else ["-nilness", "-shadow", "-unusedwrite"]
        rc, out, dt = run(["go", "vet", "-vettool=" + GATECHECK] + flags + ["./..."], tree, env)
        line = first_line(out, r"\.go:\d+")
        return bool(line), line, dt
    if gid == "secrets":
        added = "\n".join(t for _, s, t in diff_lines(diff) if s == "+")
        t0 = time.perf_counter()
        p = subprocess.run(["gitleaks", "stdin", "--no-banner", "--redact", "-v", "--exit-code", "3"],
                           input=added, capture_output=True, text=True)
        dt = time.perf_counter() - t0
        rule = re.search(r"RuleID:\s+(\S+)", p.stdout + p.stderr)
        return p.returncode == 3, ("gitleaks: " + rule.group(1)) if rule else "", dt
    t0 = time.perf_counter()
    hits = {"test_integrity": test_integrity, "expected_moved": expected_moved,
            "review_hints": review_hints}[gid](diff)
    return bool(hits), "; ".join(hits), time.perf_counter() - t0


def main():
    os.makedirs(os.path.join(WORK, "bin"), exist_ok=True)
    env = dict(os.environ, GOFLAGS="-mod=mod", GOTOOLCHAIN="local")
    rc, out, _ = run(["go", "build", "-o", GATECHECK, "."], os.path.join(HERE, "gatecheck"), env)
    if rc:
        raise SystemExit("building gatecheck failed:\n" + out)
    go_version = subprocess.run(["go", "version"], capture_output=True, text=True).stdout.strip()
    gl_version = subprocess.run(["gitleaks", "version"], capture_output=True, text=True).stdout.strip()

    cases = [{"id": "BASE", "cls": "base", "title": "unmodified base tree", "edits": []}] + PATCHES
    # warm the build and test caches once so the first case is not charged for them
    run(["go", "test", "-race", "-count=1", "./..."], SVC, env)

    results = {}
    for rep in range(REPS):
        for c in cases:
            tree = apply(c["id"], c["edits"])
            diff = unified_diff(tree)
            row = results.setdefault(c["id"], {
                "id": c["id"], "cls": c["cls"], "title": c["title"],
                "diff_lines": sum(1 for _ in diff_lines(diff)), "diff": diff,
                "gates": {g: {"fail": False, "fails": [], "finding": "", "seconds": []} for g, _, _ in GATES},
            })
            for gid, _, _ in GATES:
                fail, finding, dt = gate(gid, tree, diff, env)
                g = row["gates"][gid]
                # a gate that fails on some reps and passes on others is recorded as
                # flaky rather than averaged away: a race can lose increments or not
                g["fails"].append(fail)
                g["fail"] = any(g["fails"])
                g["seconds"].append(round(dt, 4))
                if fail and not g["finding"]:
                    g["finding"] = finding
            verdicts = "".join("X" if row["gates"][g]["fails"][-1] else "." for g, _, _ in GATES)
            print(f"rep {rep + 1} {c['id']:5} {verdicts}  {c['title'][:70]}", flush=True)

    json.dump({
        "go": go_version, "gitleaks": gl_version, "reps": REPS,
        "gates": [{"id": g, "label": l, "kind": k} for g, l, k in GATES],
        "cases": list(results.values()),
    }, open(os.path.join(WORK, "results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
