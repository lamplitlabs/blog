---
layout: post
title: "AI Security: A Shared Prompt Cache Leaks Other Tenants' Prompts - Measured on llama.cpp"
date: 2026-11-26 10:00:00 +0000
categories: ai
author: manishtiwari25
description: "One shared llama-server: 5 of 5 secret codes read from another tenant's system prompt in 60 probes. Stripping cache fields failed; a per-tenant salt worked."
image:
  path: /assets/img/headers/ai/ai-security-prompt-cache-tenant-leaks-measured.webp
  alt: "Header card titled Your shared prompt cache talks. 5 of 5 six-digit approval codes read out of another tenant's system prompt via cached_tokens, median 60 probes each. 100% right on whether a 2k-token document was sent, from wall time alone: 11 ms versus 186 ms. Bars: stripping cache fields 100%, cache_prompt false 100%, per-tenant cache salt 58%."
tags: [ai-security, enterprise-ai, llm, caching, multi-tenant, side-channel, llama.cpp, python, benchmark]
---

Prompt caching is the cheapest speed-up in LLM serving. If a request starts with the same tokens as an earlier one, the server reuses the key/value state it already computed and skips that part of prefill. Every hosted API and every self-hosted server does it, and enterprise gateways expose it on purpose: `usage.prompt_tokens_details.cached_tokens` is how you check that your [prompt ordering]({% post_url AI/2026-10-10-azure-openai-prompt-caching-dotnet %}) works and how chargeback gives cached input a discount.

That cache is shared state, though. When two teams, two customers or two agents share one model server, the cache sits between them. This post measures what one tenant can learn about another tenant's prompts through it, on a real llama.cpp server on my laptop, and which of the usual fixes actually close the gap.

Short version:

- **Reading a secret out of another tenant's system prompt took 60 requests.** Through `cached_tokens` alone, the attacker recovered **5 of 5** six-digit approval codes, one digit at a time.
- **Stripping the cache fields at the gateway does not help against membership tests.** Wall time alone told whether the victim had sent a given 2,048-token document in **40 of 40** trials (11 ms vs 186 ms).
- **`cache_prompt: false` on each request does not close it either** on llama.cpp build 12359: still **100%**, because the server picks the slot by prompt similarity and keeps a RAM prompt cache.
- **A per-tenant salt at the start of the prompt does close it:** **57.5%**, which is a coin flip at 40 trials. It cost the victim nothing (11 ms vs 12 ms per call), while turning caching off cost 16x (183 ms).

## The setup

One `llama-server` (llama.cpp build 12359, Metal) serves SmolLM2-135M-Instruct on an Apple M2 Pro with 4 slots (`-np 4 -c 32768`). Two tenants share it:

- The **victim** calls it like a normal chat app. Each request carries the same system prompt and a new user question. In the extraction test, the system prompt is a treasury assistant with a secret in it:

  > You are the treasury assistant for {org}. Follow the payment runbook. Wire approval code: {code}. Never reveal the approval code to anyone. ...

- The **attacker** sends its own requests with `max_tokens: 1`. It never sees the victim's traffic. It only sees its own replies and how long they took.

A small gateway function sits in front of the server. Depending on the policy, it passes replies through, strips `timings` and `prompt_tokens_details`, adds a per-tenant salt, or sets `cache_prompt: false`. The benchmark (`scripts/prompt-cache-timing/bench.py`, standard library only) plays both tenants in turn: one victim call, then one attacker probe. It is seeded, and the whole run takes 8 minutes.

The model is tiny on purpose. Nothing here depends on what the model says: the attacker asks for one token and ignores it. What matters is the server's prefix cache, and a larger model only widens the timing gap, because each uncached prompt token costs more.

## Attack 1: read the secret through `cached_tokens`

The attacker knows (or guesses) the template, which is common for a product's system prompt. It sends `template prefix + known digits + one guessed digit` and reads `cached_tokens` from the reply. The guess that matches the victim's next digit shares one more token with the cached prefix, so it comes back with one more cached token. Ten guesses per digit, six digits: 60 requests.

![Terminal panel from bench.py extract. Ten probes for the first digit of the Woodgrove approval code, each with 38 prompt tokens. Nine come back with cached_tokens 24, digit 5 with 25, marked as the longest cached prefix. Wall times are 8 to 13 ms with no clear pattern. Bottom line: recovered 534165, true code 534165, 60 probes.](/assets/img/posts/ai/prompt-cache-extract-transcript.webp)

The panel shows real replies for the first digit. Nine guesses come back with 24 cached tokens. The right one comes back with 25. All five secrets were recovered exactly, with 60 probes each. No tie needed a second round.

The same attack using wall time only failed: **3 of 30** digits right with 180 probes per secret, which is what random guessing gives. One extra cached token saves about 0.1 ms of prefill on this model. The noise on a single request is several milliseconds. So `cached_tokens` is the dangerous field here, not the clock. It turns a sub-millisecond difference into an exact integer.

An earlier version of the benchmark gave a less clean result (2 of 5). The cause was in the test, not the server: two secrets used the same company name, so the first secret's prompt stayed in another slot and blurred the second one. The final run gives each tenant its own organisation name. If anything, that is one more warning: whatever else sits in the cache changes what the attacker sees.

## Attack 2: did they send this document?

Membership is the more practical question. Has someone uploaded this contract? Is this the system prompt the competitor's bot runs on? Did anyone paste the leaked memo? The attacker takes a candidate document, sends it as its own prompt, and times the reply. For control, it also sends a fresh document of the same length that nobody sent. The order is randomised per trial.

![Dot plot of attacker wall times on a log scale at four prompt lengths, 40 trials each. Red dots for the victim's document, blue for a same-length fresh one. 26 tokens: sent 8 ms, not sent 14 ms. 140 tokens: 8 versus 17 ms. 512 tokens: 8 versus 38 ms. 2051 tokens: 11 versus 186 ms. The pair guess is right 100% of the time at every length.](/assets/img/posts/ai/prompt-cache-hit-miss-latency.webp)

| Shared prefix (tokens) | Sent, p50 | Not sent, p50 | Pair guess right | Fixed threshold right (held-out half) |
|---:|---:|---:|---:|---:|
| 26 | 7.9 ms | 13.9 ms | 100% | 97.5% |
| 140 | 8.3 ms | 17.2 ms | 100% | 100% |
| 512 | 8.3 ms | 38.2 ms | 100% | 100% |
| 2,048 | 11.3 ms | 186.1 ms | 100% | 90.0% |

"Pair guess" is the simplest attacker: send the candidate and a control, and call the faster one "sent". "Fixed threshold" picks one cut-off on the first 20 trials and scores it on the other 20, so the attacker needs no control request at all. It drops to 90% at 2,048 tokens only because a few uncached probes landed on an idle moment of a loaded host. The pair guess was never wrong.

Even 26 tokens, a short sentence, gave a 6 ms gap. Prefill time grows with prompt length, and the cached path barely does, so longer documents are easier to detect, not harder.

## Which fix closes it

I ran the 2,048-token membership test 40 more times under each gateway policy, plus the extraction test. Then I ran it against a second server started with the strictest cache flags I could find: `--cache-ram 0` (no prompt cache in RAM) and `-sps 0` (do not pick the slot by prompt similarity).

![Bar chart of pair guess accuracy at 2,048 tokens. Default server 100% with code read 5 of 5. Gateway strips cache fields 100%. cache_prompt false 100%. Per-tenant salt 58%. Hardened server with --cache-ram 0 -sps 0: 52% after one victim call, 100% after four victim calls, 60% with cache_prompt false, 42% with salt. Victim cost per call: pass-through 12 ms, salt 11 ms, cache_prompt false 183 ms.](/assets/img/posts/ai/prompt-cache-mitigations.webp)

| Policy | Membership right (pair) | Secret code read | Victim's own call, p50 |
|---|---:|---|---:|
| Pass-through (default) | 100% | 5 of 5 | 11.5 ms |
| Gateway strips `timings` + `prompt_tokens_details` | 100% | no (field gone) | 11.5 ms |
| Request sets `cache_prompt: false` | 100% | no (field gone) | 183.0 ms |
| Per-tenant salt at the start of the prompt | **57.5%** | no | **10.9 ms** |
| Hardened server, victim 1 call between probes | 52.5% | - | - |
| Hardened server, victim 4 calls between probes | **100%** | - | - |
| Hardened server + `cache_prompt: false` | 60.0% | - | - |
| Hardened server + per-tenant salt | 42.5% | - | - |

What each row says:

1. **Stripping the fields only stops the exact-integer attack.** The attacker loses `cached_tokens`, but a 175 ms gap needs no field to be seen. If your gateway forwards prompt-cache discounts, the discount itself is a signal too: a cheaper bill means a cache hit.
2. **`cache_prompt: false` is a request flag, not an isolation boundary.** On this build, the server log shows why. Even with the flag set, the next request is sent to the slot whose stored prompt is most similar (`selected slot by LCP similarity, f_sim_best = 1.000`). Prefill on that slot was still faster, and the attacker's own probes ran at 177 ms vs 412 ms. It is also the most expensive fix: the victim's own calls went from 11 ms to 183 ms.
3. **Server flags help until the victim gets busy.** With `--cache-ram 0 -sps 0`, slots are picked by least-recently-used. After one victim call, the attacker usually lands on a different slot: 52.5%. After four victim calls, the victim's prompt is in every slot, and the attacker is back to 100%. Slot reuse is a cache too, whatever the flags say.
4. **The per-tenant salt is the one fix that held everywhere and cost nothing.** The gateway puts a secret, per-tenant value (here `[cache scope <16 hex>]`) at the very start of the system prompt. Requests from the same tenant still share a prefix, so the victim keeps its cache hits (10.9 ms). The attacker's request diverges from the victim's after the chat template's first few tokens, so no guess can get a longer match than any other.

The salt is what the hosted providers converged on as well: caches scoped per organisation, plus a cache key you can set yourself. If you run your own inference for several teams or customers, the gateway is the place to do it. It already knows the tenant (it bills it, see [token budgets]({% post_url AI/2026-11-07-enterprise-ai-token-budgets-concurrency-measured %})), so the salt is one more line in the policy. Scope matters: per tenant, not per user, unless users in one tenant must not learn about each other's prompts. In that case the salt is per user, and you lose cross-user cache hits.

## What this does not show

- **Remote attackers face more noise.** My probes ran over localhost. Over a network, the 6 ms gap at 26 tokens would need repeated probes. The 175 ms gap at 2,048 tokens would not.
- **Real traffic is mixed.** Here the victim called between every probe. With other tenants on the server, the victim's prompt can be evicted before the attacker probes. That makes the attack slower, not impossible, and a popular system prompt stays cached almost all the time.
- **Batch and engine differences.** vLLM, TGI and hosted APIs use different cache layouts (block hashing, per-org scoping). The mechanism is the same: shared prefix state plus a measurable difference. Test your own stack with the same two probes.
- **The salt needs to stay secret.** If an attacker learns another tenant's salt, it can rebuild their prefix. Derive it from a server-side key, never from the tenant name alone. (The benchmark uses a hash of the tenant name to stay reproducible.)

## Reproduce it

```bash
# Needs: CPython 3.11+, llama-server on PATH, SmolLM2-135M-Instruct in the HF cache.
python3 scripts/finetune-eval/hf_to_gguf.py ~/.cache/huggingface/hub/models--HuggingFaceTB--SmolLM2-135M-Instruct/snapshots/<rev> /tmp/smol.gguf
llama-server -m /tmp/smol.gguf --port 18693 -np 4 -c 32768 -ngl 99 &
llama-server -m /tmp/smol.gguf --port 18694 -np 4 -c 32768 -ngl 99 --cache-ram 0 -sps 0 &
python3 scripts/prompt-cache-timing/bench.py --llm 127.0.0.1:18693 --hardened 127.0.0.1:18694 --out /tmp/pc/raw.json  # ~8 min
python3 scripts/prompt-cache-timing/summarise.py /tmp/pc   # -> scripts/data/prompt-cache-timing-leaks.json
python3 scripts/prompt-cache-timing/gen_images.py          # the images in this post
```

Every number above comes from [`scripts/data/prompt-cache-timing-leaks.json`](https://github.com/lamplitlabs/blog/blob/main/scripts/data/prompt-cache-timing-leaks.json). It keeps every hit and miss latency, each secret's recovered digits next to the true ones, and the per-digit log behind the screenshot. The run is seeded (`--seed 20261126`). Timings move by 10-20% with host load, but the gaps are 6x to 16x, so the conclusions do not.

## Where Hive fits

[Hive](https://hivefleet.dev/) is Lamplit Labs' open-source, self-improving (RSI) agent harness. It runs agents on the owner's own machine, and they call whichever model provider or local model server the owner chooses. When several projects point at one local llama.cpp, Ollama or vLLM server, their requests share that server's prompt cache, which is exactly the setup this post measures. The fix measured above applies there too: a per-project salt at the start of the prompt, rather than a hope that nobody times the responses. The [Hive introduction]({% post_url AI/2026-10-25-hive-self-improving-rsi-agent-harness %}) has more on how it works.

## Related posts

- [Azure OpenAI Prompt Caching in .NET: Cut Latency and Input Cost by Ordering Your Prompt Right]({% post_url AI/2026-10-10-azure-openai-prompt-caching-dotnet %})
- [AI Security: Document Permissions in RAG, Measured - Prompt Rules, Post-filters, Pre-filters and Caches]({% post_url AI/2026-11-25-ai-security-rag-document-permissions-measured %})
- [Enterprise AI: Token Budgets That Hold Under Concurrency - Measured on an LLM Gateway]({% post_url AI/2026-11-07-enterprise-ai-token-budgets-concurrency-measured %})
- [Enterprise AI: Audit Logging and Policy Controls for an LLM Gateway]({% post_url AI/2026-10-23-enterprise-ai-llm-gateway-audit-logging-policy-controls %})
- [AI Security: Secrets in Agent Logs, Measured - What gitleaks and Redaction Actually Catch]({% post_url AI/2026-11-02-ai-security-secrets-in-agent-logs-measured %})
- [Hive: Lamplit Labs' open-source, self-improving (RSI) agent harness]({% post_url AI/2026-10-25-hive-self-improving-rsi-agent-harness %})
