---
layout: post
title: "AI Security: ReDoS in LLM Guardrail Regexes, Measured in Python, Node, Go and Rust"
date: 2026-11-23 01:00:00 +0000
categories: ai
author: manishtiwari25
description: "Five LLM guardrail regexes in Python, Node, Go and Rust: one ordinary 37-byte line took 4.5 s in Python and failed 67% of a guard's traffic. Rust: 0.1 µs."
image:
  path: /assets/img/headers/ai/ai-security-guardrail-redos.webp
  alt: "Header card titled ReDoS in AI guardrails, measured: one ordinary line, five regex engines. The rule is (api[_-]?key|token|secret|password)\\s*[:=]\\s*\"([\\w-]+)+\" and the input is the 37-byte line password=\"build-agent-nightly-release. Log-scale bars of the time to check it: Python 3.13 re 4.5 s, Node 22 V8 Irregexp 710.3 ms, Node 22 with the linear fallback flag 686.7 ms, Go 1.27 regexp 3.2 µs, Rust regex 1.13 100 ns. The hardened rewrite of the rule is under 10 µs on every engine. Apple M2 Pro, median of 3 runs."
tags: [ai-security, guardrails, regex, redos, llm, rust, go, python, nodejs, benchmark]
---

Most LLM guardrails start as a list of regular expressions. One spots a chat-role spoof in retrieved text. One spots a credential in model output. One finds URLs to check against an egress allowlist, one catches markdown images that leak data through the query string, and one redacts e-mail addresses and card numbers before anything is logged. They are cheap, easy to read, and they run on every request, often before the model sees the text.

That makes them the first code in your stack to touch attacker-controlled input. A regex that backtracks badly is a denial-of-service (ReDoS) bug that anyone who can type into the chat box can trigger. You don't need an attacker, either: in this test, some ordinary lines nobody wrote to cause trouble were enough.

We wrote five guardrail rules the way they usually look, plus a hardened rewrite of each. We ran all ten through five regex engines and then put each engine behind a small HTTP guard service under steady load. Everything below was measured on one machine, and the harness is in the repository.

## TL;DR

- **Python 3.13 `re` needed 4.5 seconds for one ordinary 37-byte line.** The secret rule took 4,453 ms on `password="build-agent-nightly-release`. One more word (`-signing`) and Node ran into our 120-second kill switch. Python's role rule did the same on the 48-byte line `System: please summarise the attached quarterly.`
- **One such line every 5 seconds took a Python guard service down.** At 200 benign requests per second, 66.5% of them failed (reset or timed out after 5 s), and the p99 of the ones that got through was 4.9 s. Node's event loop kept serving but its p99 went from 2.1 ms to 845 ms.
- **Go `regexp` and Rust `regex` never blew up exponentially.** No search ran past 43 ms on up to 1.3 MB of input. The one exception was the naive redaction rule, whose find-and-replace loop is quadratic by design: 3.5 s on 64 KB of digits in Go and 1.4 s on 256 KB in Rust. On the 37-byte line Rust took about 0.1 µs and Go 3.2 µs, and neither guard service dropped a request.
- **V8's `--enable-experimental-regexp-engine-on-excessive-backtracks` flag did not save Node.** The linear engine refuses every case-insensitive rule and every rewrite with a wide `{m,n}` bound, which here is 7 of the 10 patterns.
- **The hardened rewrites fixed every engine** with the same positives matched: no nested quantifiers, bounded repeats, and character classes that cannot overlap. Rust's compiler turned two of them away with `CompiledTooBig` until `\w` was made ASCII-only.

## The five rules

All ten patterns are in [`scripts/guardrail-redos/rules.json`](https://github.com/lamplitlabs/blog/blob/main/scripts/guardrail-redos/rules.json), and every harness reads them from that file. The naive versions are the kind of thing you find in guardrail code, gists and LLM-written filters:

| Rule | What it looks for | Naive pattern | Hardened pattern |
|---|---|---|---|
| `role_override` | `system:` lines that try to change the rules | `(system\|assistant\|developer)\s*:\s*(\w+\s*)*(ignore\|override\|reveal)` | `(?:system\|assistant\|developer)[ \t]*:[^\n]{0,200}?(?:ignore\|override\|reveal)` |
| `secret_assign` | a quoted credential in model output | `(api[_-]?key\|token\|secret\|password)\s*[:=]\s*"([\w-]+)+"` | `(?:api[_-]?key\|token\|secret\|password)\s*[:=]\s*"[A-Za-z0-9_-]{8,256}"` |
| `exfil_url` | any URL, to check against an allowlist | `https?://([\w.-]+)+\.[a-z]{2,}` | `https?://[A-Za-z0-9.-]{1,253}\.[a-z]{2,24}` |
| `md_image` | a markdown image with a remote URL | `!\[.*\]\((https?://.*)\)` | `!\[[^\]\n]{0,256}\]\(\s*https?://[^)\s]{1,1000}\)` |
| `pii_redact` | e-mails and 16-digit card numbers, replaced with `#` | `[\w.+-]+@[\w-]+\.[\w.-]+\|\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}` | card first, then a bounded e-mail with dotted labels |

The first two rules are case-insensitive. The first four only test for a match, and `pii_redact` replaces every match. Each rule has three positive examples, and both versions of every rule matched all of them on every engine. We also ran every version over 3,455 real lines of question and answer text from the GSM8K and TruthfulQA datasets, and no rule matched any of them. So the rewrites are not faster because they match less.

The engines:

- **Python 3.13.5 `re`**: a backtracking engine.
- **Node 22.18 (V8 Irregexp)**: backtracking, compiled to machine code. It was measured twice, once with V8's linear-time fallback flag on.
- **Go 1.27.4 `regexp`**: RE2-style. It guarantees linear time per search.
- **Rust `regex` 1.13.1**: finite automata (a lazy DFA, with other engines behind it), also linear per search.

## How it was measured

[`measure.sh`](https://github.com/lamplitlabs/blog/blob/main/scripts/guardrail-redos/measure.sh) builds everything offline and runs four experiments, three times each, on an Apple M2 Pro (12 cores, macOS 27, load average 3 to 8 during the run):

1. **Attack ladder.** For each rule, a string of the shape that defeats it: `token="` followed by *n* `a`s, `system: ` followed by *n* `a`s and a `!`, *n* copies of `![a](`, *n* digits. *n* runs from 8 up to 262,144, and a rule stops climbing the first time one string takes more than 1 second.
2. **Natural ladder.** For each rule, an ordinary sentence grown one word at a time, with no padding and no strange characters. These are the lines that matter for "it only fires on attacks".
3. **Benign corpus.** All 3,455 real lines, timed per rule. This checks that the rewrites cost nothing on normal text.
4. **Guard service under load.** Each engine runs as an HTTP service that applies all five rules to the request body, the way a guardrail sidecar does. An open-loop Go client sends 200 benign lines per second for 30 seconds, plus the 37-byte line once every 5 seconds. Latency is measured from each request's *scheduled* send time, so a stalled server is charged for every request that queued behind it.

Every timing is the median of up to five calls, and the tables show the median of the three runs. A call that ran past 120 seconds was killed, using `SIGALRM` in Python and by terminating the worker thread in Node. Go and Rust never came close to that limit.

## Result 1: attack strings grow exponentially on backtracking engines

![Log-scale line chart of the time to run the naive secret_assign rule on token=" followed by n letter a, for n from 8 to 262,144. Python and both Node lines climb steeply and stop between 26 and 30 characters, when one string took more than a second. The Go and Rust lines stay flat and reach 262,144 characters: Go in about 29 ms, Rust in about 0.2 ms.](/assets/img/posts/ai/guardrail-redos-attack-growth.webp){: w="1500" h="860" }

`([\w-]+)+` is the textbook catastrophic pattern. Each run of letters can be split between the inner and outer `+` in exponentially many ways, and the engine tries them all before it gives up. Each extra `a` roughly quadruples the time on Python and Node. On the `exfil_url` rule a 34-byte string took 2.7 s in Python and a 38-byte one 3.5 s in Node. On `role_override` Python passed one second at 33 bytes.

Go and Rust compile the same pattern to an automaton, so there is nothing to backtrack. A string of 262,144 characters took Go 29 ms and Rust 0.2 ms. The naive pattern is just as harmless there as the hardened one.

## Result 2: ordinary lines are enough

![Table of the longest ordinary line each engine finished per rule and variant. For naive rules, Python reaches the 120 s kill on role_override at 48 bytes, takes 4.5 s on secret_assign at 37 bytes and 10.4 s on exfil_url at 60 bytes. Node takes 3.2 s on role_override at 48 bytes, gets killed on secret_assign at 45 bytes and takes 1.8 s on exfil_url at 60 bytes. Node with the fallback flag finishes exfil_url in 0.2 ms but not the other two. Every hardened rule and every Go and Rust cell finished in microseconds.](/assets/img/posts/ai/guardrail-redos-natural-lines.webp){: w="1500" h="950" }

This is the result that should change how you think about it. These lines were grown one word at a time from sentences anyone might send:

| Ordinary line (bytes) | Rule | Python | Node | Node + fallback | Go | Rust |
|---|---|---:|---:|---:|---:|---:|
| `System: please summarise the attached.` (38) | role_override | 673 ms | 12.7 ms | 12.1 ms | 4.3 µs | 0.2 µs |
| `System: please summarise the attached quarterly.` (48) | role_override | **killed at 120 s** | 3.2 s | 3.0 s | 5.5 µs | 0.1 µs |
| `password="build-agent-nightly-release` (37) | secret_assign | **4.5 s** | 710 ms | 687 ms | 3.2 µs | 0.1 µs |
| `password="build-agent-nightly-release-signing` (45) | secret_assign | not reached | **killed at 120 s** | **killed at 120 s** | 4.0 µs | 0.1 µs |
| `health check http://build-agent-internal-eu-west:8080/health` (60) | exfil_url | 10.4 s | 1.8 s | 0.2 ms | 0.8 µs | 0.1 µs |

No input here is crafted. A `system:` line that never says "ignore" makes the naive role rule try every way to split the words before it fails. An unterminated quoted value (the model stopped mid-string, or a log line was cut) does the same to the secret rule. Every word adds a factor of four to fifty. A guard that has run fine for months can hang on the first long, slightly odd line it meets.

The hardened rules finished every one of these lines in under 10 µs on every engine. The slowest was Go's hardened redaction rule on its longest line, at 23 µs.

## Result 3: one slow line takes down the whole guard service

![Two-column chart for the guard service under 200 benign requests per second plus one 37-byte line every 5 seconds. Left: share of benign requests that failed. Python naive 66.5%, Node naive 0.6%, Node with fallback naive 0.7%, every other cell 0%. Right: p99 latency of successful requests on a log scale. Python naive 4.9 s, Node naive 845 ms, Node fallback naive 774 ms, Python hardened 34.6 ms, Node hardened 2.1 ms, Go and Rust 6.8 to 12.6 ms for both variants.](/assets/img/posts/ai/guardrail-redos-load-test.webp){: w="1500" h="900" }

The benchmarks show the cost of one call. The load test shows how much of that cost reaches users. Over 3 × 30 seconds, each service received 18,000 benign requests and 18 copies of the 37-byte line:

| Guard service | Rules | Benign requests failed | p50 (ok) | p99 (ok) |
|---|---|---:|---:|---:|
| Python 3.13, `ThreadingHTTPServer` | naive | **66.5%** (11,287 reset, 690 timed out) | 0.6 ms | 4.9 s |
| Python 3.13, `ThreadingHTTPServer` | hardened | 0% | 0.8 ms | 34.6 ms |
| Node 22, `http` | naive | 0.6% (108 reset) | 0.3 ms | 845 ms |
| Node 22 + fallback flag | naive | 0.7% (126 reset) | 0.3 ms | 774 ms |
| Node 22, `http` | hardened | 0% | 0.2 ms | 2.1 ms |
| Go 1.27, `net/http` | naive / hardened | 0% / 0% | 0.3 ms | 12.6 / 6.8 ms |
| Rust, std threads | naive / hardened | 0% / 0% | 0.2 / 0.3 ms | 10.6 / 11.2 ms |

Python is worst because CPython's `re` holds the GIL while it backtracks. One request thread stuck on a 4.5-second match freezes every other thread. Meanwhile the client opens new connections and fills the listen backlog (capped at 128 by macOS `kern.ipc.somaxconn`), and the kernel starts resetting connections. Two thirds of the traffic failed even though only 0.1% of requests were bad. Node has a single event loop, so it freezes too, but its match takes 700 ms instead of 4.5 s. The backlog mostly absorbed that, and Node lost "only" 0.6% while every request that queued behind a match paid for it in latency.

The same 37-byte request sent once with `curl`, after the load test, to the Python, Node and Rust guards:

![Terminal running curl with the same 37-byte body against six guard services. Python with naive rules answered flagged empty after 6713 ms, total 6.71 s. Python hardened answered in 0.001 s. Node naive took 1236 ms, 1.24 s total. Node hardened answered in 0.002 s. Rust naive and Rust hardened both answered in under 0.002 s, with guard times of 0.10 and 0.42 ms.](/assets/img/posts/ai/guardrail-redos-curl-poison.webp){: w="1500" h="416" }

Note `"flagged": []`. After 6.7 seconds the naive rule did not even flag the line. A ReDoS costs you availability and buys no detection in return.

## Result 4: V8's fallback flag cannot run most guardrail rules

Since V8 8.8, Node has had a non-backtracking engine. With `--enable-experimental-regexp-engine-on-excessive-backtracks`, V8 is supposed to switch a regex to that engine once it passes 50,000 backtracks. In our runs it helped exactly one rule: naive `exfil_url` went from 1.8 s to 0.2 ms on the 60-byte line. The flag made no difference to the others, so we asked V8 directly which patterns its linear engine accepts:

```text
$ node --enable-experimental-regexp-engine v8_linear_probe.mjs rules.json
role_override  naive     flags=i   refused: Cannot be executed in linear time
role_override  hardened  flags=i   refused: Cannot be executed in linear time
secret_assign  naive     flags=i   refused: Cannot be executed in linear time
secret_assign  hardened  flags=i   refused: Cannot be executed in linear time
exfil_url      naive     flags=-   linear ok
exfil_url      hardened  flags=-   refused: Cannot be executed in linear time
md_image       naive     flags=-   linear ok
md_image       hardened  flags=-   refused: Cannot be executed in linear time
pii_redact     naive     flags=g   linear ok
pii_redact     hardened  flags=g   refused: Cannot be executed in linear time
```

In Node 22, the linear engine refuses the `i` flag and any bounded repeat with a large range (`{2,24}` and `{8,256}` are refused, while `{1,4}` and `{0,16}` are accepted). Guardrail rules are full of both. Naive `md_image` and `pii_redact` were accepted, yet they still took 12 s and 2.7 s on the long attack strings. The fallback only kicks in on backtracking, and their cost is polynomial rescanning, which involves little backtracking. The flag is worth knowing about, but it does not replace fixing the patterns.

## Result 5: linear per search is not linear per `replace_all`

Naive `pii_redact` was the only rule that grew faster than the input on Go and Rust. Rust took 0.5 ms at 4 KB, 88 ms at 64 KB and 1.4 s at 256 KB of digits, and Go took 3.5 s at 64 KB. The `regex` crate documents this. The linear-time bound holds for each search, and an iterator such as `replace_all` can run O(n) searches. On a string of digits, the e-mail branch `[\w.+-]+@` scans to the end, finds no `@`, and the iterator moves on one character and scans again. Go's `ReplaceAllString` has the same shape. The hardened version checks the card number first and caps the local part at 64 characters, which brings the same 256 KB down to 0.7 ms in Rust and 69 ms in Go.

Python's and Node's naive `md_image` show the same quadratic pattern: 1.5 s and 0.8 s for 80 KB of `![a](`. The fix was the same, too: bounded, non-overlapping classes such as `[^\]\n]{0,256}` instead of `.*`.

The other Rust lesson came at compile time:

![Terminal output of guardbench compile rules.json, one line per pattern. All ten naive and hardened rules compile in 0.06 to 6.1 ms. Two extra probes fail with Compiled regex exceeds size limit of 10485760 bytes: secret_assign hardened written with Unicode \w and {8,256}, and exfil_url hardened with Unicode \w and {1,253}. The ASCII (?-u:\w) version of secret_assign compiles in 0.41 ms.](/assets/img/posts/ai/guardrail-redos-rust-compile.webp){: w="1500" h="464" }

The obvious hardening, `[\w-]{8,256}`, compiles fine in Python, Node and Go. In Rust it fails with `CompiledTooBig`, because `\w` is Unicode-aware by default (thousands of code point ranges), and a repeat of 256 copies them 256 times past the default 10 MiB limit. You can raise `RegexBuilder::size_limit`, but the better fix is to say what you mean. Credentials and hostnames are ASCII, so write `[A-Za-z0-9_-]` or `(?-u:\w)`, and the pattern compiles in 0.4 ms. It is a startup failure, not a production incident, but it can surprise you when you port a rule set from another language.

## What the hardening costs on normal text

Nothing measurable. Running all five rules over the 3,455 real lines (754 KB) took, naive vs hardened:

| Engine | Naive, 5 rules | Hardened, 5 rules |
|---|---:|---:|
| Rust `regex` | 1.8 ms | 1.8 ms |
| Node 22 | 11.1 ms | 11.5 ms |
| Python 3.13 `re` | 78.5 ms | 61.6 ms |
| Go `regexp` | 114 ms | 147 ms |

Go's `pii_redact` is the one cell that got slower (29 ms to 59 ms), because Go runs bounded repeats like `{1,64}` as an unrolled NFA. That is 17 µs per line, it is still linear, and it is the price of the 50x improvement on the 64 KB digit string (3.5 s to 18 ms).

## How to fix your guardrail regexes

1. **Run guardrails on a linear-time engine.** Use Rust `regex`, Go `regexp`, or RE2 or [Hyperscan](https://github.com/intel/hyperscan) through a binding. In Python, [`google-re2`](https://pypi.org/project/google-re2/) is close to a drop-in replacement for the simple patterns guardrails use. In Node, [`re2`](https://www.npmjs.com/package/re2) wraps the C++ library. A linear engine makes a bad pattern merely slow instead of fatal. In Rust and Go, a mistake like the naive `secret_assign` costs microseconds.
2. **If you must stay on a backtracking engine, rewrite the patterns.** Never put a quantifier inside a quantified group (`(\w+\s*)*`, `([\w-]+)+`). Make adjacent classes unable to match the same character. Replace `.*` with a bounded, negated class (`[^\]\n]{0,256}`). Bound every repeat to the longest real value.
3. **Cap the input before the regex sees it.** No guardrail needs 256 KB in one line. A length cap turns quadratic cases into bounded ones on any engine, and it is the only protection against `replace_all`-style rescans that linear engines still have.
4. **Never run a guardrail on the request thread without a deadline.** In Python that means a separate process or a timeout around a worker. A thread is not enough, because the GIL stops the watchdog from running. In Node, use a worker thread you can terminate, which is what our harness does. A guard that times out should fail closed for that request and return quickly, not hang.
5. **Fuzz your own patterns with ordinary text, not only attack strings.** Our ladder, real sentences grown one word at a time, found every bad rule within five words. Tools like [`recheck`](https://makenowjust-labs.github.io/recheck/) find attack strings statically.
6. **Test the port, not only the pattern.** A rule set that compiles in Python can fail to build in Rust (`CompiledTooBig`) or be refused by V8's linear engine. Run the compile step in CI on the engine you ship.

This is one more layer in the defense-in-depth approach from the [prompt injection defenses post]({% post_url AI/2026-10-29-ai-security-prompt-injection-defenses-agents %}). Guardrail regexes are a cheap first filter, but they are code that faces the attacker and needs the same review as any parser. The markdown-image and URL rules exist because of the exfiltration channels in the [egress post]({% post_url AI/2026-10-27-ai-security-llm-data-exfiltration-agent-tool-egress %}). The secret rule is the kind of redaction the [secrets in agent logs post]({% post_url AI/2026-11-02-ai-security-secrets-in-agent-logs-measured %}) measured for catch rate. This post measured what it costs when it goes wrong.

## Reproduce it

```bash
# Needs: cargo (regex 1.13.1 and serde_json 1.0.154 in the local cache), go, node,
# CPython 3.11+ with pyarrow, GSM8K and TruthfulQA parquet files in the HF cache.
bash scripts/guardrail-redos/measure.sh /tmp/redos 3      # ~37 minutes on an M2 Pro
python3 scripts/guardrail-redos/summarise.py /tmp/redos   # -> scripts/data/guardrail-redos-m2pro.json
python3 scripts/guardrail-redos/gen_images.py             # the images in this post
```

The numbers above come from [`scripts/data/guardrail-redos-m2pro.json`](https://github.com/lamplitlabs/blog/blob/main/scripts/data/guardrail-redos-m2pro.json), which keeps every run (not just the medians) and the raw terminal output behind the screenshots. The other engine comparison on this blog, for throughput rather than worst cases, is the [regex engine performance post]({% post_url Performance/2026-10-03-regex-engine-performance-rust-go-dotnet-node %}).

## Where Pulse fits

Pulse, Lamplit Labs' multi-project self-improving automation product, is coming soon. Its agents read untrusted text all day: issue threads, CI logs, web pages, model output. Each of those passes through filters like the ones measured here before anything acts on it. That is why we put our own guardrails through ReDoS tests and run them on a linear-time engine rather than trust that a pattern looks harmless. The [Pulse introduction]({% post_url AI/2026-10-25-pulse-internal-rsi-tool %}) has more on what we are building.
