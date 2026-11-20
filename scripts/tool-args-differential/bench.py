#!/usr/bin/env python3
"""Tool-call argument differential bench: does the gate judge the same JSON the executor runs?

    python3 scripts/tool-args-differential/bench.py <work-dir>

Needs: cargo (serde 1.0.229 + serde_json 1.0.154, from crates.io or the local
cache; CARGO_NET_OFFLINE=true works), go >= 1.27 (encoding/json/v2), node, jq.

What it does, all locally and for real:
  1. Builds a sandbox root: workspace/ with ordinary files, secrets/canary.env
     holding a fresh random canary, and workspace/link -> ../secrets.
  2. Writes a corpus of `read_file` argument strings (raw JSON text, as tool
     calls deliver them): benign controls plus 9 families of payloads that try
     to make the gate and the executor read different paths.
  3. Runs seven policy gates over the corpus. Each parses the arguments its own
     way, extracts `path` and applies the same rule (relative path starting
     with workspace/, no ".." component). Each gate is scored fail-closed
     (no path seen -> deny) and fail-open (deny only a path it sees and dislikes).
  4. Runs five Rust executors (serde variants) over the corpus; each really opens
     the file it extracted. A read whose first line is the canary is a leak.
  5. Repeats step 4 with the gate forwarding its own canonical re-serialisation
     {"path": <what the gate saw>} instead of the model's bytes.
Writes <work-dir>/cells.json (every payload x gate x executor) and the summary
scripts/data/tool-args-differential.json.
"""
import base64
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WORK = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "tool-args-work")
DATA = os.path.join(REPO, "scripts/data/tool-args-differential.json")

GOOD = ["workspace/README.md", "workspace/src/main.rs", "workspace/Cargo.toml"]
BAD = ["secrets/canary.env", "workspace/../secrets/canary.env"]


def policy_ok(p):
    return p.startswith("workspace/") and ".." not in p.split("/")


# ---------------------------------------------------------------- corpus
def corpus():
    """(family, description, raw argument text). Raw text is built by hand so
    duplicate keys, escapes and trailing bytes survive."""
    J = lambda s: json.dumps(s)
    out = []
    for g in GOOD:
        out.append(("benign", "plain path", '{"path": %s}' % J(g)))
        out.append(("benign", "path plus declared reason", '{"path": %s, "reason": "check the handler"}' % J(g)))
        out.append(("benign", "path plus undeclared key", '{"path": %s, "explanation": "check the handler"}' % J(g)))
    for g in GOOD:
        for b in BAD:
            out += [
                ("duplicate-key", "good first, bad last", '{"path": %s, "path": %s}' % (J(g), J(b))),
                ("duplicate-key", "bad first, good last", '{"path": %s, "path": %s}' % (J(b), J(g))),
                ("case-variant", "bad path, good PATH", '{"path": %s, "PATH": %s}' % (J(b), J(g))),
                ("case-variant", "bad path, good Path", '{"path": %s, "Path": %s}' % (J(b), J(g))),
                ("alias-key", "only file_path, bad", '{"file_path": %s}' % J(b)),
                ("alias-key", "only filename, bad", '{"filename": %s}' % J(b)),
                ("escaped-key", "p\\u0061th bad, then path good", '{"p\\u0061th": %s, "path": %s}' % (J(b), J(g))),
                ("escaped-key", "path good, then p\\u0061th bad", '{"path": %s, "p\\u0061th": %s}' % (J(g), J(b))),
                ("escaped-value", "dots as \\u002e", '{"path": "workspace/\\u002e\\u002e/secrets/canary.env"}'),
                ("escaped-value", "slash as \\/ and dots as \\u002e", '{"path": "workspace\\/\\u002e\\u002e\\/secrets\\/canary.env"}'),
                ("trailing-data", "second object after the first", '{"path": %s}{"path": %s}' % (J(g), J(b))),
                ("trailing-data", "second object, bad first", '{"path": %s}{"path": %s}' % (J(b), J(g))),
                ("type-confusion", "path as array", '{"path": [%s, %s]}' % (J(g), J(b))),
                ("bad-unicode", "lone surrogate in value", '{"path": "%s\\ud800"}' % b),
                ("bad-unicode", "NUL then traversal", '{"path": "%s\\u0000/../../%s"}' % (g, b)),
            ]
    for g in ["workspace/link/canary.env", "workspace/link/../link/canary.env"]:
        out.append(("symlink", "workspace/link -> ../secrets", '{"path": %s}' % J(g)))
    # dedupe while keeping order
    seen, uniq = set(), []
    for fam, desc, raw in out:
        if raw not in seen:
            seen.add(raw)
            uniq.append((fam, desc, raw))
    return uniq


# ---------------------------------------------------------------- gates
def gate_python(raws):
    res = []
    for r in raws:
        try:
            a = json.loads(r)
            p = a.get("path") if isinstance(a, dict) else None
            res.append({"path": p if isinstance(p, str) else None, "err": ""})
        except ValueError as e:
            res.append({"path": None, "err": str(e)})
    return res


REGEX = re.compile(r'"path"\s*:\s*"([^"]*)"')


def gate_regex(raws):
    res = []
    for r in raws:
        m = REGEX.search(r)
        res.append({"path": m.group(1) if m else None, "err": ""})
    return res


def run_lines(cmd):
    t = time.time()
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return [json.loads(l) for l in out.splitlines() if l.strip()], time.time() - t


def write_b64(path, raws):
    with open(path, "w") as f:
        for r in raws:
            f.write(base64.b64encode(r.encode("utf-8", "surrogatepass")).decode() + "\n")


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    log = open(os.path.join(WORK, "bench.txt"), "w")
    global print
    _print = print
    def print(*a, **k):  # noqa: A001 - tee to <work-dir>/bench.txt for the terminal image
        _print(*a, **k)
        _print(*a, **dict(k, file=log, flush=True))
    bin_dir = os.path.join(WORK, "bin")
    os.makedirs(bin_dir)
    env = dict(os.environ, CARGO_TARGET_DIR=os.path.join(WORK, "target"))
    subprocess.run(["cargo", "build", "--release", "-q", "--manifest-path", os.path.join(HERE, "toolexec/Cargo.toml")], check=True, env=env)
    lock = os.path.join(HERE, "toolexec/Cargo.lock")
    if os.path.exists(lock):
        os.remove(lock)
    toolexec = os.path.join(WORK, "target/release/toolexec")
    gogate = os.path.join(bin_dir, "gogate")
    subprocess.run(["go", "build", "-o", gogate, "."], check=True, cwd=os.path.join(HERE, "gogate"))

    # sandbox root
    root = os.path.join(WORK, "root")
    os.makedirs(os.path.join(root, "workspace/src"))
    os.makedirs(os.path.join(root, "secrets"))
    canary = "CANARY_TOKEN=tooldiff-" + secrets.token_hex(8)
    files = {"workspace/README.md": "# demo crate\n", "workspace/src/main.rs": "fn main() {}\n",
             "workspace/Cargo.toml": "[package]\nname = \"demo\"\n", "secrets/canary.env": canary + "\n"}
    for k, v in files.items():
        with open(os.path.join(root, k), "w") as f:
            f.write(v)
    os.symlink("../secrets", os.path.join(root, "workspace/link"))

    items = corpus()
    raws = [r for _, _, r in items]
    pay = os.path.join(WORK, "payloads.b64")
    write_b64(pay, raws)
    with open(os.path.join(WORK, "payloads.jsonl"), "w") as f:
        for fam, desc, raw in items:
            f.write(json.dumps({"family": fam, "desc": desc, "raw": raw}) + "\n")

    gates = {}
    t = time.time(); gates["python json.loads"] = gate_python(raws); gt = {"python json.loads": time.time() - t}
    t = time.time(); gates["regex on raw text"] = gate_regex(raws); gt["regex on raw text"] = time.time() - t
    gates["node JSON.parse"], gt["node JSON.parse"] = run_lines(["node", os.path.join(HERE, "gate.mjs"), pay])
    gates["go encoding/json"], gt["go encoding/json"] = run_lines([gogate, "v1", pay])
    gates["go encoding/json/v2"], gt["go encoding/json/v2"] = run_lines([gogate, "v2", pay])
    gates["bash + jq -r .path"], gt["bash + jq -r .path"] = run_lines(["bash", os.path.join(HERE, "gate_jq.sh"), pay])
    gates["rust serde_json::Value"], gt["rust serde_json::Value"] = run_lines([toolexec, "gate", "rust-value", pay])
    for name, rows in gates.items():
        assert len(rows) == len(raws), (name, len(rows))

    executors = ["typed", "typed-deny", "alias", "value", "typed-deny-checked"]
    ex = {}
    for v in executors:
        ex[v], _ = run_lines([toolexec, "exec", v, root, pay])

    def leaked(row):
        return row["status"] == "read" and row.get("sha_head", "").startswith("CANARY_TOKEN=")

    # canonical forwarding: each gate's own view, re-serialised
    canon = {}
    for gname, rows in gates.items():
        fwd = [json.dumps({"path": r["path"]}) if r["path"] is not None else "{}" for r in rows]
        cp = os.path.join(WORK, "canon-%d.b64" % len(canon))
        write_b64(cp, fwd)
        canon[gname] = {v: run_lines([toolexec, "exec", v, root, cp])[0] for v in executors}

    cells = []
    for i, (fam, desc, raw) in enumerate(items):
        for gname, rows in gates.items():
            p = rows[i]["path"]
            seen_ok = p is not None and policy_ok(p)
            for mode in ("closed", "open"):
                allow = seen_ok if mode == "closed" else (p is None or seen_ok)
                for v in executors:
                    cells.append({
                        "i": i, "family": fam, "desc": desc, "gate": gname, "mode": mode, "executor": v,
                        "gate_path": p, "allow": allow,
                        "exec_status": ex[v][i]["status"], "exec_path": ex[v][i].get("path"),
                        "leak": allow and leaked(ex[v][i]),
                        "leak_canonical": allow and leaked(canon[gname][v][i]),
                        "benign_read": allow and ex[v][i]["status"] == "read",
                        "benign_read_canonical": allow and canon[gname][v][i]["status"] == "read",
                    })
    with open(os.path.join(WORK, "cells.json"), "w") as f:
        json.dump({"canary_prefix": "CANARY_TOKEN=", "cells": cells}, f)

    # summary
    fams = []
    for fam, _, _ in items:
        if fam not in fams:
            fams.append(fam)
    count = lambda pred: sum(1 for c in cells if pred(c))
    gate_names = list(gates)
    summary = {
        "generated": time.strftime("%Y-%m-%d"),
        "host": subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip(),
        "versions": {
            "rustc": subprocess.run(["rustc", "--version"], capture_output=True, text=True).stdout.strip(),
            "serde_json": "1.0.154", "serde": "1.0.229",
            "go": subprocess.run(["go", "version"], capture_output=True, text=True).stdout.strip(),
            "node": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip(),
            "jq": subprocess.run(["jq", "--version"], capture_output=True, text=True).stdout.strip(),
            "python": sys.version.split()[0],
        },
        "payloads": len(items),
        "families": {f: sum(1 for x in items if x[0] == f) for f in fams},
        "gates": gate_names,
        "executors": executors,
        "leaks": {
            mode: {g: {v: count(lambda c, g=g, v=v, mode=mode: c["gate"] == g and c["mode"] == mode and c["executor"] == v and c["leak"])
                       for v in executors} for g in gate_names}
            for mode in ("closed", "open")},
        "leaks_canonical": {
            mode: {g: {v: count(lambda c, g=g, v=v, mode=mode: c["gate"] == g and c["mode"] == mode and c["executor"] == v and c["leak_canonical"])
                       for v in executors} for g in gate_names}
            for mode in ("closed", "open")},
        "leaks_by_family": {
            mode: {f: {v: count(lambda c, f=f, v=v, mode=mode: c["family"] == f and c["mode"] == mode and c["executor"] == v and c["leak"])
                       for v in executors} for f in fams}
            for mode in ("closed", "open")},
        "benign_allowed_and_read": {g: {v: count(lambda c, g=g, v=v: c["gate"] == g and c["mode"] == "closed" and c["executor"] == v and c["family"] == "benign" and c["benign_read"])
                                        for v in executors} for g in gate_names},
        "benign_allowed_and_read_canonical": {g: {v: count(lambda c, g=g, v=v: c["gate"] == g and c["mode"] == "closed" and c["executor"] == v and c["family"] == "benign" and c["benign_read_canonical"])
                                                  for v in executors} for g in gate_names},
        "benign_total": sum(1 for x in items if x[0] == "benign"),
        "gate_seconds": {g: round(s, 4) for g, s in gt.items()},
        "gate_views": {g: [r["path"] for r in rows] for g, rows in gates.items()},
        "exec_views": {v: [r.get("path") if r["status"] != "reject" else None for r in ex[v]] for v in executors},
        "exec_status": {v: [r["status"] for r in ex[v]] for v in executors},
        "corpus": [{"family": f, "desc": d, "raw": r} for f, d, r in items],
    }
    # parse cost of each executor variant: 5 runs of 1M calls, medians
    reps = []
    for _ in range(5):
        out = subprocess.run([toolexec, "bench", "1000000"], check=True, capture_output=True, text=True).stdout
        reps.append({tuple(l.split("\t")[:2]): float(l.split("\t")[2]) for l in out.splitlines()[1:]})
    summary["parse_ns_median"] = {"%s/%s" % k: sorted(r[k] for r in reps)[2] for k in reps[0]}
    summary["parse_ns_runs"] = {"%s/%s" % k: [r[k] for r in reps] for k in reps[0]}
    with open(DATA, "w") as f:
        json.dump(summary, f, indent=1)
        f.write("\n")
    write_report(summary, items, gates, ex)
    print("payloads", len(items), "cells", len(cells))
    for mode in ("closed", "open"):
        print("== leaks, fail-%s gates (rows) x executors (cols): %s" % (mode, " ".join(executors)))
        for g in gate_names:
            print("  %-24s %s" % (g, " ".join("%3d" % summary["leaks"][mode][g][v] for v in executors)))
        print("  canonical forwarding total:", sum(summary["leaks_canonical"][mode][g][v] for g in gate_names for v in executors))


def write_report(summary, items, gates, ex):
    """<work-dir>/report.html: one row per payload, what each gate saw and
    decided (fail-closed) and what each executor read. Screenshot it with shots.sh."""
    import html
    h = lambda s: html.escape(s if s is not None else "")
    gnames = summary["gates"]
    exs = summary["executors"]
    rows = []
    for i, (fam, desc, raw) in enumerate(items):
        cells = []
        for g in gnames:
            p = gates[g][i]["path"]
            ok = p is not None and policy_ok(p)
            cells.append('<td class="%s" title="%s">%s</td>' % ("allow" if ok else "deny", h(repr(p)), "allow" if ok else "deny"))
        for v in exs:
            r = ex[v][i]
            st = r["status"]
            if st == "read" and r.get("sha_head", "").startswith("CANARY_TOKEN="):
                st = "CANARY"
            cells.append('<td class="x-%s">%s</td>' % (st.lower(), st))
        rows.append('<tr><td class="fam">%s</td><td class="raw"><code>%s</code></td>%s</tr>' % (h(fam), h(raw), "".join(cells)))
    head = "".join("<th>%s</th>" % h(g) for g in gnames) + "".join("<th>serde %s</th>" % h(v) for v in exs)
    doc = """<!doctype html><meta charset="utf-8"><title>tool-args differential</title>
<style>
body{font:13px -apple-system,Helvetica,Arial,sans-serif;background:#0d1117;color:#e6edf3;margin:16px}
h1{font-size:18px;margin:0 0 4px} p{color:#8b949e;margin:0 0 12px}
table{border-collapse:collapse} th,td{border:1px solid #30363d;padding:3px 6px;text-align:center}
th{background:#161b22;font-weight:600;font-size:12px;max-width:90px}
td.raw{text-align:left;max-width:520px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
td.fam{text-align:left;color:#8b949e}
code{font:12px Menlo,monospace}
.allow{background:#12361f;color:#56d364}.deny{background:#3d1d1d;color:#ff7b72}
.x-read{color:#8b949e}.x-reject,.x-error{color:#6e7681}.x-canary{background:#da3633;color:#fff;font-weight:700}
</style>
<h1>read_file arguments: what the gate judged vs what serde executed</h1>
<p>%d payloads; gate columns show the fail-closed decision; executor columns show what the Rust handler really opened (CANARY = it read secrets/canary.env). Red CANARY in a row with a green allow is a bypass.</p>
<table><tr><th>family</th><th>raw arguments</th>%s</tr>%s</table>""" % (len(items), head, "".join(rows))
    with open(os.path.join(WORK, "report.html"), "w") as f:
        f.write(doc)


if __name__ == "__main__":
    main()
