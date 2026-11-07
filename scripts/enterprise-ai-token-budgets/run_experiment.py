#!/usr/bin/env python3
"""Drive gateway.py with a seeded enterprise workload and record what each budget mode lets through.

    python3 scripts/enterprise-ai-token-budgets/run_experiment.py --upstream 127.0.0.1:18431 \
        --modes none,post,estimate,reserve --conc 16 --reps 3 --out .tmp/budgets-raw.jsonl

Per run, with a fresh gateway ledger:
  * batch-summariser: N_BATCH weekly-digest calls (about 350 prompt tokens, max_tokens 1024),
    pulled from one queue by --conc workers; a 429 drops the item (no retry) and the worker moves on.
  * support-bot: N_SUPPORT triage calls from 2 workers asking max_tokens 4096 (the gateway clamps to 512).
  * finance-ops: N_SHADOW calls under a use case that is not in its register, and the same count from
    a team the gateway has never heard of (both must get 403 and cost nothing).
Writes one JSON line per run: the final ledger snapshot plus client-side timings.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import random
import statistics
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gateway import Gateway  # noqa: E402

N_BATCH, N_SUPPORT, N_SHADOW = 60, 24, 6
WORDS = ("invoice refund seat licence renewal outage login password export report delay escalation contract "
         "vendor payment overdue discount VAT region tenant migration backup SSO audit quota credit note "
         "purchase order dispute onboarding offboarding").split()


def batch_items(seed: int):
    rng = random.Random(seed)
    items = []
    for i in range(N_BATCH):
        thread = " ".join(rng.choice(WORDS) for _ in range(rng.randint(260, 320)))
        items.append({"messages": [
            {"role": "system", "content": "You summarise support ticket threads for the weekly account review. "
                                          "Write a detailed summary with every action item."},
            {"role": "user", "content": f"Account A-{1000 + i}. Thread:\n{thread}"}],
            "max_tokens": 1024, "temperature": 0.8, "seed": i})
    return items


def support_items(seed: int):
    rng = random.Random(seed + 7)
    asks = ["Our March invoice shows 12 seats but we cancelled 4 on 2 March. Please correct it.",
            "SSO login fails for two users since this morning with error AADSTS50105.",
            "Can you send the credit note for order PO-5531 again? The PDF link expired.",
            "We need the VAT number added to all invoices from April onwards."]
    return [{"messages": [
        {"role": "system", "content": "You are the Contoso support triage assistant. Give a category, a priority and a two-line reply."},
        {"role": "user", "content": f"Ticket {4400 + i}: {rng.choice(asks)}"}],
        "max_tokens": 4096, "temperature": 0.7, "seed": i} for i in range(N_SUPPORT)]


def call(port: int, team: str, use_case: str, body: dict):
    t0 = time.monotonic()
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=900)
    try:
        c.request("POST", "/v1/chat/completions", body=json.dumps(body),
                  headers={"Content-Type": "application/json", "x-team": team, "x-use-case": use_case})
        r = c.getresponse()
        data = json.loads(r.read() or b"{}")
        return r.status, data, (time.monotonic() - t0) * 1000
    finally:
        c.close()


def run_once(upstream: str, port: int, mode: str, conc: int, rep: int, audit_dir: str | None):
    audit = os.path.join(audit_dir, f"audit-{mode}-c{conc}-r{rep}.jsonl") if audit_dir else None
    if audit and os.path.exists(audit):
        os.remove(audit)
    gw = Gateway(upstream, mode, audit_path=audit)
    srv = gw.serve(port)
    results = {"batch": [], "support": [], "shadow": []}
    lock = threading.Lock()
    queue = list(batch_items(rep))
    qlock = threading.Lock()

    def batch_worker():
        while True:
            with qlock:
                if not queue:
                    return
                item = queue.pop(0)
            st, data, ms = call(port, "batch-summariser", "UC-112 weekly account digest", item)
            with lock:
                results["batch"].append({"status": st, "ms": ms, "usage": data.get("usage")})

    sup = support_items(rep)
    slock = threading.Lock()

    def support_worker():
        while True:
            with slock:
                if not sup:
                    return
                item = sup.pop(0)
            st, data, ms = call(port, "support-bot", "UC-101 ticket triage", item)
            with lock:
                results["support"].append({"status": st, "ms": ms, "usage": data.get("usage")})

    def shadow_worker():
        body = {"messages": [{"role": "user", "content": "Summarise this vendor contract and flag risky clauses."}],
                "max_tokens": 2048}
        for _ in range(N_SHADOW):
            st, _, ms = call(port, "finance-ops", "ad-hoc contract review", body)
            st2, _, ms2 = call(port, "marketing-sandbox", "unregistered", body)
            with lock:
                results["shadow"] += [{"status": st, "ms": ms, "who": "unregistered use case"},
                                      {"status": st2, "ms": ms2, "who": "unknown team"}]
            time.sleep(0.5)

    t0 = time.monotonic()
    threads = [threading.Thread(target=batch_worker) for _ in range(conc)]
    threads += [threading.Thread(target=support_worker) for _ in range(2)]
    threads += [threading.Thread(target=shadow_worker)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.monotonic() - t0
    snap = gw.ledger.snapshot()
    srv.shutdown()
    srv.server_close()
    adm = sorted(gw.admission_ms)
    pct = lambda xs, q: xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None  # noqa: E731
    return {"mode": mode, "conc": conc, "rep": rep, "wall_s": round(wall, 1), "ledger": snap,
            "admission_ms_p50": round(pct(adm, 0.5), 2) if adm else None,
            "admission_ms_p95": round(pct(adm, 0.95), 2) if adm else None,
            "batch_statuses": {str(k): sum(1 for r in results["batch"] if r["status"] == k) for k in (200, 429, 403, 502)},
            "batch_completion_tokens": [r["usage"]["completion_tokens"] for r in results["batch"] if r["usage"]],
            "support_completion_tokens": [r["usage"]["completion_tokens"] for r in results["support"] if r["usage"]],
            "support_ms_p50": round(statistics.median([r["ms"] for r in results["support"] if r["status"] == 200]), 1),
            "shadow_statuses": {w: [r["status"] for r in results["shadow"] if r["who"] == w]
                                for w in ("unregistered use case", "unknown team")},
            "budget_429_ms_p50": round(statistics.median([r["ms"] for r in results["batch"] if r["status"] == 429]), 1)
            if any(r["status"] == 429 for r in results["batch"]) else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default="127.0.0.1:18431")
    ap.add_argument("--port", type=int, default=18440)
    ap.add_argument("--modes", default="none,post,estimate,reserve")
    ap.add_argument("--conc", default="16")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", required=True)
    ap.add_argument("--audit-dir", default=None)
    a = ap.parse_args()
    if a.audit_dir:
        os.makedirs(a.audit_dir, exist_ok=True)
    n = 0
    for rep in range(a.reps):
        for conc in [int(c) for c in a.conc.split(",")]:
            for mode in a.modes.split(","):
                row = run_once(a.upstream, a.port + n, mode, conc, rep, a.audit_dir)
                n += 1
                b = row["ledger"]["teams"]["batch-summariser"]
                print(f"{mode:9s} c={conc:2d} rep={rep} wall={row['wall_s']:6.1f}s spent={b['spent']:6d}/{b['budget']} "
                      f"over={b['overshoot_pct']:5.1f}% served={b['served']:2d} 429={b['rejected_budget']:2d} "
                      f"peak_in_flight={b['peak_in_flight']:2d} adm_p50={row['admission_ms_p50']}ms", flush=True)
                with open(a.out, "a") as f:
                    f.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
