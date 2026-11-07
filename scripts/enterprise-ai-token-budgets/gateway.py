#!/usr/bin/env python3
"""A small LLM gateway with per-team token budgets, written for the
"Enterprise AI: token budgets that hold under concurrency" post (stdlib only).

It sits in front of any OpenAI-compatible /v1/chat/completions server (the post
uses llama-server) and enforces, per team and per budget window:

  * a registered use case (x-use-case header must be in the team's register),
  * a token budget, in one of four enforcement modes:
      none      meter only, never reject on budget
      post      admit while spent < budget, add prompt+completion when the reply arrives
      estimate  admit while spent + prompt <= budget, add prompt at admission and the
                completion when the reply arrives (what "estimate prompt tokens" gateway
                policies do)
      reserve   admit only if spent + reserved + prompt + max_tokens <= budget, hold that
                reservation while the call is in flight, settle to the real usage after
  * a max_tokens ceiling per team (requests above it are clamped, never forwarded as is).

Every decision is written to an audit JSONL line. GET /budgets renders an HTML
status page (the screenshot in the post), GET /budgets.json the same as JSON.

    python3 gateway.py --upstream 127.0.0.1:18431 --port 18440 --mode reserve
"""
from __future__ import annotations

import argparse
import html
import http.client
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODES = ("none", "post", "estimate", "reserve")

# Team register: budget per window (tokens), the use cases each team registered, the
# largest max_tokens a call may ask for. In a real rollout this comes from the use-case
# intake register; here it is a dict so the experiment is self-contained.
DEFAULT_TEAMS = {
    "batch-summariser": {"budget": 40000, "use_cases": {"UC-112 weekly account digest"}, "max_tokens_cap": 1024},
    "support-bot": {"budget": 60000, "use_cases": {"UC-101 ticket triage"}, "max_tokens_cap": 512},
    "finance-ops": {"budget": 20000, "use_cases": {"UC-087 invoice coding"}, "max_tokens_cap": 512},
}


class Ledger:
    def __init__(self, teams: dict, mode: str):
        self.mode = mode
        self.lock = threading.Lock()
        self.t0 = time.monotonic()
        self.teams = {}
        for name, cfg in teams.items():
            self.teams[name] = {
                "budget": cfg["budget"], "use_cases": set(cfg["use_cases"]), "cap": cfg["max_tokens_cap"],
                "spent": 0, "reserved": 0, "in_flight": 0, "peak_in_flight": 0,
                "served": 0, "rejected_budget": 0, "rejected_use_case": 0, "clamped": 0,
                "exhausted_at": None,
            }
        self.unknown_rejected = 0

    def admit(self, team: str, use_case: str, prompt_tokens: int, max_tokens: int):
        """Return (decision, http_status, reservation, reason)."""
        with self.lock:
            t = self.teams.get(team)
            if t is None:
                self.unknown_rejected += 1
                return "reject", 403, 0, "unknown team"
            if use_case not in t["use_cases"]:
                t["rejected_use_case"] += 1
                return "reject", 403, 0, "use case not in register"
            ok, held = True, 0
            if self.mode == "post":
                ok = t["spent"] < t["budget"]
            elif self.mode == "estimate":
                ok = t["spent"] + prompt_tokens <= t["budget"]
                if ok:
                    t["spent"] += prompt_tokens
            elif self.mode == "reserve":
                need = prompt_tokens + max_tokens
                ok = t["spent"] + t["reserved"] + need <= t["budget"]
                if ok:
                    t["reserved"] += need
                    held = need
            if not ok:
                t["rejected_budget"] += 1
                if t["exhausted_at"] is None:
                    t["exhausted_at"] = round(time.monotonic() - self.t0, 2)
                return "reject", 429, 0, "token budget exhausted"
            t["in_flight"] += 1
            t["peak_in_flight"] = max(t["peak_in_flight"], t["in_flight"])
            return "admit", 200, held, ""

    def settle(self, team: str, held: int, prompt_tokens: int, completion_tokens: int):
        with self.lock:
            t = self.teams[team]
            t["in_flight"] -= 1
            t["reserved"] -= held
            if self.mode == "estimate":
                t["spent"] += completion_tokens  # prompt was counted at admission
            else:
                t["spent"] += prompt_tokens + completion_tokens
            t["served"] += 1

    def release(self, team: str, held: int, prompt_tokens: int):
        """Upstream failed: give the reservation back, and the estimate charge."""
        with self.lock:
            t = self.teams[team]
            t["in_flight"] -= 1
            t["reserved"] -= held
            if self.mode == "estimate":
                t["spent"] -= prompt_tokens

    def snapshot(self) -> dict:
        with self.lock:
            out = {"mode": self.mode, "elapsed_s": round(time.monotonic() - self.t0, 1),
                   "unknown_team_rejected": self.unknown_rejected, "teams": {}}
            for name, t in self.teams.items():
                row = {k: v for k, v in t.items() if k != "use_cases"}
                row["use_cases"] = sorted(t["use_cases"])
                row["overshoot_pct"] = round(100.0 * (t["spent"] - t["budget"]) / t["budget"], 1) if t["spent"] > t["budget"] else 0.0
                out["teams"][name] = row
            return out


class Gateway:
    def __init__(self, upstream: str, mode: str, teams: dict | None = None, audit_path: str | None = None):
        assert mode in MODES, mode
        host, port = upstream.split(":")
        self.up_host, self.up_port = host, int(port)
        self.ledger = Ledger(teams or DEFAULT_TEAMS, mode)
        self.audit_path = audit_path
        self.audit_lock = threading.Lock()
        self.audit_rows: list[dict] = []
        self.admission_ms: list[float] = []

    def _upstream(self, method: str, path: str, body: dict | None, timeout: float = 600):
        c = http.client.HTTPConnection(self.up_host, self.up_port, timeout=timeout)
        try:
            c.request(method, path, body=json.dumps(body) if body is not None else None,
                      headers={"Content-Type": "application/json"})
            r = c.getresponse()
            return r.status, json.loads(r.read() or b"{}")
        finally:
            c.close()

    def count_prompt_tokens(self, messages: list) -> int:
        """Exact prompt token count: the server's own chat template, then its tokenizer."""
        _, tpl = self._upstream("POST", "/apply-template", {"messages": messages})
        _, tok = self._upstream("POST", "/tokenize", {"content": tpl["prompt"], "add_special": False, "parse_special": True})
        return len(tok["tokens"])

    def audit(self, row: dict):
        with self.audit_lock:
            self.audit_rows.append(row)
            if self.audit_path:
                with open(self.audit_path, "a") as f:
                    f.write(json.dumps(row) + "\n")

    def handle_chat(self, team: str, use_case: str, req: dict):
        t_in = time.monotonic()
        team_cfg = self.ledger.teams.get(team)
        asked = int(req.get("max_tokens") or 4096)
        cap = team_cfg["cap"] if team_cfg else asked
        max_tokens = min(asked, cap)
        prompt_tokens = 0
        if self.ledger.mode in ("estimate", "reserve") and team_cfg and use_case in team_cfg["use_cases"]:
            prompt_tokens = self.count_prompt_tokens(req.get("messages", []))
        decision, status, held, reason = self.ledger.admit(team, use_case, prompt_tokens, max_tokens)
        adm_ms = (time.monotonic() - t_in) * 1000
        row = {"ts": round(time.time(), 3), "team": team, "use_case": use_case, "decision": decision,
               "status": status, "reason": reason, "max_tokens_asked": asked, "max_tokens_sent": max_tokens,
               "reserved": held, "admission_ms": round(adm_ms, 2)}
        if decision != "admit":
            self.audit(row)
            return status, {"error": {"code": status, "message": reason}}
        with self.audit_lock:
            self.admission_ms.append(adm_ms)
        if max_tokens < asked:
            with self.ledger.lock:
                team_cfg["clamped"] += 1
        fwd = dict(req)
        fwd["max_tokens"] = max_tokens
        try:
            up_status, body = self._upstream("POST", "/v1/chat/completions", fwd)
        except Exception as e:  # noqa: BLE001 - upstream down: give the budget back
            self.ledger.release(team, held, prompt_tokens)
            row.update(decision="error", status=502, reason=str(e))
            self.audit(row)
            return 502, {"error": {"code": 502, "message": "upstream error"}}
        if up_status != 200:
            self.ledger.release(team, held, prompt_tokens)
            row.update(decision="error", status=up_status, reason="upstream status")
            self.audit(row)
            return up_status, body
        usage = body.get("usage", {})
        p, c = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        self.ledger.settle(team, held, p, c)
        row.update(prompt_tokens=p, completion_tokens=c, prompt_estimate=prompt_tokens,
                   upstream_ms=round((time.monotonic() - t_in) * 1000 - adm_ms, 1))
        self.audit(row)
        return 200, body

    def render_html(self) -> str:
        s = self.ledger.snapshot()
        rows = []
        for name, t in s["teams"].items():
            used_pct = 100.0 * t["spent"] / t["budget"]
            bar_w = min(used_pct, 150.0) / 1.5
            colour = "#3fb950" if used_pct < 80 else ("#d29922" if used_pct <= 100 else "#f85149")
            limit_mark = 100 / 1.5
            rows.append(
                f"<tr><td><b>{html.escape(name)}</b><div class=uc>{html.escape(', '.join(t['use_cases']))}</div></td>"
                f"<td class=num>{t['budget']:,}</td><td class=num>{t['spent']:,}</td><td class=num>{t['reserved']:,}</td>"
                f"<td><div class=bar><div class=fill style='width:{bar_w:.1f}%;background:{colour}'></div>"
                f"<div class=limit style='left:{limit_mark:.1f}%'></div></div><div class=pct>{used_pct:.1f}% of budget"
                + (f" &middot; <span class=over>+{t['overshoot_pct']}% over</span>" if t["overshoot_pct"] else "")
                + f"</div></td><td class=num>{t['served']}</td><td class=num>{t['rejected_budget']}</td>"
                f"<td class=num>{t['rejected_use_case']}</td><td class=num>{t['clamped']}</td></tr>")
        recent = [r for r in self.audit_rows[-8:]][::-1]
        arows = "".join(
            f"<tr><td>{time.strftime('%H:%M:%S', time.localtime(r['ts']))}</td><td>{html.escape(r['team'])}</td>"
            f"<td>{html.escape(r['use_case'] or '-')}</td><td class='d {r['decision']}'>{r['status']} {r['decision']}</td>"
            f"<td class=num>{r.get('prompt_tokens', '-')}</td><td class=num>{r.get('completion_tokens', '-')}</td>"
            f"<td class=num>{r['reserved'] or '-'}</td><td>{html.escape(r['reason'] or '')}</td></tr>" for r in recent)
        return f"""<!doctype html><html><head><meta charset=utf-8><title>LLM gateway budgets</title><style>
body{{font:14px -apple-system,Helvetica,Arial,sans-serif;background:#0d1117;color:#e6edf3;margin:24px}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#8b949e;margin-bottom:16px}}
table{{border-collapse:collapse;width:100%;margin-bottom:22px}} th,td{{padding:8px 10px;border-bottom:1px solid #30363d;text-align:left;vertical-align:top}}
th{{color:#8b949e;font-weight:600;font-size:12px;text-transform:uppercase}} .num{{text-align:right;font-variant-numeric:tabular-nums}}
.uc{{color:#8b949e;font-size:12px}} .bar{{position:relative;height:12px;background:#21262d;border-radius:6px;width:260px}}
.fill{{height:12px;border-radius:6px}} .limit{{position:absolute;top:-3px;width:2px;height:18px;background:#e6edf3}}
.pct{{font-size:12px;color:#8b949e;margin-top:4px}} .over{{color:#f85149;font-weight:600}}
.d.admit{{color:#3fb950}} .d.reject{{color:#f85149}} .d.error{{color:#d29922}} h2{{font-size:15px;margin:0 0 6px}}
.mode{{display:inline-block;padding:2px 8px;border:1px solid #30363d;border-radius:10px;color:#58a6ff}}
</style></head><body>
<h1>LLM gateway &middot; token budgets</h1>
<div class=sub>enforcement mode <span class=mode>{s['mode']}</span> &middot; window elapsed {s['elapsed_s']} s &middot; unknown-team calls rejected: {s['unknown_team_rejected']}</div>
<table><tr><th>team / registered use cases</th><th class=num>budget</th><th class=num>spent</th><th class=num>reserved</th><th>used</th>
<th class=num>served</th><th class=num>429 budget</th><th class=num>403 use case</th><th class=num>clamped</th></tr>{''.join(rows)}</table>
<h2>Audit log (latest)</h2>
<table><tr><th>time</th><th>team</th><th>use case</th><th>decision</th><th class=num>prompt</th><th class=num>completion</th><th class=num>reserved</th><th>reason</th></tr>{arows}</table>
</body></html>"""

    def serve(self, port: int) -> ThreadingHTTPServer:
        gw = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, status, body, ctype="application/json"):
                data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                if status == 429:
                    self.send_header("Retry-After", "5")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/budgets":
                    return self._send(200, gw.render_html(), "text/html; charset=utf-8")
                if self.path == "/budgets.json":
                    return self._send(200, gw.ledger.snapshot())
                return self._send(404, {"error": "not found"})

            def do_POST(self):
                if self.path != "/v1/chat/completions":
                    return self._send(404, {"error": "not found"})
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                status, body = gw.handle_chat(self.headers.get("x-team", ""), self.headers.get("x-use-case", ""), req)
                return self._send(status, body)

        class Server(ThreadingHTTPServer):
            request_queue_size = 256  # default 5 resets connections when 20 clients connect at once

        srv = Server(("127.0.0.1", port), H)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default="127.0.0.1:18431")
    ap.add_argument("--port", type=int, default=18440)
    ap.add_argument("--mode", choices=MODES, default="reserve")
    ap.add_argument("--audit", default=None)
    a = ap.parse_args()
    Gateway(a.upstream, a.mode, audit_path=a.audit).serve(a.port)
    print(f"gateway on 127.0.0.1:{a.port} -> {a.upstream} mode={a.mode}")
    while True:
        time.sleep(3600)
