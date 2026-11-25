#!/usr/bin/env python3
"""Seeded benchmark: secrets in hexdumps that AI agents print into their logs.

Usage:
  python3 scripts/agent-log-hexdumps/bench.py --work <scratch-dir> [--repeats 3]

Follow-up to scripts/agent_log_secret_leak_bench.py, which found that an
`xxd .env` in an agent transcript got past every defence it measured. This
script asks the obvious next questions: is that true for the other dump tools
an agent reaches for, and does turning the dump back into bytes before the
redactor and the scanner see it fix it?

For every event it writes a small .env file with one fake secret (same
generator and same nine secret kinds as the earlier bench, seeded) and runs a
real command over it: cat (control), base64, xxd, xxd -p, xxd -i, xxd -b,
hexdump, hexdump -C, od, od -c and od -A x -t x1. The command's stdout becomes
one agent log record. Then it measures six defences:

  gitleaks_stored      gitleaks dir, default rules, over the stored JSONL
  gitleaks_view_tuned  gitleaks with scripts/data/agent-logs-gitleaks.toml over
                       the decoded view (record content JSON-unescaped)
  redact               the earlier bench's encoding-aware known-value redactor
                       (raw, URL, hex, base64 at 3 alignments, JSON-escaped)
  undump_redact        the same redactor, run over the bytes the dump decodes
                       back to (undump() below); a hit drops the whole output
  undump_scan          gitleaks, tuned config, over the decoded bytes
  undump_both          undump_redact or undump_scan

A secret counts as caught when a redactor removed it so the oracle cannot get
it back from what was stored, or when gitleaks reported a finding in that
event's record. The oracle is undump() plus the earlier bench's recoverable()
(raw, URL-decoded, base64, hex), checked against `xxd -r` and `xxd -r -p`.

It also runs undump() over 5,000 benign agent tool outputs (the earlier bench's
generator) and over benign dumps of random binary files, to count how often
the normaliser fires on something that is not a dump and how much noise the
scanner adds on decoded binary.

Fake secret prefixes are built in pieces (inherited from the earlier bench) so
this repository itself never matches a scanner rule. The JSON written to
scripts/data/agent-log-hexdumps.json holds counts only, no secret values.
"""
import argparse
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import time
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import agent_log_secret_leak_bench as base  # noqa: E402

SEED = 20261125
EVENTS_PER_FORMAT = 45  # 5 of each of the nine secret kinds
BENIGN_RECORDS = 5000
BENIGN_DUMPS_PER_FORMAT = 40
DATA_OUT = "scripts/data/agent-log-hexdumps.json"
TUNED_CONFIG = base.TUNED_CONFIG

# id, command (the .env path is appended), label
FORMATS = [
    ("cat", ["cat"], "cat .env (control)"),
    ("base64", ["base64", "-i"], "base64 -i .env"),
    ("xxd", ["xxd"], "xxd .env"),
    ("xxd_p", ["xxd", "-p"], "xxd -p .env"),
    ("xxd_i", ["xxd", "-i"], "xxd -i .env"),
    ("xxd_b", ["xxd", "-b"], "xxd -b .env"),
    ("hexdump", ["hexdump"], "hexdump .env"),
    ("hexdump_c", ["hexdump", "-C"], "hexdump -C .env"),
    ("od", ["od"], "od .env"),
    ("od_c", ["od", "-c"], "od -c .env"),
    ("od_x1", ["od", "-A", "x", "-t", "x1"], "od -A x -t x1 .env"),
]
DUMP_FORMATS = [f for f in FORMATS if f[0] not in ("cat", "base64")]

DEFENCES = [
    ("gitleaks_stored", "gitleaks, default rules, stored JSONL"),
    ("gitleaks_view_tuned", "gitleaks, tuned config, decoded view"),
    ("redact", "Encoding-aware known-value redaction"),
    ("undump_redact", "Undump, then known-value redaction"),
    ("undump_scan", "Undump, then gitleaks (tuned)"),
    ("undump_both", "Undump, then redaction + gitleaks"),
]

DROP = "[REDACTED: %d-byte dump held a known secret]"


# ------------------------------------------------------------ undump
OD_ESC = {"\\0": 0, "\\a": 7, "\\b": 8, "\\f": 12, "\\n": 10, "\\r": 13, "\\t": 9, "\\v": 11}


def _rows(text, pat):
    """Lines of text that match pat; None unless every non-empty line does (a lone '*' is allowed)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    out = []
    for ln in lines:
        if ln.strip() == "*":
            out.append(None)
            continue
        m = pat.match(ln)
        if not m:
            return None
        out.append(m)
    return out


def _fill(rows, total, spill=False):
    """rows: [(offset, bytes) or None for '*'] -> bytes, expanding '*' repeats.

    spill: a row may already hold bytes of the next one (od -c prints a
    multibyte character in full on the row where it starts)."""
    buf = bytearray()
    prev = b""
    pending = False
    for r in rows:
        if r is None:
            pending = True
            continue
        off, data = r
        if pending and prev:
            while len(buf) < off:
                buf += prev
            del buf[off:]
            pending = False
        if len(buf) != off and not (spill and off <= len(buf) <= off + 3):
            return None
        buf += data
        prev = data
    if total is not None:
        if pending and prev:
            while len(buf) < total:
                buf += prev
        if len(buf) < total:
            return None
        del buf[total:]
    return bytes(buf)


RE_XXD = re.compile(r"^([0-9a-f]{8}): ((?:[0-9a-f]{2,4} ?){1,8}) *(?:  .*)?$")
RE_XXD_B = re.compile(r"^([0-9a-f]{8}): ((?:[01]{8} ?){1,6}) *(?:  .*)?$")
RE_HEXC = re.compile(r"^([0-9a-f]{8})((?:  ?[0-9a-f]{2}){1,16}) *(?:  \|.*\|)?$")
RE_BARE = re.compile(r"^([0-9a-f]{7,8})$")
RE_HD = re.compile(r"^([0-9a-f]{7})((?: +[0-9a-f]{4}){1,8}) *$")
RE_OD_X1 = re.compile(r"^([0-9a-f]{7})((?: +[0-9a-f]{2}){1,16}) *$")
RE_OD = re.compile(r"^([0-7]{7})((?: +[0-7]{6}){1,8}) *$")
RE_XXD_P = re.compile(r"^[0-9a-f]{2,}$")
RE_XXD_I = re.compile(r"^\s*(?:0x[0-9a-f]{2}(?:, ?|,?$))+\s*$")


def _split_end(text, offset_base, offset_re=RE_BARE):
    """Split hexdump/od output into data lines and the trailing total-length line."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2 or not re.match(r"^[0-9a-f]{7,8}$", lines[-1]):
        return None, None
    try:
        total = int(lines[-1], offset_base)
    except ValueError:
        return None, None
    return "\n".join(lines[:-1]), total


def undump_xxd(text):
    rows = _rows(text, RE_XXD)
    if not rows:
        return None
    return _fill([None if m is None else (int(m.group(1), 16), bytes.fromhex(m.group(2).replace(" ", ""))) for m in rows], None)


def undump_xxd_b(text):
    rows = _rows(text, RE_XXD_B)
    if not rows:
        return None
    return _fill([None if m is None else (int(m.group(1), 16), bytes(int(b, 2) for b in m.group(2).split())) for m in rows], None)


def undump_xxd_p(text):
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines or not all(RE_XXD_P.match(ln) for ln in lines):
        return None
    joined = "".join(lines)
    # A lone hash or digest line is hex too; require the xxd -p shape: full 60-char
    # rows except the last one, and more than one row or a row that decodes to text.
    if len(joined) % 2 or any(len(ln) != 60 for ln in lines[:-1]):
        return None
    data = bytes.fromhex(joined)
    if len(lines) == 1 and sum(32 <= b < 127 or b in (9, 10, 13) for b in data) < 0.9 * len(data):
        return None
    return data


def undump_xxd_i(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    body = [ln for ln in lines if not re.match(r"^(unsigned|\};)", ln.strip())]
    if not body or not all(RE_XXD_I.match(ln) for ln in body):
        return None
    return bytes(int(h, 16) for h in re.findall(r"0x([0-9a-f]{2})", "\n".join(body)))


def undump_hexdump_c(text):
    data, total = _split_end(text, 16)
    if data is None:
        return None
    rows = _rows(data, RE_HEXC)
    if not rows:
        return None
    return _fill([None if m is None else (int(m.group(1), 16), bytes.fromhex(m.group(2).replace(" ", ""))) for m in rows], total)


def undump_hexdump(text):
    data, total = _split_end(text, 16)
    if data is None:
        return None
    rows = _rows(data, RE_HD)
    if not rows:
        return None
    parsed = []
    for m in rows:
        if m is None:
            parsed.append(None)
            continue
        words = m.group(2).split()
        parsed.append((int(m.group(1), 16), b"".join(int(w, 16).to_bytes(2, "little") for w in words)))
    return _fill(parsed, total)


def undump_od_x1(text):
    data, total = _split_end(text, 16)
    if data is None:
        return None
    rows = _rows(data, RE_OD_X1)
    if not rows:
        return None
    return _fill([None if m is None else (int(m.group(1), 16), bytes.fromhex(m.group(2).replace(" ", ""))) for m in rows], total)


def undump_od(text):
    data, total = _split_end(text, 8)
    if data is None:
        return None
    rows = _rows(data, RE_OD)
    if not rows:
        return None
    parsed = []
    for m in rows:
        if m is None:
            parsed.append(None)
            continue
        parsed.append((int(m.group(1), 8), b"".join(int(w, 8).to_bytes(2, "little") for w in m.group(2).split())))
    return _fill(parsed, total)


def _columns(text):
    """Map display column -> character. od -c pads each cell to 4 columns by wcwidth():
    wide characters take two columns and combining marks none."""
    out, col = {}, 0
    for ch in text:
        if (unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf")) and col:
            # Zero width: od padded its cell with four spaces, so the mark
            # belongs to the column before it.
            out[col - 1] = out[col - 1].strip() + ch
            continue
        out[col] = ch
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            col += 2
        else:
            col += 1
    return out


def undump_od_c(text):
    data, total = _split_end(text, 8)
    if data is None:
        return None
    lines = [ln for ln in data.splitlines() if ln.strip()]
    parsed = []
    for ln in lines:
        if ln.strip() == "*":
            parsed.append(None)
            continue
        if not re.match(r"^[0-7]{7}(?: |$)", ln):
            return None
        off = int(ln[:7], 8)
        cells = _columns(ln[8:])
        out = bytearray()
        for i in range(16):
            c = "".join(cells.get(col, " ") for col in range(i * 4, i * 4 + 4))
            s = c.strip()
            if c == "    ":
                out.append(32)
            elif s in OD_ESC:
                out.append(OD_ESC[s])
            elif re.match(r"^[0-7]{3}$", s):
                out.append(int(s, 8))
            elif s == "**":
                pass  # continuation byte of the multibyte character printed in an earlier cell
            elif len(s) == 1:
                # A printable character, or the first cell of a multibyte one:
                # it stands for all of its bytes, and the "**" cells after it
                # (possibly on the next row) for none.
                out += s.encode("utf-8")
            else:
                return None
        parsed.append((off, bytes(out)))
    # Rows hold 16 cells; the last row is padded with blank cells, which the
    # total-length line trims.
    return _fill(parsed, total, spill=True)


UNDUMPERS = [
    ("xxd_b", undump_xxd_b), ("xxd", undump_xxd), ("xxd_i", undump_xxd_i), ("xxd_p", undump_xxd_p),
    ("hexdump_c", undump_hexdump_c), ("hexdump", undump_hexdump), ("od_x1", undump_od_x1),
    ("od", undump_od), ("od_c", undump_od_c),
]


def undump(text):
    """Return (format id, bytes) when text is a whole dump in one of nine layouts, else (None, None)."""
    for name, fn in UNDUMPERS:
        try:
            data = fn(text)
        except (ValueError, OverflowError):
            data = None
        if data:
            return name, data
    return None, None


# ------------------------------------------------------------ corpus
def env_file(g, rng, kind, v):
    name = base.ENV_NAME[kind]
    lines = ["# local overrides - do not commit", "LOG_LEVEL=debug", "%s=%s" % (name, v), "FEATURE_FLAGS=search,v2"]
    extra = rng.choice([[], ["PORT=8080"], ["REGION=eu-west-1", "PORT=8080"], ["DATABASE_POOL=10"]])
    head, tail = lines[:2] + extra[: len(extra) // 2], extra[len(extra) // 2:] + lines[3:]
    return ("\n".join(head + [lines[2]] + tail) + "\n").encode()


def run_tool(cmd, path):
    res = subprocess.run(cmd + [path], capture_output=True, check=True, cwd=os.path.dirname(path))
    # Agent runtimes store tool output as UTF-8 text. od -c prints a valid
    # multibyte sequence as the character followed by "**" cells.
    return res.stdout.decode("utf-8", errors="replace")


def recoverable(text, v):
    if base.recoverable(text, v):
        return True
    _, data = undump(text)
    return bool(data) and v.encode() in data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--repeats", type=int, default=3)
    a = ap.parse_args()
    work = os.path.abspath(a.work)
    if os.path.isdir(work):
        shutil.rmtree(work)
    files = os.path.join(work, "files")
    cap = os.path.join(work, "capture")
    for d in (files, cap):
        os.makedirs(d)

    rng = random.Random(SEED)
    g = base.Gen(rng)
    kinds = base.NON_PEM
    events = []
    for fid, cmd, label in FORMATS:
        for j in range(EVENTS_PER_FORMAT):
            kind = kinds[j % len(kinds)]
            v = g.secret(kind)
            known = [v] + [g.secret(rng.choice(kinds)) for _ in range(base.EXTRA_KNOWN_PER_SESSION)]
            ev_dir = os.path.join(files, "%s-%03d" % (fid, j))
            os.makedirs(ev_dir)
            path = os.path.join(ev_dir, ".env")
            raw = env_file(g, rng, kind, v)
            with open(path, "wb") as fh:
                fh.write(raw)
            out = run_tool(cmd, path)
            if fid == "xxd_i":
                # xxd -i names the array after the file; an agent usually pipes it.
                out = subprocess.run(["xxd", "-i"], input=raw, capture_output=True, check=True).stdout.decode("utf-8", errors="replace")
            events.append({"id": len(events), "format": fid, "kind": kind, "secret": v, "known": known,
                           "raw": raw, "cmd": " ".join(cmd + [".env"]), "out": out})

    # The oracle and undump() must agree with the real reverse tools.
    xxd_r = {"ok": 0, "n": 0}
    for e in events:
        if e["format"] in ("xxd", "xxd_p"):
            flag = ["-r"] if e["format"] == "xxd" else ["-r", "-p"]
            back = subprocess.run(["xxd"] + flag, input=e["out"].encode("latin-1"), capture_output=True, check=True).stdout
            xxd_r["n"] += 1
            xxd_r["ok"] += back == e["raw"]
    undump_exact = {}
    for e in events:
        fmt, data = undump(e["out"])
        row = undump_exact.setdefault(e["format"], {"exact": 0, "detected_as": {}})
        row["exact"] += data == e["raw"]
        row["detected_as"][fmt or "none"] = row["detected_as"].get(fmt or "none", 0) + 1
    sanity = sum(recoverable(e["out"], e["secret"]) for e in events)

    # Stored JSONL and decoded view, one file per event.
    def write_views(tag, content_of):
        stored = os.path.join(work, tag + "-stored")
        view = os.path.join(work, tag + "-view")
        for d in (stored, view):
            if os.path.isdir(d):
                shutil.rmtree(d)
            os.makedirs(d)
        for e in events:
            c = content_of(e)
            if c is None:
                continue
            name = "ev-%04d" % e["id"]
            with open(os.path.join(stored, name + ".jsonl"), "w") as fh:
                fh.write(json.dumps({"type": "tool_call", "tool": "shell", "args": {"cmd": e["cmd"]}}) + "\n")
                fh.write(json.dumps({"type": "tool_result", "tool": "shell", "content": c}) + "\n")
            with open(os.path.join(view, name + ".txt"), "w", encoding="latin-1") as fh:
                fh.write(c)
        return stored, view

    def hits(findings):
        out = {}
        for f in findings:
            m = re.match(r"ev-(\d+)\.", os.path.basename(f["File"]))
            if m:
                out.setdefault(int(m.group(1)), []).append(f["RuleID"])
        return out

    stored, view = write_views("raw", lambda e: e["out"])
    scan_times = []
    for _ in range(a.repeats):
        f_stored, took = base.gitleaks(stored, os.path.join(cap, "gitleaks-stored.json"))
        scan_times.append(took)
    f_view, _ = base.gitleaks(view, os.path.join(cap, "gitleaks-view-tuned.json"), TUNED_CONFIG)

    t = time.time()
    decoded = {}
    for _ in range(a.repeats):
        for e in events:
            decoded[e["id"]] = undump(e["out"])
    undump_secs = (time.time() - t) / a.repeats
    out_bytes = sum(len(e["out"]) for e in events)

    _, undump_view = write_views("undump", lambda e: decoded[e["id"]][1].decode("latin-1") if decoded[e["id"]][1] else None)
    f_undump, _ = base.gitleaks(undump_view, os.path.join(cap, "gitleaks-undump-tuned.json"), TUNED_CONFIG)

    h_stored, h_view, h_undump = hits(f_stored), hits(f_view), hits(f_undump)
    rules_stored = {}
    for rs in h_stored.values():
        for r in rs:
            rules_stored[r] = rules_stored.get(r, 0) + 1
    decode_tags = {}
    for f in f_stored:
        for tag in f.get("Tags") or []:
            if tag.startswith("decoded:"):
                decode_tags[tag] = decode_tags.get(tag, 0) + 1

    per = {fid: {d: 0 for d, _ in DEFENCES} for fid, _, _ in FORMATS}
    stored_after = {}
    for e in events:
        red = base.Redactor(e["known"], encodings=True)
        c = e["out"]
        r_out = red.redact(c)
        fmt, data = decoded[e["id"]]
        u_out = c
        if data is not None:
            plain = data.decode("latin-1")
            if red.redact(plain) != plain:
                u_out = DROP % len(data)
        u_out = red.redact(u_out)
        caught = {
            "gitleaks_stored": e["id"] in h_stored,
            "gitleaks_view_tuned": e["id"] in h_view,
            "redact": not recoverable(r_out, e["secret"]),
            "undump_redact": not recoverable(u_out, e["secret"]),
            "undump_scan": e["id"] in h_undump,
        }
        caught["undump_both"] = caught["undump_redact"] or caught["undump_scan"]
        for d, ok in caught.items():
            per[e["format"]][d] += ok
        stored_after[e["id"]] = u_out

    # Normaliser on things that are not dumps, and scanner noise on benign dumps.
    brng = random.Random(SEED + 1)
    bg = base.Gen(brng)
    fired = {}
    for _ in range(BENIGN_RECORDS):
        tool, args, content = base.benign_record(bg, brng.choice(["orders", "billing", "search", "gateway", "notify"]))
        fmt, data = undump(content or "")
        if fmt:
            fired[fmt] = fired.get(fmt, 0) + 1
    bdir = os.path.join(work, "benign-dumps")
    os.makedirs(bdir)
    benign_ok, benign_n, benign_redacted = {}, 0, 0
    for fid, cmd, label in DUMP_FORMATS:
        for j in range(BENIGN_DUMPS_PER_FORMAT):
            blob = bytes(brng.getrandbits(8) for _ in range(brng.randrange(256, 2049)))
            p = os.path.join(bdir, "%s-%02d.bin" % (fid, j))
            with open(p, "wb") as fh:
                fh.write(blob)
            out = run_tool(cmd, p)
            fmt, data = undump(out)
            benign_n += 1
            benign_ok[fid] = benign_ok.get(fid, 0) + (data == blob)
            known = [bg.secret(brng.choice(kinds)) for _ in range(base.EXTRA_KNOWN_PER_SESSION)]
            red = base.Redactor(known, encodings=True)
            if data is not None and red.redact(data.decode("latin-1")) != data.decode("latin-1"):
                benign_redacted += 1
            with open(os.path.join(bdir, "%s-%02d.txt" % (fid, j)), "w", encoding="latin-1") as fh:
                fh.write(data.decode("latin-1") if data else "")
            os.remove(p)
    f_benign, _ = base.gitleaks(bdir, os.path.join(cap, "gitleaks-benign-dumps.json"), TUNED_CONFIG)

    # Captures for the post's terminal panels: one GitHub token through xxd.
    ex = next(e for e in events if e["format"] == "xxd" and e["kind"] == "github_pat")
    ex_dir = os.path.join(work, "example")
    os.makedirs(ex_dir)
    with open(os.path.join(ex_dir, ".env"), "wb") as fh:
        fh.write(ex["raw"])
    with open(os.path.join(ex_dir, "session.jsonl"), "w") as fh:
        fh.write(json.dumps({"type": "tool_result", "tool": "shell", "content": ex["out"]}) + "\n")
    gl = subprocess.run(["gitleaks", "dir", "session.jsonl", "--no-banner", "--no-color", "--redact", "--exit-code", "0"],
                        capture_output=True, text=True, cwd=ex_dir)
    with open(os.path.join(ex_dir, "session-undumped.txt"), "w", encoding="latin-1") as fh:
        fh.write(decoded[ex["id"]][1].decode("latin-1"))
    gl2 = subprocess.run(["gitleaks", "dir", "session-undumped.txt", "--no-banner", "--no-color", "--redact", "-v",
                          "--exit-code", "0", "-c", os.path.abspath(TUNED_CONFIG)], capture_output=True, text=True, cwd=ex_dir)
    with open(os.path.join(cap, "example.json"), "w") as fh:
        json.dump({"cmd": ex["cmd"], "out": ex["out"], "gitleaks_stored": gl.stdout + gl.stderr,
                   "gitleaks_undumped": gl2.stdout + gl2.stderr, "stored_after": stored_after[ex["id"]]}, fh, indent=1)

    totals = {d: sum(per[f][d] for f, _, _ in DUMP_FORMATS) for d, _ in DEFENCES}
    data = {
        "generated_by": "scripts/agent-log-hexdumps/bench.py",
        "seed": SEED,
        "events_per_format": EVENTS_PER_FORMAT,
        "events": len(events),
        "dump_events": EVENTS_PER_FORMAT * len(DUMP_FORMATS),
        "secret_kinds": kinds,
        "formats": [{"id": f, "label": lbl, "cmd": " ".join(c + [".env"]), "caught": per[f],
                     "undump_exact": undump_exact[f]["exact"], "undump_detected_as": undump_exact[f]["detected_as"]}
                    for f, c, lbl in FORMATS],
        "defences": [{"id": d, "label": lbl} for d, lbl in DEFENCES],
        "totals_dump_formats": totals,
        "oracle_sanity_recoverable": sanity,
        "xxd_reverse_roundtrip": xxd_r,
        "gitleaks_version": subprocess.run(["gitleaks", "version"], capture_output=True, text=True).stdout.strip(),
        "xxd_version": subprocess.run(["xxd", "-v"], capture_output=True, text=True).stderr.strip() or
        subprocess.run(["xxd", "-v"], capture_output=True, text=True).stdout.strip(),
        "gitleaks_rules_stored": rules_stored,
        "gitleaks_decode_tags_stored": decode_tags,
        "benign_records_checked": BENIGN_RECORDS,
        "undump_fired_on_benign_records": fired,
        "benign_dumps": benign_n,
        "benign_dumps_per_format": BENIGN_DUMPS_PER_FORMAT,
        # macOS od -c prints a multibyte character that starts in the last
        # cell of a row as its second byte's octal, so a few binary od -c
        # dumps cannot be reversed exactly by anyone.
        "benign_dumps_undumped_exact": benign_ok,
        "benign_dumps_dropped_by_redactor": benign_redacted,
        "gitleaks_findings_on_benign_dumps_undumped": len(f_benign),
        "gitleaks_rules_on_benign_dumps": sorted({f["RuleID"] for f in f_benign}),
        "timing": {
            "gitleaks_scan_stored_seconds_median": round(statistics.median(scan_times), 3),
            "undump_seconds_all_events": round(undump_secs, 4),
            "dump_output_bytes": out_bytes,
            "undump_mb_per_second": round(out_bytes / 1e6 / undump_secs, 1),
        },
        "repeats": a.repeats,
        "platform": subprocess.run(["uname", "-sm"], capture_output=True, text=True).stdout.strip(),
    }
    with open(DATA_OUT, "w") as fh:
        json.dump(data, fh, indent=1)
        fh.write("\n")
    print("oracle sanity: %d/%d recoverable; xxd -r round trip %d/%d" % (sanity, len(events), xxd_r["ok"], xxd_r["n"]))
    for f in data["formats"]:
        print("%-22s undump exact %2d/%d  %s" % (f["label"], f["undump_exact"], EVENTS_PER_FORMAT,
                                                  " ".join("%s=%d" % (k, v) for k, v in f["caught"].items())))
    print("totals over %d dump events:" % data["dump_events"], totals)
    print("undump fired on benign records:", fired, "benign dumps exact %d/%d, gitleaks findings %d" % (
        sum(benign_ok.values()), benign_n, len(f_benign)))
    print("timing:", data["timing"])
    print("wrote", DATA_OUT)


if __name__ == "__main__":
    main()
