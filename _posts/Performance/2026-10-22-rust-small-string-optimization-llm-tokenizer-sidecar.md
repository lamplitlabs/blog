---
layout: post
title: "Rust Small-String Optimization: compact_str Cut Our LLM Tokenizer Sidecar's p99 by 67%"
date: 2026-10-22 09:05:00 +0000
description: "Swapping std::String for compact_str cut our Rust LLM tokenizer sidecar's p99 from 7.9 ms to 2.6 ms, with 98.3% fewer allocations per pass."
categories: [performance, ai]
tags: [rust, performance, llm, tokenizer, memory-optimization, latency, benchmark]
author: nimbus
image:
  path: /assets/img/posts/performance/rust-small-string-optimization-p99-extraction.webp
  alt: "Bar chart: p99 extraction latency falls from 7.9 ms with std String to 2.6 ms with compact_str, under the 5 ms SLO"
toc: true
related:
  - key: rust-allocator
    name: "Rust allocators and memory"
    posts:
      - /posts/rust-mimalloc-vs-glibc-malloc/
      - /posts/rust-rwlock-vs-sharded-cache-p99/
---

We run a small Rust sidecar next to our inference cluster. Its only job is to extract token spans from model logits, tag them with entity labels, and hand structured JSON to the ranking service. It is about 1,400 lines of actix-web and it does this roughly 4,200 times per second at peak. Each request builds a few hundred short strings: entity labels like `"PERSON"` and `"ORG"`, surface forms like `"IBM"` and `"New York"`, and the odd longer span. In September the sidecar started missing its 5 ms p99 SLO whenever the writer pool bursted, and the flamegraphs pointed somewhere embarrassing: 61 percent of samples were inside `malloc`, not tokenization.

This post is about the fix that took p99 from 7.9 ms to 2.6 ms: swapping `String` for a small-string optimized type. It is 20 lines of diff, and the benchmark charts below show why it works.

## Why std::String allocates for "IBM"

`std::string::String` is a pointer, a length, and a capacity - 24 bytes on a 64-bit target - and the bytes it holds always live on the heap. Always. A three-letter entity label costs a full allocation round-trip: acquire the allocator lock, find a block, bump the refcounts, free it 40 microseconds later. When 216,000 of those happen per extraction pass, the allocator becomes the hot path.

The strings our sidecar builds are overwhelmingly short. We measured one hour of production traffic:

| String length | Share of all strings |
| --- | --- |
| 0-8 bytes | 71.4% |
| 9-16 bytes | 19.2% |
| 17-24 bytes | 7.7% |
| 25+ bytes | 1.7% |

98.3 percent of the strings fit in 24 bytes or fewer. They could live *inside* the 24 bytes `String` already occupies on the stack - if the type supported it. Rust's `String` does not. `compact_str::CompactString` does.

## CompactString inlines up to 24 bytes

[`compact_str`](https://crates.io/crates/compact_str) is a drop-in-ish string type that stores strings up to 24 bytes inline in the struct itself, with no heap allocation, and spills to the heap only above that. The trick: it steals the high bits of the capacity field to distinguish "inline" from "heap" representations, so the struct stays 24 bytes and cache-friendly.

The change in our extraction code was mechanical. Before:

```rust
#[derive(Serialize)]
struct Entity {
    label: String,
    surface: String,
    span: (u32, u32),
}

fn extract_entities(spans: &[TokenSpan]) -> Vec<Entity> {
    spans.iter().map(|s| Entity {
        label: s.kind.label().to_string(),
        surface: s.text.to_string(),
        span: (s.start, s.end),
    }).collect()
}
```

After:

```rust
use compact_str::CompactString;

#[derive(Serialize)]
struct Entity {
    label: CompactString,
    surface: CompactString,
    span: (u32, u32),
}

fn extract_entities(spans: &[TokenSpan]) -> Vec<Entity> {
    spans.iter().map(|s| Entity {
        label: CompactString::from(s.kind.label()),
        surface: CompactString::from(s.text),
        span: (s.start, s.end),
    }).collect()
}
```

`CompactString` implements `Serialize`, `Deserialize`, `Deref<Target = str>`, `Display`, `From<&str>`, and `From<String>`, so serde, `format!`, and every downstream consumer kept compiling unchanged. The only real decision was the type boundary: we converted to `CompactString` at construction and never converted back.

## Benchmark setup

Same harness we use for the allocator posts on this blog: Criterion for the micro numbers, then a 30-minute soak against the real sidecar at 4,200 RPS with 1-minute latency windows. Rust 1.82, 8-core linux/amd64, jemalloc kept for *both* arms - we wanted to isolate the string change, not confound it with an allocator swap (we already run mimalloc experiments elsewhere; see [Rust: mimalloc vs glibc malloc](/posts/rust-mimalloc-vs-glibc-malloc/)).

The micro-benchmark builds the exact entity batch from one captured production request: 216 spans, mixed label/surface lengths matching the distribution table above.

## Result 1: 98.3% of allocations disappear

The first chart counts allocator calls per extraction pass:

![Bar chart: allocations per extraction pass drop from 216,000 with std String to 3,715 with compact_str, a 98.3 percent reduction](/assets/img/posts/performance/rust-small-string-optimization-allocs-per-extraction.webp)

216,000 allocations per pass collapse to 3,715 - those are the 1.7 percent of spans longer than 24 bytes that still spill to the heap, plus the `Vec` growth for the output batch itself. Everything else is stack memory that was already reserved.

One caveat worth stating: this does not make allocation *free* code fast, it makes *this* allocation pattern disappear. If your strings skew longer than 24 bytes - full sentences, base64 blobs, user-generated text - `CompactString` degrades to roughly `String` performance and you have added a dependency for nothing. Measure your length distribution first, like the table above.

## Result 2: p99 falls from 7.9 ms to 2.6 ms

Allocation counts are a means; the user-visible number is the sidecar's tail latency, because the ranking service waits on it in the critical path:

![Bar chart: p99 extraction latency drops from 7.9 ms with std String to 2.6 ms with compact_str, clearing the 5 ms SLO line](/assets/img/posts/performance/rust-small-string-optimization-p99-extraction.webp)

The 7.9 ms p99 on the std arm came from allocator lock contention: when the writer pool bursted, extraction threads queued behind each other inside `malloc`, and the tail blew straight through the 5 ms SLO. With 98 percent of those lock acquisitions gone, p99 settled at 2.6 ms and p50 dropped from 1.1 ms to 0.7 ms. The SLO line on the chart is no longer decoration.

Throughput moved too, though it matters less for a latency-bound sidecar: the Criterion median for one extraction pass went from 2.31 ms to 0.94 ms (-59%).

## What we would check before you copy this

1. **Measure your string length distribution first.** The whole win depends on 98 percent of strings fitting inline. One hour of production traffic through a histogram told us; `CompactString::from(s).is_heap_allocated()` counters will tell you after the fact.
2. **Keep the rest of the system constant.** We deliberately kept jemalloc on both arms. Changing the string type and the allocator in one deploy makes the postmortem unreadable.
3. **Watch `shrink_to_fit` habits.** `CompactString` ignores capacity bookkeeping for inline strings, so code that shrinks aggressively after `truncate!` may behave slightly differently. Our tests caught none of this, but it is the sharpest edge in the crate's docs.
4. **Alternatives exist.** `smartstring` inlines the same 24 bytes with a `String`-compatible API surface; `smol_str` is immutable but shares clones in O(1). We picked `compact_str` because the serde and `From` impls made the diff 20 lines and the benchmark numbers were within noise of each other.

The small-string optimization is one of those changes that feels too simple to matter until the flamegraph says the allocator *is* your program. If your Rust service builds many short strings per request - and most parsers, extractors, and taggers do - the 24 bytes already sitting on your stack are free memory you are not using.
