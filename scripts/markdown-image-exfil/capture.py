#!/usr/bin/env python3
"""Screenshot + attacker-log capture for the markdown-image exfiltration post's side-by-side figure.

Usage (same environment as bench.py):
  BROWSER_PATH=<chrome-headless-shell> python3.13 scripts/markdown-image-exfil/capture.py --work <scratch-dir>

Re-runs a handful of bench.py pages (same seed, same server, same driver) and
saves, for each, the PNG screenshot and the attacker host's access-log lines
that page caused, to <work>/capture/. gen_images.py crops the screenshots; the
log lines are printed in the figure verbatim apart from the port.
"""
import argparse
import json
import os
import random
import subprocess
import threading
import time

import bench

CASES = ["md_inline-0-innerhtml", "md_inline-0-inert_allowlist", "md_inline-0-csp_inert",
         "md_open_redirect-0-innerhtml", "md_open_redirect-0-inert_allowlist",
         "html_meta_refresh-0-csp", "html_meta_refresh-0-csp_inert"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--port", type=int, default=8940)
    a = ap.parse_args()
    browser = os.environ["BROWSER_PATH"]
    cap = os.path.join(os.path.abspath(a.work), "capture")
    os.makedirs(cap, exist_ok=True)
    pages = bench.build_pages(a.port, random.Random(bench.SEED))
    log = bench.Log()
    srv = bench.make_server(a.port, pages, log)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out = {}
    for pid in CASES:
        entry = [{"id": pid, "url": "http://chat.localhost:%d/case/%s" % (a.port, pid),
                  "shot": os.path.join(cap, pid + ".png"), "settle": 800}]
        pf = os.path.join(cap, "pages.json")
        with open(pf, "w") as f:
            json.dump(entry, f)
        log.hits.clear()
        subprocess.run(["node", os.path.join(bench.HERE, "driver.mjs"), pf, os.path.join(cap, "out.jsonl")],
                       env=dict(os.environ, BROWSER_PATH=browser), check=True)
        time.sleep(0.3)
        t0 = log.hits[0][0] if log.hits else 0
        out[pid] = {"canary": pages[pid]["canary"], "md": pages[pid]["md"].replace(str(a.port), "PORT"),
                    "requests": [{"ms": round((t - t0) * 1000, 1), "host": h.replace(str(a.port), "PORT"),
                                  "path": p} for t, h, p in log.hits]}
        print(pid, len(log.hits), "requests")
    srv.shutdown()
    with open(os.path.join(cap, "capture.json"), "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
