#!/usr/bin/env python3
"""Capture the gateway's /budgets status page after a real run, for the post's screenshots.

    python3 scripts/enterprise-ai-token-budgets/capture_status.py --upstream 127.0.0.1:18431 --mode post --out .tmp/status-post.html

Runs the same seeded workload as run_experiment.py (rep 0, 16 batch workers), then, with the
gateway still up, fetches GET /budgets over HTTP and saves the page. Screenshot it with any
headless browser.
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_experiment as R  # noqa: E402
from gateway import Gateway  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default="127.0.0.1:18431")
    ap.add_argument("--port", type=int, default=18490)
    ap.add_argument("--mode", default="post")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    keep = {}
    orig_serve = Gateway.serve

    def serve(self, port):  # keep the server object so the page can be fetched before shutdown
        srv = orig_serve(self, port)
        keep["srv"] = srv
        orig_shutdown = srv.shutdown

        def shutdown():
            page = urllib.request.urlopen(f"http://127.0.0.1:{port}/budgets").read()
            with open(a.out, "wb") as f:
                f.write(page)
            orig_shutdown()
        srv.shutdown = shutdown
        return srv

    Gateway.serve = serve
    row = R.run_once(a.upstream, a.port, a.mode, 16, 0, None)
    b = row["ledger"]["teams"]["batch-summariser"]
    print(f"{a.mode}: spent {b['spent']}/{b['budget']} served {b['served']} 429 {b['rejected_budget']} -> {a.out}")


if __name__ == "__main__":
    main()
