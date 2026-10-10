---
layout: post
title: "Regex Engine Performance: Rust regex vs Go regexp vs .NET 8 Regex vs Node 22, Measured with hyperfine"
date: 2026-10-15 00:00:00 +0200
categories: performance rust
tags: rust go dotnet nodejs regex performance benchmark hyperfine
author: manishtiwari25
description: "Scanning a 1 GB log for five patterns: Rust regex 1,480 MB/s, .NET 8 Regex 612-705 MB/s, Node 22 438 MB/s, Go regexp 96 MB/s - and why the gap exists."
image:
  path: /assets/img/headers/performance/regex-engines-rust-go-dotnet-node.webp
  alt: "Bar chart of regex scan throughput in MB/s on a 1 GB log: Rust regex 1,480, .NET 8 NonBacktracking 705, .NET 8 Compiled 612, Node 22 Irregexp 438, Go regexp 96"
  lqip: "data:image/webp;base64,UklGRlYAAABXRUJQVlA4IEoAAACQAwCdASoUAAsAPzmGuVOvKSWisAgB4CcJQBUehDvbb7wfqxgAAP7MAbu2FBRNeATzjnUM7UC6ZhGEWYVYhZdGdQaF6ZSU0eAAAA=="
---

The [Python vs Rust hot-loop post]({% post_url Performance/2026-10-07-python-vs-rust-hot-loop-performance %}) measured raw arithmetic. This one measures something most backend services actually do every day and rarely benchmark: running regular expressions over a lot of text. Log scanners, WAF rules, routing tables, PII redaction and "grep in a loop" jobs all come down to the same question - how fast does the language's standard regex engine chew through bytes?

Four engines, one workload. A 1 GB nginx access log (4.9 million lines), five patterns applied to every line, count the matches. The patterns are the kind you find in a real alerting rule:

```text
1. \b5\d\d\b                                   # 5xx status codes
2. "(GET|POST|PUT|DELETE) /api/v[0-9]+/[a-z]+   # API method + versioned path
3. (\d{1,3}\.){3}\d{1,3}                        # IPv4 address
4. Mozilla/5\.0 \((Windows|Macintosh|Linux)     # user-agent OS family
5. [a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-z]{2,}  # email address in query string
```

![Bar chart of regex scan throughput in MB/s for Rust, .NET 8, Node 22 and Go](/assets/img/headers/performance/regex-engines-rust-go-dotnet-node.webp){: width="1200" height="630" }

## The four programs

Every program reads the file once with a buffered reader, splits on `\n`, runs the five compiled patterns on each line and sums a counter. The patterns are compiled exactly once, outside the loop; compiling inside the loop is the most common regex mistake and would turn this into a benchmark of the compiler, not the matcher.

**Rust 1.81, `regex` 1.10.**

```rust
let res: Vec<Regex> = PATTERNS.iter().map(|p| Regex::new(p).unwrap()).collect();
for line in reader.lines() {
    let line = line?;
    for re in &res { if re.is_match(&line) { hits += 1; } }
}
```

**Go 1.23, `regexp` from the standard library.** Same shape, `re.MatchString(line)`.

**.NET 8, `System.Text.RegularExpressions`.** Two variants: `RegexOptions.Compiled`, which emits IL for a backtracking matcher, and `RegexOptions.NonBacktracking`, the automata-based engine added in .NET 7. `Regex.IsMatch(line)` on a `ReadOnlySpan<char>`.

**Node 22, V8 Irregexp.** `re.test(line)` over `readline` chunks. The `u` flag is off; the patterns are ASCII.

## Results

`hyperfine -w 2 -r 5`, Apple M2 Pro, single thread, file already in page cache so disk is not in the picture. Throughput is 1,024 MB divided by the mean wall time.

| Engine | Wall time | MB/s | Relative |
|---|---:|---:|---:|
| Rust `regex` 1.10 | 725 ms | 1,480 | 1.00x |
| .NET 8 `NonBacktracking` | 1.52 s | 705 | 2.10x slower |
| .NET 8 `Compiled` | 1.75 s | 612 | 2.42x slower |
| Node 22 Irregexp | 2.45 s | 438 | 3.38x slower |
| Go 1.23 `regexp` | 11.18 s | 96 | 15.4x slower |

![hyperfine output for the Rust, .NET 8, Node 22 and Go regex scanners showing 725 ms, 1.754 s, 2.451 s and 11.183 s mean wall time](/assets/img/posts/performance/regex-engines-hyperfine-output.webp){: width="1000" height="560" }

## Why the spread is 15x

**Rust's `regex` crate wins on literal prefiltering.** Before it runs any automaton it looks for required literals in the pattern (`Mozilla/5.0`, `/api/v`, `@`) and uses a vectorised `memchr`/Teddy search to skip to candidate positions. Most lines in an access log fail that prefilter in a few nanoseconds and the regex engine proper never runs. Patterns 1 and 3 have no literal, so they are where Rust spends almost all of its 725 ms; the lazy DFA handles those at roughly 1.5 GB/s.

**.NET 8 is in the same family of techniques, one step behind.** Since .NET 7 the backtracking engine also finds leading literals and uses `IndexOf`/`SearchValues` (vectorised) to jump to them, which is why `Compiled` lands at 612 MB/s rather than the 150-200 MB/s .NET 5 would have given you. `NonBacktracking` is faster here because patterns 2 and 4 have alternations that the backtracker has to try in order; the DFA tries them at once. The trade-off is that `NonBacktracking` does not support backreferences or lookarounds, and its compile time is 3-10x higher, so it is a per-pattern choice, not a global switch.

**Node is competitive for a backtracker.** Irregexp JIT-compiles each pattern to machine code and does Boyer-Moore-style skipping on literal prefixes. What it lacks is the vectorised multi-literal search; pattern 5 (email, no good literal anchor) is the one that costs Node most of its gap to .NET.

**Go's `regexp` guarantees linear time and pays for it on every byte.** The standard library engine is RE2-derived: no backtracking, no catastrophic inputs, but also no literal prefilter beyond a single leading literal prefix, and its NFA/one-pass simulation is interpreted rather than compiled. 96 MB/s is in line with Go's own documentation, which says the package is "not optimised for speed" and points to third-party engines. Swapping in `github.com/grafana/regexp` (a fork with literal prefiltering) brought the Go number to 4.2 s / 255 MB/s with no code changes; `github.com/wasilibs/go-re2` (RE2 compiled to Wasm) got to 1.9 s but adds a Wasm runtime to the binary.

## The thing that matters more than the engine

Rerunning the Rust and .NET programs with the patterns compiled **inside** the loop produced 41 s and 118 s respectively - 55x and 67x slower than the numbers in the table. No engine choice recovers from that. If you take one line from this post: hoist the compile, cache the `Regex` object (`[GeneratedRegex]` in .NET does this at build time), and only then worry about which runtime you are on.

The second-largest lever was the five-patterns-per-line structure itself. Combining the five patterns into one alternation `(?:p1)|(?:p2)|...` and matching once per line cut Rust to 410 ms and .NET `NonBacktracking` to 0.98 s, because the prefilter and DFA only walk each line once. Go got slower (13.4 s): a bigger NFA with no prefilter means more states to simulate per byte.

## When to care

- A **log pipeline or WAF** that runs hundreds of rules over every request should be on Rust `regex`, .NET `NonBacktracking`, or RE2/Hyperscan via a binding. Go's standard `regexp` will become the bottleneck and the fix is a library swap, not a rewrite.
- A **web handler running two or three regexes on a short string** will not notice any of this; a 100-byte string is sub-microsecond on every engine here. Spend the effort on the database query instead, as the [EF Core post]({% post_url Performance/2026-10-05-ef-core-query-performance-dotnet %}) shows.
- **Untrusted patterns** (user-supplied search, tenant-configured rules) change the question from throughput to worst case. Go and .NET `NonBacktracking` cannot go exponential; Rust `regex` cannot either; Node and .NET `Compiled` can, and need a `matchTimeout` or input length cap.

## Related

- [Python vs Rust Hot-Loop Performance]({% post_url Performance/2026-10-07-python-vs-rust-hot-loop-performance %}) - the same Rust toolchain on pure arithmetic instead of text scanning.
- [Node.js 22 vs Deno 2 vs Bun 1.1 HTTP Performance]({% post_url Performance/2026-10-04-node-vs-deno-vs-bun-http-performance %}) - how the V8 runtime measured here compares on request handling.
- [Go Goroutines vs .NET Tasks]({% post_url Performance/2026-10-11-go-vs-dotnet-goroutines-vs-tasks-concurrency-throughput %}) - Go and .NET head-to-head on a workload Go does win.
