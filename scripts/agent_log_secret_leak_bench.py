#!/usr/bin/env python3
"""Seeded benchmark: how secrets end up in AI agent logs, and what catches them.

Usage:
  python3 scripts/agent_log_secret_leak_bench.py --work <scratch-dir> [--model <file.gguf>] [--repeats 3]

It generates a corpus of agent session logs (JSONL, one record per line, the
way most agent runtimes write transcripts) with fake secrets planted in eleven
"leak shapes", writes the corpus three ways (no redaction, naive known-value
redaction, encoding-aware known-value redaction with a streaming holdback),
scans the stored JSONL with gitleaks, scans a decoded view of the same logs
(record content JSON-unescaped, streamed deltas reassembled) with gitleaks,
and checks every planted secret with a recovery oracle (raw, percent-decoding,
base64 at any offset, hex, xxd reversal, reassembled stream deltas).

Every secret is a generated fake built from a fixed seed at run time. None is
written into the repository: scripts/data/agent-log-secret-leaks.json holds
aggregates only, and <scratch-dir>/capture/ (gitleaks output with --redact,
one token-split example) is read by scripts/gen_agent_log_secrets_post_images.py.

Needs gitleaks on PATH. With --model and llama-tokenize (llama.cpp) on PATH the
streamed-reply shape is split by the model's real tokenizer; without them it
falls back to 4-character chunks.
"""
import argparse
import base64
import json
import os
import random
import re
import shutil
import statistics
import string
import subprocess
import time
from collections import Counter
from urllib.parse import quote, quote_plus, unquote, unquote_plus

SEED = 20261102
SESSIONS = 200
EVENTS_PER_SHAPE = 24
EXTRA_KNOWN_PER_SESSION = 6
DATA_OUT = "scripts/data/agent-log-secret-leaks.json"
TUNED_CONFIG = "scripts/data/agent-logs-gitleaks.toml"

ALNUM = string.ascii_letters + string.digits
B64CH = ALNUM + "+/"
MARK = "[REDACTED]"

KINDS = [
    "aws_key_id", "aws_secret", "github_pat", "slack_bot", "stripe_live",
    "openai", "anthropic", "jwt", "db_password", "pem",
]
ENV_NAME = {
    "aws_key_id": "AWS_ACCESS_KEY_ID",
    "aws_secret": "AWS_SECRET_ACCESS_KEY",
    "github_pat": "GITHUB_TOKEN",
    "slack_bot": "SLACK_BOT_TOKEN",
    "stripe_live": "STRIPE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "jwt": "SERVICE_JWT",
    "db_password": "DB_PASSWORD",
    "pem": "TLS_PRIVATE_KEY",
}
NON_PEM = [k for k in KINDS if k != "pem"]

# id, label, compatible secret kinds, known to the runtime (in its env/vault)
SHAPES = [
    ("env_dump", "env dump in shell output", NON_PEM, True),
    ("file_read", ".env or key file read by a tool", KINDS, True),
    ("http_bearer", "curl -v, bearer/API-key header", ["github_pat", "openai", "anthropic", "jwt", "slack_bot", "stripe_live"], True),
    ("http_basic", "curl -v, Basic auth header (base64)", ["github_pat", "stripe_live", "db_password"], True),
    ("traceback_dsn", "traceback locals with a connection URL", ["db_password"], True),
    ("k8s_secret", "kubectl get secret -o yaml (base64)", KINDS, True),
    ("url_query", "token in a logged URL (percent-encoded)", ["aws_secret", "db_password", "jwt", "slack_bot"], True),
    ("hexdump", "xxd of a config file", NON_PEM, True),
    ("model_prose", "model repeats the key in its reply", NON_PEM, True),
    ("sse_stream", "streamed reply, one log record per token", NON_PEM, True),
    ("repo_file", "hard-coded key in a file the agent read", NON_PEM, False),
]


class Gen:
    def __init__(self, rng):
        self.rng = rng

    def s(self, alphabet, n):
        return "".join(self.rng.choice(alphabet) for _ in range(n))

    def hexs(self, n):
        return self.s("0123456789abcdef", n)

    def uuid(self):
        h = self.hexs(32)
        return "%s-%s-4%s-a%s-%s" % (h[:8], h[8:12], h[13:16], h[17:20], h[20:])

    def b64u(self, raw):
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def secret(self, kind):
        # Prefixes are split so this file itself never matches a scanner rule.
        if kind == "aws_key_id":
            return "AK" + "IA" + self.s(string.ascii_uppercase + "234567", 16)
        if kind == "aws_secret":
            return self.s(B64CH, 40)
        if kind == "github_pat":
            return "gh" + "p_" + self.s(ALNUM, 36)
        if kind == "slack_bot":
            return "xo" + "xb-" + self.s(string.digits, 11) + "-" + self.s(string.digits, 13) + "-" + self.s(ALNUM, 24)
        if kind == "stripe_live":
            return "sk" + "_live_" + self.s(ALNUM, 24)
        if kind == "openai":
            return "sk-" + "proj-" + self.s(ALNUM + "-_", 74) + "T3Blbk" + "FJ" + self.s(ALNUM + "-_", 74)
        if kind == "anthropic":
            return "sk-" + "ant-api03-" + self.s(ALNUM + "-_", 93) + "AA"
        if kind == "jwt":
            head = self.b64u(b'{"alg":"HS256","typ":"JWT"}')
            body = self.b64u(json.dumps({"sub": "svc-" + self.s(string.digits, 6), "scope": "deploy", "exp": 1893456000}).encode())
            sig = self.b64u(bytes(self.rng.getrandbits(8) for _ in range(32)))
            return head + "." + body + "." + sig
        if kind == "db_password":
            chars = list(self.s(ALNUM, 16))
            for _ in range(3):
                chars.insert(self.rng.randrange(1, len(chars)), self.rng.choice("!#%&*+=@^/"))
            return "".join(chars)
        if kind == "pem":
            body = base64.b64encode(bytes(self.rng.getrandbits(8) for _ in range(900))).decode()
            lines = [body[i:i + 64] for i in range(0, len(body), 64)]
            return "-----BEGIN " + "RSA PRIVATE KEY-----\n" + "\n".join(lines) + "\n-----END RSA PRIVATE KEY-----"
        raise ValueError(kind)


def xxd(data):
    """Format bytes like `xxd` with its default options."""
    out = []
    for off in range(0, len(data), 16):
        row = data[off:off + 16]
        groups = []
        for i in range(0, 16, 2):
            pair = row[i:i + 2]
            groups.append(pair.hex().ljust(4))
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        out.append("%08x: %s  %s" % (off, " ".join(groups), text))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------ tokenizer
class Tokenizer:
    def __init__(self, model):
        self.model = model
        self.name = "fixed 4-character chunks"
        if model and shutil.which("llama-tokenize"):
            # Label by architecture and vocabulary, not by the (local) file name.
            res = subprocess.run(["llama-tokenize", "-m", model, "-p", "x", "-v"], capture_output=True, text=True)
            meta = dict(re.findall(r"kv\s+\d+:\s+(\S+)\s+\S+\s+=\s+(\S+)", res.stdout + res.stderr))
            arch = meta.get("general.architecture", "?")
            self.name = "llama-tokenize, %s %s GGUF, %s BPE vocab %s" % (
                arch, meta.get("general.size_label", ""), meta.get("tokenizer.ggml.pre", "?"), meta.get(arch + ".vocab_size", "?"))

    def pieces(self, text):
        if self.name.startswith("fixed"):
            return [text[i:i + 4] for i in range(0, len(text), 4)]
        res = subprocess.run(
            ["llama-tokenize", "-m", self.model, "-p", text, "--no-bos", "--log-disable"],
            capture_output=True, text=True, check=True)
        out = []
        for line in res.stdout.splitlines():
            m = re.match(r"^\s*\d+ -> '(.*)'$", line)
            if m:
                out.append(m.group(1))
        if "".join(out) != text:
            raise RuntimeError("tokenizer pieces do not reassemble the prompt")
        return out


# ------------------------------------------------------------ corpus
def benign_record(g, repo):
    """One tool call/result pair or message with no secret in it."""
    pick = g.rng.randrange(12)
    if pick == 0:
        rows = ["%s %s" % (g.hexs(7), g.rng.choice(["fix flaky retry test", "bump deps", "add export endpoint", "refactor db pool", "docs: env vars"])) for _ in range(8)]
        return "shell", {"cmd": "git log --oneline -n 8"}, "\n".join(rows)
    if pick == 1:
        dots = "".join(g.rng.choice("....F.s") for _ in range(42))
        return "shell", {"cmd": "pytest -q"}, dots + "\n1 failed, 39 passed, 2 skipped in %.2fs" % (g.rng.random() * 9 + 1)
    if pick == 2:
        integ = base64.b64encode(bytes(g.rng.getrandbits(8) for _ in range(64))).decode()
        return "fs.read", {"path": "package-lock.json"}, '{\n  "node_modules/undici": {\n    "version": "6.21.%d",\n    "resolved": "https://registry.npmjs.org/undici/-/undici-6.21.%d.tgz",\n    "integrity": "sha512-%s"\n  }\n}' % (g.rng.randrange(9), g.rng.randrange(9), integ)
    if pick == 3:
        return "shell", {"cmd": "docker pull ghcr.io/acme/%s:latest" % repo}, "latest: Pulling from acme/%s\nDigest: sha256:%s\nStatus: Downloaded newer image for ghcr.io/acme/%s:latest" % (repo, g.hexs(64), repo)
    if pick == 4:
        return "http.get", {"url": "https://api.internal/v1/orders?limit=20"}, json.dumps({"request_id": g.uuid(), "etag": 'W/"%s"' % g.hexs(32), "items": [{"id": g.uuid(), "total": g.rng.randrange(100, 9000)} for _ in range(3)]})
    if pick == 5:
        return "assistant", None, g.rng.choice([
            "The failing test depends on the clock; I'll freeze time in the fixture and rerun.",
            "Next I'll run the integration suite against the local database.",
            "The diff touches three files. I'll keep the public API unchanged.",
            "Lint passes. Opening the pull request with the summary below.",
        ])
    if pick == 6:
        # The AWS documentation example key: scanners allowlist it on purpose.
        return "fs.read", {"path": "docs/aws.md"}, "Configure the CLI:\n\n    aws configure\n    AWS Access Key ID [None]: AKIA" + "IOSFODNN7EXAMPLE\n    Default region name [None]: eu-west-1\n"
    if pick == 7:
        png = base64.b64encode(bytes(g.rng.getrandbits(8) for _ in range(150))).decode()
        return "browser.screenshot", {"url": "http://localhost:3000/checkout"}, "data:image/png;base64," + png
    if pick == 8:
        return "shell", {"cmd": "pip download -r requirements.txt --require-hashes"}, "Collecting httpx==0.27.2 --hash=sha256:%s\nCollecting anyio==4.6.2 --hash=sha256:%s\nSaved ./httpx-0.27.2-py3-none-any.whl" % (g.hexs(64), g.hexs(64))
    if pick == 10:
        # Keyed identifiers that are not secrets: idempotency keys, cache keys.
        return "shell", {"cmd": "curl -sv -X POST https://api.internal/v1/refunds"}, (
            "> POST /v1/refunds HTTP/2\n> Host: api.internal\n> idempotency-key: %s\n> content-type: application/json\n>\n"
            "< HTTP/2 201\n< x-request-id: %s\n<\n{\"id\": \"%s\", \"status\": \"pending\"}" % (g.uuid(), g.uuid(), g.uuid()))
    if pick == 11:
        return "http.get", {"url": "https://api.internal/v1/audit?limit=50"}, json.dumps(
            {"items": [], "next_page_token": g.s(B64CH, 44), "cache_key": g.hexs(40)})
    return "shell", {"cmd": "terraform state list"}, "\n".join("azurerm_storage_account.logs[\"%s\"]  /subscriptions/%s/resourceGroups/rg-%s" % (g.hexs(6), g.uuid(), repo) for _ in range(3))


def leak_content(g, shape, kind, v, rng):
    """Return (tool, args, content) for a leak event; content holds v in some form."""
    name = ENV_NAME[kind]
    if shape == "env_dump":
        env = ["PATH=/usr/local/bin:/usr/bin:/bin", "HOME=/home/agent", "LANG=C.UTF-8", "PWD=/workspace/orders",
               "CI=true", "NODE_ENV=development", "HOSTNAME=%s" % g.hexs(12), "PYTHONUNBUFFERED=1",
               "GIT_COMMIT=%s" % g.hexs(40), "BUILD_ID=%s" % g.uuid(), "%s=%s" % (name, v)]
        rng.shuffle(env)
        return "shell", {"cmd": "env"}, "\n".join(env)
    if shape == "file_read":
        if kind == "pem":
            return "fs.read", {"path": "deploy/tls.key"}, v + "\n"
        return "fs.read", {"path": ".env"}, "# local overrides - do not commit\nLOG_LEVEL=debug\n%s=%s\nFEATURE_FLAGS=search,v2\n" % (name, v)
    if shape == "http_bearer":
        header = ("x-api-key: %s" % v) if kind == "anthropic" else ("authorization: Bearer %s" % v)
        return "shell", {"cmd": "curl -sv https://api.internal/v1/models"}, (
            "*   Trying 10.0.4.17:443...\n* Connected to api.internal (10.0.4.17) port 443\n"
            "> GET /v1/models HTTP/2\n> Host: api.internal\n> user-agent: curl/8.7.1\n> accept: */*\n> %s\n>\n"
            "< HTTP/2 200\n< content-type: application/json\n< x-request-id: %s\n<\n{\"object\":\"list\",\"data\":[]}" % (header, g.uuid()))
    if shape == "http_basic":
        user = {"github_pat": "x-access-token", "stripe_live": "", "db_password": "svc-deploy"}[kind]
        cred = (v + ":") if kind == "stripe_live" else (user + ":" + v)
        return "shell", {"cmd": "curl -sv -u *** https://api.internal/v1/charges"}, (
            "*   Trying 10.0.4.17:443...\n* Server auth using Basic with user '%s'\n"
            "> GET /v1/charges HTTP/2\n> Host: api.internal\n> authorization: Basic %s\n> user-agent: curl/8.7.1\n>\n"
            "< HTTP/2 200\n< x-request-id: %s" % (user, base64.b64encode(cred.encode()).decode(), g.uuid()))
    if shape == "traceback_dsn":
        if rng.random() < 0.5:
            url = "postgresql://app_rw:%s@db.internal:5432/orders" % quote(v, safe="")
            err = 'E   psycopg.OperationalError: connection to server at "db.internal" (10.0.3.9), port 5432 failed: timeout expired'
            exc = "OperationalError"
        else:
            url = "redis://:%s@cache.internal:6379/0" % quote(v, safe="")
            err = "E   redis.exceptions.TimeoutError: Timeout connecting to server"
            exc = "TimeoutError"
        return "shell", {"cmd": "pytest -l tests/test_db.py"}, (
            "_________________________ test_connect _________________________\n\n"
            "dsn        = '%s'\ntimeout    = 5\n\n    def test_connect(dsn, timeout):\n>       conn = connect(dsn, timeout=timeout)\n%s\n"
            "tests/test_db.py:18: %s" % (url, err, exc))
    if shape == "k8s_secret":
        key = "tls.key" if kind == "pem" else name
        return "shell", {"cmd": "kubectl get secret app-env -n orders -o yaml"}, (
            "apiVersion: v1\ndata:\n  LOG_LEVEL: ZGVidWc=\n  %s: %s\nkind: Secret\nmetadata:\n"
            "  creationTimestamp: \"2026-10-30T09:12:44Z\"\n  name: app-env\n  namespace: orders\n"
            "  resourceVersion: \"%d\"\n  uid: %s\ntype: Opaque" % (key, base64.b64encode(v.encode()).decode(), rng.randrange(10 ** 6, 10 ** 7), g.uuid()))
    if shape == "url_query":
        param = rng.choice(["api_key", "token", "access_token", "sig", "auth"])
        return "shell", {"cmd": "python scripts/export_report.py --debug"}, (
            "DEBUG httpcore.connection: connect_tcp.started host='reports.internal' port=443\n"
            "INFO httpx: HTTP Request: GET https://reports.internal/v2/export?format=csv&%s=%s \"HTTP/1.1 200 OK\"\n"
            "wrote report.csv (412 rows)" % (param, quote(v, safe="")))
    if shape == "hexdump":
        data = ("LOG_LEVEL=debug\n%s=%s\n" % (name, v)).encode()
        return "shell", {"cmd": "xxd .env"}, xxd(data)
    if shape == "model_prose":
        return "assistant", None, rng.choice([
            "The tests fail because %s is not set in CI. Locally it is `%s`, so I exported that value and the suite passes now." % (name, v),
            "Found it: the client reads %s from the environment. The current value (%s) is valid; the 401 came from the wrong region." % (name, v),
            "I'll add the key to the CI secrets. For reference the value I used is %s." % v,
        ])
    if shape == "repo_file":
        return "fs.read", {"path": "src/payments/config.py"}, (
            "import os\n\n# TODO: move to the secret store before launch\n%s = os.environ.get(\"%s\", \"%s\")\nTIMEOUT_S = 30\n" % (name, name, v))
    raise ValueError(shape)


def build_corpus(tok):
    rng = random.Random(SEED)
    g = Gen(rng)
    sessions = []
    for i in range(SESSIONS):
        repo = rng.choice(["orders", "billing", "search", "gateway", "notify"])
        n = rng.randrange(30, 61)
        sessions.append({"id": "s%04d" % i, "repo": repo, "blocks": [benign_record(g, repo) for _ in range(n)],
                         "known": [g.secret(rng.choice(NON_PEM)) for _ in range(EXTRA_KNOWN_PER_SESSION)]})
    events = []
    tokens_by_kind = {}
    sse_example = None
    for shape, label, kinds, known in SHAPES:
        for j in range(EVENTS_PER_SHAPE):
            kind = kinds[j % len(kinds)]
            v = g.secret(kind)
            sess = sessions[rng.randrange(SESSIONS)]
            ev = {"id": len(events), "shape": shape, "kind": kind, "secret": v, "known": known, "session": sess["id"]}
            if shape == "sse_stream":
                text = "Done. I set `%s=%s` in `.env.local` so the integration tests can reach the API." % (ENV_NAME[kind], v)
                pieces = tok.pieces(text)
                start = text.index(v)
                end = start + len(v)
                pos, touching = 0, 0
                for p in pieces:
                    if pos < end and pos + len(p) > start:
                        touching += 1
                    pos += len(p)
                tokens_by_kind.setdefault(kind, []).append(touching)
                if sse_example is None and kind == "github_pat":
                    sse_example = {"text": text, "pieces": pieces, "secret_start": start, "secret_end": end, "tokenizer": tok.name}
                block = ("sse", pieces, None)
            else:
                block = leak_content(g, shape, kind, v, rng)
            if known:
                sess["known"].append(v)
            pos = rng.randrange(len(sess["blocks"]) + 1)
            sess["blocks"].insert(pos, ("event", ev["id"], block))
            events.append(ev)
    return sessions, events, tokens_by_kind, sse_example


# ------------------------------------------------------------ redaction
def variants(v):
    """Encodings of v that a known-value redactor should also remove."""
    b = v.encode()
    out = {quote(v, safe=""), quote_plus(v), b.hex(), b.hex().upper(), json.dumps(v)[1:-1]}
    for enc in (base64.b64encode, base64.urlsafe_b64encode):
        for k in range(3):
            e = enc(b"\0" * k + b).decode().rstrip("=")
            start = -(-8 * k // 6)
            end = (8 * (k + len(b))) // 6
            out.add(e[start:end])
    out.discard(v)
    return out


class Redactor:
    def __init__(self, secrets, encodings):
        needles = set()
        for v in secrets:
            needles.add(v)
            if encodings:
                needles.update(variants(v))
        self.needles = sorted((n for n in needles if len(n) >= 8), key=len, reverse=True)
        self.maxlen = max(len(n) for n in self.needles)

    def redact(self, text):
        for n in self.needles:
            if n in text:
                text = text.replace(n, MARK)
        return text


def write_corpus(sessions, out_dir, mode):
    """mode: none | naive | full.

    Writes <out_dir>/session-*.jsonl (the stored log) and <out_dir>-view/*.txt
    (a decoded view: each record's content JSON-unescaped, each stream
    reassembled). Returns ({event_id: (file, [jsonl lines])},
    {event_id: (file, first view line, last view line)}).
    """
    view_dir = out_dir + "-view"
    for d in (out_dir, view_dir):
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)
    lines_of = {}
    view_of = {}
    holdback = []
    for si, sess in enumerate(sessions):
        red = None
        if mode != "none":
            red = Redactor(sess["known"], encodings=(mode == "full"))
        fname = "session-%s.jsonl" % sess["id"]
        lineno = 0
        seq = 0
        view = []
        t0 = 1793347200 + si * 3600  # 2026-10-30T08:00:00Z + one hour per session
        with open(os.path.join(out_dir, fname), "w") as fh:
            def emit(rec, ev_id=None):
                nonlocal lineno, seq
                seq += 1
                lineno += 1
                rec = dict({"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t0 + seq * 2)) + "Z", "session": sess["id"], "seq": seq}, **rec)
                fh.write(json.dumps(rec) + "\n")
                if ev_id is not None:
                    lines_of.setdefault(ev_id, (fname, []))[1].append(lineno)

            for block in sess["blocks"]:
                ev_id = None
                if block[0] == "event":
                    ev_id, block = block[1], block[2]
                tool, args, content = block
                if tool == "sse":
                    pieces = args
                    sid = "st_%s_%d" % (sess["id"], seq)
                    deltas = []
                    if mode == "full":
                        hold = red.maxlen - 1
                        holdback.append(hold)
                        buf = ""
                        for p in pieces:
                            buf = red.redact(buf + p)
                            if len(buf) > hold:
                                deltas.append(buf[:len(buf) - hold])
                                buf = buf[len(buf) - hold:]
                        if buf:
                            deltas.append(red.redact(buf))
                    else:
                        deltas = [red.redact(p) if red else p for p in pieces]
                    for dlt in deltas:
                        emit({"type": "sse_chunk", "stream": sid, "delta": dlt}, ev_id)
                    emit({"type": "sse_end", "stream": sid, "chunks": len(pieces)})
                    view.append((ev_id, "".join(deltas)))
                    continue
                if red:
                    content = red.redact(content)
                view.append((ev_id, content))
                if tool == "assistant":
                    emit({"type": "assistant", "content": content}, ev_id)
                else:
                    emit({"type": "tool_call", "tool": tool, "args": args})
                    emit({"type": "tool_result", "tool": tool, "content": content}, ev_id)
        vname = "session-%s.txt" % sess["id"]
        vline = 0
        with open(os.path.join(view_dir, vname), "w") as fh:
            for ev_id, text in view:
                n = text.count("\n") + 1
                fh.write(text + "\n")
                if ev_id is not None:
                    view_of[ev_id] = (vname, vline + 1, vline + n)
                vline += n
    write_corpus.holdback = holdback
    return lines_of, view_of


# ------------------------------------------------------------ oracle
B64RUN = re.compile(r"[A-Za-z0-9+/_-]{12,}={0,2}")
HEXRUN = re.compile(r"(?:[0-9a-fA-F]{2}){8,}")
XXDROW = re.compile(r"^[0-9a-f]{8}: ((?:[0-9a-f]{2,4} ?)+)", re.M)


def recoverable(text, v):
    """Can an attacker who reads the stored log get v back, with stock tools?"""
    vb = v.encode()
    for t in (text, unquote(text), unquote_plus(text)):
        if v in t:
            return True
    for m in B64RUN.finditer(text):
        s = m.group(0).rstrip("=")
        for off in range(4):
            chunk = s[off:]
            chunk = chunk[:len(chunk) - len(chunk) % 4] if len(chunk) % 4 == 1 else chunk
            for dec in (base64.b64decode, base64.urlsafe_b64decode):
                try:
                    d = dec(chunk + "=" * (-len(chunk) % 4))
                except Exception:
                    continue
                if vb in d:
                    return True
    for m in HEXRUN.finditer(text):
        try:
            if vb in bytes.fromhex(m.group(0)):
                return True
        except ValueError:
            pass
    rows = XXDROW.findall(text)
    if rows:
        try:
            if vb in bytes.fromhex("".join(r.replace(" ", "") for r in rows)):
                return True
        except ValueError:
            pass
    return False


def event_text(log_dir, fname, lines, cache):
    if fname not in cache:
        with open(os.path.join(log_dir, fname)) as fh:
            cache[fname] = fh.read().splitlines()
    recs = [json.loads(cache[fname][n - 1]) for n in lines]
    if recs and recs[0]["type"] == "sse_chunk":
        return "".join(r["delta"] for r in recs)
    return "\n".join(r.get("content", "") for r in recs)


# ------------------------------------------------------------ gitleaks
def gitleaks(log_dir, report, config=None):
    t = time.time()
    cmd = ["gitleaks", "dir", log_dir, "--no-banner", "--redact", "-f", "json", "-r", report, "--exit-code", "0", "-l", "error"]
    if config:
        cmd += ["-c", os.path.abspath(config)]
    subprocess.run(cmd, check=True)
    took = time.time() - t
    with open(report) as fh:
        return json.load(fh), took


def flagged_view_events(findings, view_of):
    by_file = {}
    for f in findings:
        by_file.setdefault(os.path.basename(f["File"]), []).append(f)
    hit = {}
    stray = []
    claimed = set()
    for ev_id, (vname, first, last) in view_of.items():
        for f in by_file.get(vname, []):
            if first <= f["StartLine"] <= last:
                hit.setdefault(ev_id, []).append(f["RuleID"])
                claimed.add(id(f))
    stray = [f for f in findings if id(f) not in claimed]
    return hit, stray


def flagged_events(findings, lines_of):
    by_line = {}
    for f in findings:
        by_line.setdefault((os.path.basename(f["File"]), f["StartLine"]), []).append(f)
    hit = {}
    for ev_id, (fname, lines) in lines_of.items():
        rules = [f["RuleID"] for n in lines for f in by_line.get((fname, n), [])]
        if rules:
            hit[ev_id] = rules
    event_lines = {(fname, n) for fname, lines in lines_of.values() for n in lines}
    stray = [f for f in findings if (os.path.basename(f["File"]), f["StartLine"]) not in event_lines]
    return hit, stray


def fp_classes(stray, view_dir):
    """Group findings outside leak events by the key name in front of the match."""
    out = {}
    for f in stray:
        head = f["Match"].split("REDACTED")[0].replace("\\n", " ")
        m = re.match(r'[\s"]*([A-Za-z_-]+)', head)
        label = m.group(1) if m else f["RuleID"]
        out.setdefault(label, {"rule": f["RuleID"], "findings": 0})["findings"] += 1
    text = "".join(open(os.path.join(view_dir, n)).read() for n in os.listdir(view_dir))
    for label, row in out.items():
        row["benign_records"] = len(re.findall(r'(?m)(?:^> |")' + re.escape(label) + r'(?:: |": )', text))
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["findings"]))


def one_session_capture(log_dir, events, lines_of, cap):
    """gitleaks -v on one session that holds both a decoded and a missed leak."""
    per = {}
    for e in events:
        per.setdefault(lines_of[e["id"]][0], set()).add(e["shape"])
    want = {"http_basic", "traceback_dsn", "sse_stream"}
    fname = sorted(per, key=lambda f: (-len(per[f] & want), f))[0]
    res = subprocess.run(["gitleaks", "dir", fname, "--no-banner", "--no-color", "--redact", "-v",
                          "--exit-code", "0"], capture_output=True, text=True, cwd=log_dir)
    planted = [{"shape": e["shape"], "kind": e["kind"], "lines": lines_of[e["id"]][1]} for e in events if lines_of[e["id"]][0] == fname]
    with open(os.path.join(cap, "gitleaks-one-session.txt"), "w") as fh:
        fh.write(res.stdout + res.stderr)
    with open(os.path.join(cap, "gitleaks-one-session-planted.json"), "w") as fh:
        json.dump({"file": fname, "planted": planted}, fh, indent=1)


def dir_bytes(d):
    return sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--model")
    ap.add_argument("--repeats", type=int, default=3)
    a = ap.parse_args()
    work = os.path.abspath(a.work)
    cap = os.path.join(work, "capture")
    os.makedirs(cap, exist_ok=True)

    tok = Tokenizer(a.model)
    sessions, events, tokens_by_kind, sse_example = build_corpus(tok)
    evmap = {e["id"]: e for e in events}

    logs, lines, views, findings = {}, {}, {}, {}
    write_times = {}
    for mode in ("none", "naive", "full"):
        d = os.path.join(work, "logs-" + mode)
        times = []
        for _ in range(a.repeats):
            t = time.time()
            lines[mode], views[mode] = write_corpus(sessions, d, mode)
            times.append(time.time() - t)
            if mode == "full":
                holdback = write_corpus.holdback
        write_times[mode] = statistics.median(times)
        logs[mode] = d
    scan_times = []
    for _ in range(a.repeats):
        findings["none"], took = gitleaks(logs["none"], os.path.join(cap, "gitleaks-none.json"))
        scan_times.append(took)
    findings["view"], _ = gitleaks(logs["none"] + "-view", os.path.join(cap, "gitleaks-view.json"))
    findings["full_view"], _ = gitleaks(logs["full"] + "-view", os.path.join(cap, "gitleaks-full-view.json"))

    hit_raw, stray_raw = flagged_events(findings["none"], lines["none"])
    hit_view, stray_view = flagged_view_events(findings["view"], views["none"])
    hit_full, stray_full = flagged_view_events(findings["full_view"], views["full"])
    one_session_capture(logs["none"], events, lines["none"], cap)
    findings["view_tuned"], _ = gitleaks(logs["none"] + "-view", os.path.join(cap, "gitleaks-view-tuned.json"), TUNED_CONFIG)
    findings["full_view_tuned"], _ = gitleaks(logs["full"] + "-view", os.path.join(cap, "gitleaks-full-view-tuned.json"), TUNED_CONFIG)
    hit_view_tuned, stray_view_tuned = flagged_view_events(findings["view_tuned"], views["none"])
    hit_full_tuned, stray_full_tuned = flagged_view_events(findings["full_view_tuned"], views["full"])
    cache = {m: {} for m in logs}

    def leaked(mode, ev_id):
        fname, ln = lines[mode][ev_id]
        return recoverable(event_text(logs[mode], fname, ln, cache[mode]), evmap[ev_id]["secret"])

    sanity = sum(leaked("none", e["id"]) for e in events)
    rows = []
    for shape, label, kinds, known in SHAPES:
        ids = [e["id"] for e in events if e["shape"] == shape]
        row = {"id": shape, "label": label, "known_to_runtime": known, "events": len(ids),
               "kinds": sorted(set(evmap[i]["kind"] for i in ids)),
               "gitleaks": sum(1 for i in ids if i in hit_raw),
               "gitleaks_decoded_view": sum(1 for i in ids if i in hit_view),
               "gitleaks_decoded_view_tuned": sum(1 for i in ids if i in hit_view_tuned),
               "naive_redaction": sum(1 for i in ids if not leaked("naive", i)),
               "full_redaction": sum(1 for i in ids if not leaked("full", i)),
               "full_plus_gitleaks": sum(1 for i in ids if (not leaked("full", i)) or i in hit_full),
               "full_plus_gitleaks_tuned": sum(1 for i in ids if (not leaked("full", i)) or i in hit_full_tuned),
               "gitleaks_missed_kinds": dict(sorted(Counter(evmap[i]["kind"] for i in ids if i not in hit_raw).items())),
               "gitleaks_decoded_view_missed_kinds": dict(sorted(Counter(evmap[i]["kind"] for i in ids if i not in hit_view).items())),
               "gitleaks_rules": sorted(set(r for i in ids for r in hit_raw.get(i, []))),
               "gitleaks_rules_decoded_view": sorted(set(r for i in ids for r in hit_view.get(i, [])))}
        rows.append(row)
        print("%-14s gitleaks %2d  view %2d  tuned %2d  naive %2d  full %2d  full+tuned %2d  / %d" % (
            shape, row["gitleaks"], row["gitleaks_decoded_view"], row["gitleaks_decoded_view_tuned"], row["naive_redaction"],
            row["full_redaction"], row["full_plus_gitleaks_tuned"], len(ids)))

    total = len(events)
    tot = {k: sum(r[k] for r in rows) for k in ("gitleaks", "gitleaks_decoded_view", "gitleaks_decoded_view_tuned",
                                                "naive_redaction", "full_redaction", "full_plus_gitleaks", "full_plus_gitleaks_tuned")}
    tot["events"] = total
    records = sum(1 for d in [logs["none"]] for f in os.listdir(d) for _ in open(os.path.join(d, f)))
    rule_counts = {}
    for f in findings["none"]:
        rule_counts[f["RuleID"]] = rule_counts.get(f["RuleID"], 0) + 1
    raw_bytes = dir_bytes(logs["none"])

    tok_stats = {k: {"median": statistics.median(v), "min": min(v), "max": max(v), "n": len(v)} for k, v in sorted(tokens_by_kind.items())}
    secret_len = {}
    for e in events:
        secret_len.setdefault(e["kind"], []).append(len(e["secret"]))

    data = {
        "generated_by": "scripts/agent_log_secret_leak_bench.py",
        "seed": SEED,
        "sessions": SESSIONS,
        "records": records,
        "log_bytes": raw_bytes,
        "events": total,
        "events_per_shape": EVENTS_PER_SHAPE,
        "oracle_sanity_raw_recoverable": sanity,
        "gitleaks_version": subprocess.run(["gitleaks", "version"], capture_output=True, text=True).stdout.strip(),
        "gitleaks_config": "default rules",
        "tokenizer": tok.name,
        "shapes": rows,
        "totals": tot,
        "gitleaks_findings_raw": len(findings["none"]),
        "gitleaks_findings_outside_leak_events": len(stray_raw),
        "gitleaks_findings_outside_leak_events_decoded_view": len(stray_view),
        "gitleaks_findings_outside_leak_events_after_full_redaction": len(stray_full),
        "gitleaks_tuned_config": TUNED_CONFIG,
        "gitleaks_findings_outside_leak_events_decoded_view_tuned": len(stray_view_tuned),
        "gitleaks_findings_outside_leak_events_after_full_redaction_tuned": len(stray_full_tuned),
        "false_positive_classes_stored": fp_classes(stray_raw, logs["none"] + "-view"),
        "false_positive_classes_decoded_view": fp_classes(stray_view, logs["none"] + "-view"),
        "gitleaks_rule_counts_raw": dict(sorted(rule_counts.items(), key=lambda kv: -kv[1])),
        "sse_tokens_per_secret": tok_stats,
        "secret_length_chars": {k: statistics.median(v) for k, v in sorted(secret_len.items())},
        "stream_holdback_chars": {"median": statistics.median(holdback), "min": min(holdback), "max": max(holdback)},
        "timing_seconds_median": {
            "gitleaks_scan_raw_logs": round(statistics.median(scan_times), 3),
            "write_no_redaction": round(write_times["none"], 3),
            "write_naive_redaction": round(write_times["naive"], 3),
            "write_full_redaction": round(write_times["full"], 3),
        },
        "repeats": a.repeats,
    }
    with open(DATA_OUT, "w") as fh:
        json.dump(data, fh, indent=1)
        fh.write("\n")
    if sse_example:
        with open(os.path.join(cap, "sse-example.json"), "w") as fh:
            json.dump(sse_example, fh)
    print("oracle sanity: %d/%d planted secrets recoverable from the unredacted logs" % (sanity, total))
    print("totals:", tot)
    print("gitleaks findings outside leak events (false positives): stored %d, decoded view %d, after full redaction %d; "
          "tuned config: decoded view %d, after full redaction %d" % (
              len(stray_raw), len(stray_view), len(stray_full), len(stray_view_tuned), len(stray_full_tuned)))
    print("timing:", data["timing_seconds_median"], "log MB: %.2f" % (raw_bytes / 1e6))
    print("tokens per secret:", tok_stats)
    print("wrote", DATA_OUT)


if __name__ == "__main__":
    main()
