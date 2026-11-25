#!/usr/bin/env python3
"""Measure what the serialisation format of ERP records costs inside an LLM prompt.

The same seeded vendor-invoice rows are written as pretty JSON, minified JSON, YAML, XML, a
Markdown table and CSV. For each format the script asks a running llama-server for:

  * the exact prompt token count (POST /tokenize, the model's own tokenizer),
  * the prefill time of a 100-record prompt (POST /completion, n_predict 1, cache_prompt false,
    median of --reps runs, read from the server's own `timings.prompt_ms`).

From the token counts it works out tokens per record and how many records fit into the model's
context window after a fixed reserve for instructions and the answer.

    llama-server -m .tmp/smollm2-135m.gguf -c 8192 --port 8093 &
    python3 scripts/enterprise-ai-prompt-formats/measure.py --port 8093 \
        --out scripts/data/enterprise-ai-prompt-formats.json | tee .tmp/formats-term.txt

Standard library only. The records are synthetic (seed 20261124); no real vendor data.
"""
from __future__ import annotations

import argparse
import csv
import http.client
import io
import json
import random
import statistics
import time
from xml.sax.saxutils import escape

SEED = 20261124
VENDORS = [
    "Contoso Office Supply GmbH", "Fabrikam Logistics B.V.", "Northwind Traders Ltd",
    "Adventure Works Cycles", "Litware Facility Services", "Tailspin Toys AB",
    "Wide World Importers", "Proseware, Inc.", "Woodgrove Print & Mail", "Alpine Ski House",
]
CURRENCIES = ["EUR", "EUR", "EUR", "USD", "GBP", "SEK"]
ACCOUNTS = ["600110", "600120", "612000", "615300", "620400", "640100", "655000"]
COST_CENTRES = ["CC-1010", "CC-1020", "CC-2040", "CC-3100", "CC-4200"]
STATUSES = ["Open", "Approved", "OnHold", "Posted"]
LINES = [
    "Toner cartridges and paper, Q4 restock", "Pallet freight Rotterdam to Hamburg",
    "Monthly cleaning contract, building B", "Courier, same-day, legal documents",
    "Laptop docking stations (12 units)", "Annual licence renewal, plotting software",
    "Canteen coffee beans, 40 kg", "Reprint of safety manuals, 500 copies",
]
FIELDS = ["invoice_id", "vendor_account", "vendor_name", "invoice_date", "due_date", "currency",
          "amount", "vat", "main_account", "cost_centre", "status", "description"]
FORMATS = ["json_pretty", "json_min", "yaml", "xml", "markdown", "csv"]
LABEL = {"json_pretty": "JSON (indent 2)", "json_min": "JSON (minified)", "yaml": "YAML",
         "xml": "XML", "markdown": "Markdown table", "csv": "CSV"}
INSTRUCTIONS = ("You code vendor invoices for accounts payable. Below are open invoices from the ERP. "
                "Answer the question using only these records.\n\n")
QUESTION = "\n\nQuestion: which invoices from Fabrikam Logistics B.V. are on hold, and what is their total amount?"


def records(n: int) -> list[dict]:
    rnd = random.Random(SEED)
    out = []
    for i in range(n):
        v = rnd.randrange(len(VENDORS))
        day = rnd.randrange(1, 29)
        amount = round(rnd.uniform(40, 25000), 2)
        out.append({
            "invoice_id": f"INV-{2026_0000 + 17 * i + rnd.randrange(17):08d}",
            "vendor_account": f"V{10040 + 7 * v:06d}",
            "vendor_name": VENDORS[v],
            "invoice_date": f"2026-10-{day:02d}",
            "due_date": f"2026-11-{day:02d}",
            "currency": rnd.choice(CURRENCIES),
            "amount": amount,
            "vat": round(amount * 0.19, 2),
            "main_account": rnd.choice(ACCOUNTS),
            "cost_centre": rnd.choice(COST_CENTRES),
            "status": rnd.choice(STATUSES),
            "description": rnd.choice(LINES),
        })
    return out


def yaml_scalar(v) -> str:
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v)
    # Quote what a YAML parser would otherwise read as a number, a date or a mapping.
    if any(c in s for c in ":#,&[]{}") or s[:1].isdigit():
        return '"' + s.replace('"', '\\"') + '"'
    return s


def serialise(rows: list[dict], fmt: str) -> str:
    if fmt == "json_pretty":
        return json.dumps(rows, indent=2, ensure_ascii=False)
    if fmt == "json_min":
        return json.dumps(rows, separators=(",", ":"), ensure_ascii=False)
    if fmt == "yaml":
        out = []
        for r in rows:
            for j, k in enumerate(FIELDS):
                out.append(("- " if j == 0 else "  ") + f"{k}: {yaml_scalar(r[k])}")
        return "\n".join(out)
    if fmt == "xml":
        out = ["<invoices>"]
        for r in rows:
            out.append("  <invoice>")
            out += [f"    <{k}>{escape(str(r[k]))}</{k}>" for k in FIELDS]
            out.append("  </invoice>")
        out.append("</invoices>")
        return "\n".join(out)
    if fmt == "markdown":
        out = ["| " + " | ".join(FIELDS) + " |", "|" + "---|" * len(FIELDS)]
        out += ["| " + " | ".join(str(r[k]) for k in FIELDS) + " |" for r in rows]
        return "\n".join(out)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue().rstrip("\n")
    raise ValueError(fmt)


def post(port: int, path: str, body: dict) -> dict:
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=600)
    c.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
    r = c.getresponse()
    data = r.read()
    if r.status != 200:
        raise RuntimeError(f"{path}: HTTP {r.status} {data[:200]!r}")
    return json.loads(data)


def n_tokens(port: int, text: str) -> int:
    return len(post(port, "/tokenize", {"content": text, "add_special": False})["tokens"])


def props(port: int) -> dict:
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.request("GET", "/props")
    return json.loads(c.getresponse().read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8093)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--prefill-records", type=int, default=100)
    ap.add_argument("--reserve", type=int, default=1024, help="tokens kept free for instructions and the answer")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    p = props(a.port)
    n_ctx = p.get("default_generation_settings", {}).get("n_ctx") or p.get("n_ctx")
    model = p.get("model_path", "?").rsplit("/", 1)[-1]
    sizes = [1, 10, 50, 200]
    rows = records(max(sizes))
    print(f"model {model}  n_ctx {n_ctx}  seed {SEED}  fields {len(FIELDS)}")
    print(f"{'format':<17}{'1 rec':>7}{'10':>7}{'50':>7}{'200':>8}{'tok/rec':>9}{'chars/tok':>11}{'fit':>6}{'vs csv':>8}")

    res = {}
    for fmt in FORMATS:
        counts = {n: n_tokens(a.port, serialise(rows[:n], fmt)) for n in sizes}
        chars200 = len(serialise(rows[:200], fmt))
        per_rec = (counts[200] - counts[50]) / 150
        overhead = counts[50] - per_rec * 50
        # Largest record count whose serialisation still fits, found with the real tokenizer.
        lo, hi = 1, len(rows)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if n_tokens(a.port, serialise(rows[:mid], fmt)) <= n_ctx - a.reserve:
                lo = mid
            else:
                hi = mid - 1
        fit = lo
        res[fmt] = {"label": LABEL[fmt], "tokens": {str(k): v for k, v in counts.items()},
                    "chars_200": chars200, "tokens_per_record": round(per_rec, 2),
                    "fixed_overhead": round(overhead, 1), "chars_per_token": round(chars200 / counts[200], 2),
                    "records_fit": fit}
    base = res["csv"]["tokens_per_record"]
    for fmt in FORMATS:
        r = res[fmt]
        r["vs_csv"] = round(r["tokens_per_record"] / base, 2)
        t = r["tokens"]
        print(f"{fmt:<17}{t['1']:>7}{t['10']:>7}{t['50']:>7}{t['200']:>8}{r['tokens_per_record']:>9.1f}"
              f"{r['chars_per_token']:>11.2f}{r['records_fit']:>6}{r['vs_csv']:>7.2f}x")

    print(f"\nprefill of {a.prefill_records} records + instructions + question, cache_prompt=false, median of {a.reps}")
    print(f"{'format':<17}{'prompt tok':>11}{'prefill ms':>12}{'min':>9}{'max':>9}{'tok/s':>9}")
    for fmt in FORMATS:
        prompt = INSTRUCTIONS + serialise(rows[:a.prefill_records], fmt) + QUESTION
        ms, n = [], None
        post(a.port, "/completion", {"prompt": prompt, "n_predict": 1, "cache_prompt": False})  # warm-up
        for _ in range(a.reps):
            r = post(a.port, "/completion", {"prompt": prompt, "n_predict": 1, "cache_prompt": False,
                                             "temperature": 0})
            ms.append(r["timings"]["prompt_ms"])
            n = r["timings"]["prompt_n"]
        med = statistics.median(ms)
        res[fmt]["prefill"] = {"records": a.prefill_records, "prompt_tokens": n, "ms_median": round(med, 1),
                               "ms_min": round(min(ms), 1), "ms_max": round(max(ms), 1),
                               "ms_all": [round(x, 1) for x in ms], "tok_per_s": round(n / med * 1000)}
        print(f"{fmt:<17}{n:>11}{med:>12.1f}{min(ms):>9.1f}{max(ms):>9.1f}{n / med * 1000:>9.0f}")

    out = {"setup": {"model": model, "n_ctx": n_ctx, "seed": SEED, "fields": FIELDS, "sizes": sizes,
                     "reserve": a.reserve, "reps": a.reps, "server": "llama-server (llama.cpp), Metal, Apple M2 Pro",
                     "measured": time.strftime("%Y-%m-%d")},
           "sample": {fmt: serialise(rows[:2], fmt) for fmt in FORMATS},
           "formats": res}
    with open(a.out, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
