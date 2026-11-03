#!/usr/bin/env python3
"""Open-loop load generator for llama-server /completion (stdlib only).

Usage: python3 scripts/llama_server_loadgen.py PORT OUT.jsonl [N_REQUESTS] [RATE_PER_S]
Used for the continuous batching post; scripts/summarise_continuous_batching_runs.py
turns the runs into the JSON the post's charts are drawn from.

Same seeded arrival schedule, prompts and output lengths for every config and run,
so the only thing that changes between configs is the server's scheduler.
Writes one JSON line per request with client-side timestamps of every streamed token.
"""
import http.client, json, random, sys, threading, time

PORT = int(sys.argv[1])
OUT = sys.argv[2]
N_REQ = int(sys.argv[3]) if len(sys.argv) > 3 else 48
RATE = float(sys.argv[4]) if len(sys.argv) > 4 else 4.0 / 3.0  # requests per second
SEED = 20261101

rng = random.Random(SEED)
WORDS = ("latency throughput kernel cache tensor batch slot token decode prefill memory bandwidth "
         "request queue scheduler server model weight attention layer head vector matrix sequence "
         "prompt stream budget tail median percentile arrival window context compute graph metal "
         "apple silicon quantized block scale value key shift rope norm residual feed forward gate").split()

reqs = []
t = 0.0
for i in range(N_REQ):
    t += rng.expovariate(RATE)
    n_words = rng.randint(48, 190)          # roughly 64-256 prompt tokens
    prompt = "Summarise the following notes.\n" + " ".join(rng.choice(WORDS) for _ in range(n_words))
    # long-tailed output lengths: most answers are short, a few are long
    n_predict = rng.choice([32, 48, 64, 96, 128, 128, 192, 256, 384, 512])
    reqs.append({"id": i, "arrive": t, "prompt": prompt, "n_predict": n_predict})

results = [None] * N_REQ
T0 = None


def run(r):
    delay = T0 + r["arrive"] - time.perf_counter()
    if delay > 0:
        time.sleep(delay)
    sent = time.perf_counter()
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=3600)
    body = json.dumps({"prompt": r["prompt"], "n_predict": r["n_predict"], "ignore_eos": True,
                       "temperature": 0, "cache_prompt": False, "stream": True})
    conn.request("POST", "/completion", body, {"Content-Type": "application/json"})
    resp = conn.getresponse()
    stamps, timings = [], None
    while True:
        line = resp.readline()
        if not line:
            break
        line = line.strip()
        if not line.startswith(b"data: "):
            continue
        now = time.perf_counter()
        d = json.loads(line[6:])
        if d.get("stop"):
            timings = d.get("timings")
            break
        stamps.append(now)
    conn.close()
    results[r["id"]] = {"id": r["id"], "arrive": r["arrive"], "sent": sent - T0,
                        "n_predict": r["n_predict"], "tokens": len(stamps),
                        "first": (stamps[0] - T0) if stamps else None,
                        "done": time.perf_counter() - T0,
                        "gaps": [round(b - a, 5) for a, b in zip(stamps, stamps[1:])],
                        "timings": timings}


threads = [threading.Thread(target=run, args=(r,)) for r in reqs]
T0 = time.perf_counter() + 0.5
for th in threads:
    th.start()
for th in threads:
    th.join()
with open(OUT, "w") as f:
    for res in results:
        f.write(json.dumps(res) + "\n")
print(OUT, "makespan %.1fs" % max(r["done"] for r in results),
      "tokens", sum(r["tokens"] for r in results))
