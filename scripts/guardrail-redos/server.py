#!/usr/bin/env python3
"""Guardrail service with CPython `re`: POST /check with a text body runs every rule.

Usage: python3 server.py <rules.json> <naive|hardened> <port> [threads-hint]

ThreadingHTTPServer, one thread per connection, listen backlog 512. CPython's sre
matcher holds the GIL while it backtracks, so one slow match stalls every other
request thread in the process - that is what the load test measures.
Reply: {"flagged": [rule names], "ms": guard time}.
"""
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

cfg = json.load(open(sys.argv[1]))
variant = sys.argv[2]
port = int(sys.argv[3])
RULES = [(r["name"], r["mode"], re.compile(r[variant], re.IGNORECASE if "i" in r["flags"] else 0))
         for r in cfg["rules"]]


def check(text):
    flagged = []
    for name, mode, rx in RULES:
        if mode == "search":
            if rx.search(text):
                flagged.append(name)
        else:
            new = rx.sub("#", text)
            if new != text:
                flagged.append(name)
                text = new
    return flagged


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8", "replace")
        t = time.perf_counter()
        flagged = check(body)
        out = json.dumps({"flagged": flagged, "ms": (time.perf_counter() - t) * 1000}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class S(ThreadingHTTPServer):
    request_queue_size = 512
    daemon_threads = True


print(f"python guard ({variant}) on :{port}", flush=True)
S(("127.0.0.1", port), H).serve_forever()
