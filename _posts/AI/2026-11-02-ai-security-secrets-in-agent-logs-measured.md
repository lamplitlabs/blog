---
layout: post
title: "AI Security: Secrets in Agent Logs, Measured - What gitleaks and Redaction Actually Catch"
date: 2026-11-02 06:00:00 +0100
categories: ai
author: manishtiwari25
description: "264 fake secrets in 200 AI agent session logs: gitleaks caught 53%, exact-value redaction 42%, encoding-aware redaction plus a decoded scan 90%."
image:
  path: /assets/img/headers/ai/ai-security-secrets-in-agent-logs-measured.webp
  alt: "Header card titled Secrets in AI agent logs, measured: 264 fake secrets planted in 200 agent sessions (18,947 log records), 11 leak shapes x 24 each. Five horizontal bars show the share each defence redacted or flagged: exact-value redaction 42% (110/264), gitleaks on the stored JSONL 53% (140/264), gitleaks with a tuned config on a decoded view 75% (197/264), encoding-aware redaction 82% (216/264), and encoding-aware redaction plus the tuned decoded scan 90% (238/264)"
tags: [ai-security, agents, secrets, llm, observability, benchmark, gitleaks]
---

A coding agent writes down everything it sees. Every `env` it runs, every `.env` it reads, every `curl -v` it uses to debug a 401, and every token of every reply ends up in a session transcript. Teams keep those transcripts for debugging, ship them to an observability stack, and paste them into bug reports. The [sandboxing post]({% post_url AI/2026-10-30-ai-security-sandboxing-agent-tool-calls %}) covered how to keep secrets out of a tool's reach. This post is about what happens when one gets through anyway: a secret lands in the agent log. What removes it?

The usual answers are "we redact known secrets before writing" and "we run a secret scanner over the logs". We measured both. We planted 264 fake secrets in 200 synthetic agent sessions, in the shapes they really take in agent output, and checked which secrets each defence removed or flagged.

**The short version:**

- **gitleaks with default rules flagged 140 of 264 (53%) on the stored JSONL.** It found nothing in streamed replies, where each token is its own log record, and nothing in connection-URL passwords. 693 of its 849 findings (82%) were idempotency keys, not secrets.
- **Exact-value redaction at write time removed 110 of 264 (42%).** It knows every secret the runtime holds, but it misses the same value once it is base64-encoded, percent-encoded or split across stream records.
- **Encoding-aware redaction with a stream holdback removed 216 (82%).** It cost 0.5 s of extra write time per 4.4 MB of logs.
- **That redaction plus a tuned gitleaks scan of a decoded view reached 238 (90%).** The 26 secrets left were all 24 hexdumps (0/24 for every defence) and 2 passwords hard-coded in a source file.

## The setup

Everything below comes from one script, `scripts/agent_log_secret_leak_bench.py` in this blog's repository. It uses a fixed seed (20261102) and the Python standard library, and it calls gitleaks 8.30.1 and llama.cpp's `llama-tokenize`. It ran on an Apple M2 Pro. The detection counts are deterministic for the seed, and each write and scan was repeated three times, so the timings are medians of 3.

**The corpus.** 200 agent sessions written as JSONL, one record per line, the way most agent runtimes store transcripts: `tool_call`, `tool_result`, `assistant` and `sse_chunk` records. That came to 18,947 records and 4.44 MB. Most records are ordinary agent work: `git log`, `pytest` output, lockfile reads, Docker pulls, API responses with request ids, ETags and page tokens, and `curl -v` calls carrying idempotency keys. Ten secret types are generated fresh from the seed at run time in their real formats: AWS key id and secret key, GitHub PAT, Slack bot token, Stripe live key, OpenAI project key, Anthropic key, a service JWT, a database password and a PEM private key. None of them is real, and the repository only holds aggregate counts.

**Eleven leak shapes, 24 events each.** Each shape is a way we have seen a secret get into an agent transcript:

| Leak shape | What the agent did |
| --- | --- |
| env dump | ran `env` while debugging |
| .env / key file read | `fs.read` on `.env` or `deploy/tls.key` |
| bearer header | `curl -sv` with `authorization: Bearer ...` or `x-api-key` |
| Basic auth header | `curl -sv -u ...`; curl prints the header base64-encoded |
| traceback locals | `pytest -l` printing a `postgresql://` or `redis://` URL with the password in it |
| Kubernetes secret | `kubectl get secret -o yaml` (values are base64) |
| logged URL | an HTTP client's debug log of `?token=...`, percent-encoded |
| hexdump | `xxd .env` |
| model prose | the model repeats the key in its reply ("the current value is ...") |
| streamed reply | the same, but logged one `sse_chunk` record per token |
| repo file | the agent reads a source file with a hard-coded key the runtime does not know |

**Defences.** Three ways of writing the log: no redaction; exact-value redaction of every secret the runtime holds (its env and vault, plus six decoy secrets per session); and encoding-aware redaction (below). Two ways of scanning: gitleaks over the stored JSONL, and gitleaks over a *decoded view* in which each record's content is JSON-unescaped and each stream is reassembled into one message.

**Scoring.** A secret counts as handled when redaction leaves nothing recoverable or a scanner flags it. "Recoverable" is checked by an oracle that tries what an attacker with read access to the logs would try: the raw string, percent-decoding, base64 at every offset, hex, reversing an `xxd` dump, and reassembling stream deltas. Against the unredacted logs the oracle recovers all 264 secrets, so every miss below is a real leak.

## Results

![Heat-map matrix of the 11 leak shapes against 5 defences, with green for secrets handled and red for secrets leaked, out of 24 per cell. gitleaks with default rules on the stored JSONL scores 0 of 24 on traceback locals with a connection URL, the xxd hexdump and the streamed reply, and 140 of 264 (53%) overall. Exact-value redaction scores 0 on Basic auth headers, traceback connection URLs, Kubernetes secrets, hexdumps, streamed replies and the hard-coded repo file, 110 of 264 (42%). gitleaks with a tuned config on a decoded view reaches 197 (75%), encoding-aware redaction 216 (82%), and both together 238 (90%), with the hexdump row red in every column](/assets/img/posts/ai/agent-log-secrets-detection-matrix.webp){: width="1200" height="920" }

The same numbers as a table (secrets handled, out of 24 per shape):

| Leak shape | gitleaks, stored JSONL | gitleaks, tuned, decoded view | Exact-value redaction | Encoding-aware redaction | Encoding-aware + tuned scan |
| --- | ---: | ---: | ---: | ---: | ---: |
| env dump in shell output | 22 | 22 | 24 | 24 | 24 |
| .env or key file read by a tool | 22 | 22 | 24 | 24 | 24 |
| curl -v, bearer/API-key header | 24 | 24 | 24 | 24 | 24 |
| curl -v, Basic auth header (base64) | 8 | 8 | 0 | 24 | 24 |
| traceback locals with a connection URL | 0 | 24 | 0 | 24 | 24 |
| kubectl get secret -o yaml (base64) | 24 | 24 | 0 | 24 | 24 |
| token in a logged URL (percent-encoded) | 17 | 17 | 14 | 24 | 24 |
| xxd of a config file | 0 | 0 | 0 | 0 | 0 |
| model repeats the key in its reply | 12 | 12 | 24 | 24 | 24 |
| streamed reply, one log record per token | 0 | 22 | 0 | 24 | 24 |
| hard-coded key in a file the agent read * | 11 | 22 | 0 | 0 | 22 |
| **All 264** | **140 (53%)** | **197 (75%)** | **110 (42%)** | **216 (82%)** | **238 (90%)** |

\* The runtime does not know this key, so no redaction can remove it; only a scanner can find it.

The two kinds of defence fail in different places. Redaction knows *what* the secrets are but not *where* they turn up. A scanner can find a secret anywhere, but only if it matches a pattern. Each one covers rows the other misses, and you need both.

## Where the scanner misses

### Streamed replies: one secret, 26 log records

Agent runtimes often log a streamed reply the way it arrives: one record per server-sent event, one event per token. A secret in the reply is then spread across many records, and no single record holds enough of it to match a rule.

![One streamed agent reply split by the SmolLM3 3B tokenizer through llama.cpp llama-tokenize, with every token drawn as its own box; a fake GitHub token in the middle spans 26 of the reply's 50 tokens, and the longest token piece is 3 characters, so the stored records read gh, p, _m, h1 and so on and no single record matches a scanner rule. Below, a bar chart of the median number of tokens a secret is spread across: AWS access key id 13 tokens for 20 characters, database password 15 for 19, Stripe live key 21 for 32, AWS secret key and GitHub PAT 29 for 40, Slack bot token 30 for 55, Anthropic key 68 for 108, service JWT 108.5 for 160, and OpenAI project key 109 tokens for 164 characters](/assets/img/posts/ai/agent-log-secrets-stream-token-split.webp){: width="1400" height="750" }

The split comes from a real tokenizer: SmolLM3 3B's 128,256-entry BPE vocabulary, called through `llama-tokenize`. A random credential is the worst case for BPE. It has no common words, so it breaks into one- to three-character pieces. On the stored JSONL gitleaks flagged **0 of 24** streamed secrets. On the decoded view, with each stream joined back into one message, it flagged 22. The other 2 were database passwords. With their punctuation, the default rules caught only 2 of the 52 passwords in the whole corpus, both inside Kubernetes secrets.

### Encodings: gitleaks decodes base64, but not everything around it

gitleaks 8.30.1 decodes base64 by default (`--max-decode-depth` defaults to 5). That is why it caught all 24 Kubernetes secrets. On curl's Basic auth header it caught only 8 of 24, all of them GitHub tokens. The Stripe keys were missed because curl encodes `key:` with a trailing colon, and the Stripe rule only accepts a key that ends at whitespace, a quote, a backtick, a semicolon, a literal `\n` or the end of the line. The passwords were missed because nothing matches a password.

![Terminal capture of gitleaks 8.30.1 run with --redact -v on one agent session log, session-s0043.jsonl: it reports 2 leaks, a generic-api-key finding on line 42 that is an idempotency key and a github-pat on line 4 found inside a base64 Basic auth header (tag decoded:base64 decode-depth:1). Below, line 61 of the same file printed with jq: a pytest traceback whose local variable dsn holds a redis connection URL with a percent-encoded password, a planted leak that gitleaks did not report](/assets/img/posts/ai/agent-log-secrets-gitleaks-one-session.webp){: width="1400" height="775" }

This one session shows both failures. The real leak gitleaks reported was a decoded GitHub token, and the other "leak" was an idempotency key. The planted Redis password on line 61 went unreported. No default rule covers the `scheme://user:password@host` shape. Pytest's `-l` flag prints every local variable on a failure, so a connection string in a test turns into a password in the log.

Base64 is not a secret-hiding format. Anyone who can read the log can decode it in seconds, for example in our [Encode / Decode tool](https://tools.lamplitlabs.com/encode-decode), which decodes in the browser without sending the input anywhere:

![The Lamplit Labs Encode / Decode tool with the Base64 tab and Decode mode selected: the input box holds a base64 string copied from a logged curl Basic auth header, and the result box shows the decoded plaintext svc-deploy: followed by a fake 19-character database password from the benchmark corpus](/assets/img/posts/ai/agent-log-secrets-base64-decode-lamplit-tool.webp){: width="900" height="348" }

### Prose and escaped quotes: half of the model's own replies

When the model repeats a key in its reply, gitleaks flagged 12 of 24. Prefixed keys followed by a full stop, a closing bracket or a JSON-escaped quote are missed, because most prefixed-key rules end with the same terminator group, and that group does not accept `.`, `,`, `)` or `\"`. We checked this directly with a fake Stripe-format key: `key is <key> now` and `key <key>; x` are flagged, while `key is <key>.`, `key (<key>) ok` and `key <key>, x` are not. Unprefixed secrets in prose (AWS secret keys, passwords) have nothing for a rule to anchor on.

The same terminator rule explains the repo-file row. In the stored JSONL, the source line `os.environ.get("NAME", "<key>")` is serialised with `\"` after the key, so gitleaks found 11 of 24. In the decoded view the quote is a plain `"`, and it found 22.

### False positives: the scanner's noise is your idempotency keys

On the stored logs, 693 of the 849 gitleaks findings (82%) were `generic-api-key` hits on `idempotency-key:` headers, from 727 records that carry one. Decoding made the noise worse: on the decoded view, unescaped JSON exposed `next_page_token` (740 findings) and `cache_key` (738), for 2,171 false positives in total. A scanner that cries wolf two thousand times a day gets muted, and then the real findings are muted with it.

## Where redaction misses

Exact-value redaction is the first thing most runtimes add: collect the secrets the process holds and replace each one before a line is written. It removed 110 of 264. It fails on every shape that changes the bytes: base64 in Basic headers and Kubernetes secrets (0 of 24 each), percent-encoded passwords in traceback connection URLs (0 of 24), percent-encoding in logged URLs (14 of 24, the misses being secrets with `/`, `+` or punctuation), and streams, where no single record holds the whole value (0 of 24).

The fix is cheap: redact every encoding of every known value, not just the raw string. Base64 is the only tricky case, because the encoding of a value depends on its byte offset in the surrounding data. Encode it at all three alignments and keep only the stable middle characters:

```python
import base64, json
from urllib.parse import quote, quote_plus

def variants(v):
    """Encodings of v that a known-value redactor should also remove."""
    b = v.encode()
    out = {quote(v, safe=""), quote_plus(v), b.hex(), b.hex().upper(), json.dumps(v)[1:-1]}
    for enc in (base64.b64encode, base64.urlsafe_b64encode):
        for k in range(3):  # the value can start at any of 3 byte offsets
            e = enc(b"\0" * k + b).decode().rstrip("=")
            out.add(e[-(-8 * k // 6):(8 * (k + len(b))) // 6])
    out.discard(v)
    return out
```

For streams, redact before you split. Keep a holdback buffer as long as the longest needle minus one character, redact the buffer on every token, and only write out text that can no longer be the start of a match:

```python
hold = max(len(n) for n in needles) - 1
buf = ""
for piece in stream:
    buf = redact(buf + piece)
    if len(buf) > hold:
        write_delta(buf[:len(buf) - hold])
        buf = buf[len(buf) - hold:]
write_delta(redact(buf))
```

The holdback in this corpus had a median of 319 characters and a maximum of 327. It is the longest needle minus one, and the longest needle is the hex encoding of the longest key: a 164-character OpenAI project key is 328 hex characters. It delays the log, not the user: the client still gets tokens as they arrive. If you also redact the stream going to the client, that holdback becomes visible latency, so log the stream and redact it there instead.

Together these take redaction from 110 to 216 of 264. Writing the whole corpus took 0.23 s with no redaction, 0.31 s with exact-value redaction and 0.73 s with encoding-aware redaction (medians of 3). That is about 0.1 s per MB on one core of an M2 Pro, which is noise next to a model call.

What redaction can never do is remove a secret it was not told about. The 24 keys hard-coded in a repository file stayed at 0 of 24 under every redaction mode. Only a scanner finds those.

## The tuned scan

Two config changes and one preprocessing step took gitleaks from 140 to 197 on its own, and redaction plus the scan from 216 to 238:

1. **Scan a decoded view, not the stored JSONL.** One `jq` line JSON-unescapes every record and joins stream deltas back together:

   ```bash
   jq -rj 'if .type == "sse_chunk" then .delta elif .content then "\n" + .content + "\n" else empty end' \
     session-*.jsonl > decoded.txt
   gitleaks dir decoded.txt --redact -c agent-logs-gitleaks.toml
   ```

2. **Add a rule for passwords in connection URLs,** and **3. allowlist the identifiers your logs carry by design.** The config lives at `scripts/data/agent-logs-gitleaks.toml`:

   ```toml
   [extend]
   useDefault = true

   [[rules]]
   id = "connection-url-password"
   description = "Password in the userinfo part of a connection URL"
   regex = '''\b[a-z][a-z0-9+.-]{1,20}://[^\s:/@'"]*:([^\s@/'"]{8,})@[a-z0-9.-]+'''
   secretGroup = 1
   entropy = 3.0
   keywords = ["://"]

   [[allowlists]]
   description = "idempotency keys, cache keys and page tokens are identifiers, not credentials"
   regexTarget = "match"
   regexes = ['''(?i)(idempotency-key|cache_key|next_page_token)["\\]*[:=]''']
   ```

With that config, false positives on the decoded view dropped from 2,171 to 0, and the URL rule caught all 24 traceback passwords. Be honest about what that means: we wrote both changes after seeing this corpus's misses and noise, so these are in-sample results. The lesson is not "copy this file". It is "run the scanner on a week of your own agent logs, read what it flags, and tune it before you alert on it". Your identifiers will have different names, and your connection strings may have other shapes.

## What still leaks: hexdumps

`xxd .env` scored 0 of 24 under every defence, including the combination. A hexdump splits the value into 2-byte groups separated by spaces and wraps it across lines, so neither the redactor's hex variant nor any scanner rule matches. Our oracle reads it back trivially, and so would an attacker with `xxd -r`. Agents run `xxd`, `od` and `hexdump` when a config file "looks wrong", and on binary files. Either strip or truncate tool output that looks like a hexdump before it is logged, or normalise it back to bytes before redacting.

## A starting sequence

1. **Shrink what can leak.** Every shape here except the repo file starts with the runtime holding the secret. Give tools an environment with no credentials and a broker for the calls that need one, as in the [sandboxing post]({% post_url AI/2026-10-30-ai-security-sandboxing-agent-tool-calls %}). A secret the agent process never holds cannot end up in its log.
2. **Redact every encoding at write time,** with a holdback on streams, or log streamed replies as one reassembled message. In this benchmark that took coverage from 42% to 82% for 0.5 s per 4.4 MB.
3. **Scan a decoded view with a tuned config,** in CI on stored transcripts and on anything exported to your observability stack. It is the only defence that finds secrets the runtime never knew about.
4. **Drop or normalise hexdumps and other binary-looking tool output.** Nothing else in this test caught them.
5. **Treat the log store as a secret store** until all of the above is in place: short retention, narrow read access, and rotation whenever a scan finds something. The [egress post]({% post_url AI/2026-10-27-ai-security-llm-data-exfiltration-agent-tool-egress %}) covers the matching control on the way out: a log shipped to a third-party tool is egress too.

## Reproduce it

```bash
# gitleaks 8.30.1 on PATH; llama-tokenize is optional (without it streams split into 4-character chunks)
python3 scripts/agent_log_secret_leak_bench.py --work /tmp/agent-log-bench --model <any.gguf> --repeats 3
python3 scripts/gen_agent_log_secrets_post_images.py --work /tmp/agent-log-bench
```

The first command writes `scripts/data/agent-log-secret-leaks.json` (counts only, no secrets) and keeps the generated logs, gitleaks reports and capture files under `--work`. The second draws every chart in this post from those files. The gitleaks scan of the 4.4 MB corpus took between 1.1 s and 6.8 s across our runs, depending on what else the 12-core machine was doing. The JSON records 5.8 s, the median of 3 scans on a busy run, so treat the timings as an upper bound.

Token counts depend on the tokenizer, but any BPE vocabulary breaks a random credential into short pieces. To estimate how many tokens a string costs for GPT-4o, Claude, Gemini or Llama before you send it, use the [Token Counter]({% post_url AI/2026-10-12-token-counter-checking-prompt-size-and-context-window-fit %}).

## Where Pulse fits

Pulse, Lamplit Labs' multi-project self-improving automation product, is coming soon. It runs agents for long stretches without a person watching, and their transcripts are exactly the kind of log measured here. That is why we measure our own defences instead of trusting a scanner's defaults. If you are about to give agents longer leashes, measure what your logs keep before you widen access to them. The [Pulse introduction]({% post_url AI/2026-10-25-pulse-internal-rsi-tool %}) has more on what we are building.
