---
layout: post
title: "Go sync.Pool and String Interning: Beating GC Pressure in the Same Tokenizer Sidecar"
date: 2026-10-22 09:30:00 +0000
description: The Go twin of our Rust tokenizer-sidecar benchmark - sync.Pool plus string interning cut allocations per extraction by 94% and flattened GC sawtooth.
categories: languages go
tags: [golang, go, sync-pool, memory-optimization, performance, gc-tuning, benchmark, llm, ai-infrastructure]
image:
  path: /assets/img/posts/languages/go-sync-pool-string-interning-p99-extraction.webp
  alt: Line chart of Go tokenizer-sidecar p99 extraction latency versus request rate for pooled-interned and allocating builds, showing the allocating build jumping from 20.9 ms to 110.4 ms across a GC while the pooled build climbs only to 36.1 ms
---

The Rust side of this story shipped earlier today: [our tokenizer sidecar spent 41% of its CPU in the allocator](/posts/rust-small-string-optimization-llm-tokenizer-sidecar/), and one `compact_str` import cut p99 extraction latency from 38 ms to 8.7 ms. The obvious follow-up question came from the team that owns the *other* tokenizer sidecar - the Go one that fronts the BPE tagger for the document pipeline. Same workload shape, same NUMA box, same Grafana dashboard. Different runtime, different knob.

Go does not give you a small-string optimization; `string` headers are already 16 bytes of pointer-plus-length, and the bytes always live on the heap. What Go *does* give you is control over how often you ask the allocator and the garbage collector for help. This post is that experiment: `sync.Pool` for the per-request scratch buffers, plus a tiny two-level string interner for the vocabulary hits, on the exact workload the Rust post used.

## The workload, unchanged

Same service contract as the Rust benchmark so the numbers are comparable: an HTTP sidecar that receives a document chunk (1-8 KiB), runs wordpiece tokenization against a 32 000-entry vocabulary, and returns `(offset, length, token_id)` triples as JSON. The allocation-heavy part is identical too: every extracted mention builds a surface-form `string`, a normalized lowercase `string`, and a `[]byte` staging buffer before serialization.

Per 1 000-token chunk, the naive Go handler allocates:

- ~1 400 small strings (surface + normalized forms)
- ~700 `[]byte` staging buffers, 128-2 048 bytes each
- one 32 KiB scratch buffer for the sliding window

That is ~2 100 allocations per request, almost all of them dead within 200 microseconds - exactly the shape that makes Go's GC earn its keep, and exactly the shape that makes it show up in your p99 instead of your p50.

## The two changes

**1. `sync.Pool` for the buffers.** The scratch buffer and the staging slices move into a pool keyed by capacity class:

```go
var scratchPool = sync.Pool{
    New: func() any { b := make([]byte, 32<<10); return &b },
}

var stagePool = sync.Pool{
    New: func() any { b := make([]byte, 0, 2048); return &b },
}

func (h *handler) extract(chunk []byte) []mention {
    sp := scratchPool.Get().(*[]byte)
    defer scratchPool.Put(sp)
    scratch := (*sp)[:32<<10]
    // ... tokenize into scratch, never allocate a new window
}
```

The gotcha we hit in staging and is worth repeating: **reset before you Put, not after you Get.** A `Get` that returns a slice with the previous request's tail still in it is a correctness bug that only fires under load, when pools actually get reused. We Put `buf[:0]` and keep capacity; the linter we added (`go vet` plus a 12-line `ruleguard` rule) now fails the build on a bare `pool.Put(buf)`.

**2. A two-level interner for vocabulary hits.** 92% of surface forms are already in the vocabulary, so we were allocating a brand-new Go string for the ten-thousandth occurrence of `" transformer"`. The interner is a `map[string]string` keyed by the byte content, fronted by a small per-P cache so the hot path takes no lock:

```go
type interner struct {
    mu   sync.RWMutex
    dict map[string]string
}

func (in *interner) Intern(b []byte) string {
    // zero-alloc map lookup: Go special-cases string(b) in map reads
    in.mu.RLock()
    s, ok := in.dict[string(b)]
    in.mu.RUnlock()
    if ok {
        return s // same header, same backing bytes, zero new allocations
    }
    // cold path: build once, store, return the canonical copy
    ...
}
```

The `map[string]string` self-keying is doing the interning: the key *is* the canonical string, so a hit returns the existing header and backing array. The `string(b)` conversion in a map index expression is the one place the compiler elides the copy ([golang/go#2205](https://github.com/golang/go/issues/2205)), which is what makes the read path allocation-free. Every cached surface form is now one heap object for the process lifetime instead of one per occurrence.

## What moved

Same harness as the Rust post: 60-second windows at fixed concurrency on one NUMA node, p99 of the full extract call, plus a `pprof` alloc-space profile. Go 1.23, `GOGC=100` (the default) for both builds.

![Line chart of p99 extraction latency versus request rate for both Go builds](/assets/img/posts/languages/go-sync-pool-string-interning-p99-extraction.webp)

The shape is the tell. The allocating build (amber) is *fine* at low rate - 20.9 ms p99 at 50 req/s - and then the GC cycle starts landing inside requests: 55.2 ms at 1 000 req/s, 110.4 ms at 5 000 req/s, with the two sawtooth steps being back-to-back GC cycles on the same window. The pooled-and-interned build (teal) starts at 19.8 ms and climbs smoothly to 36.1 ms, no sawtooth, because the GC simply has less work: a mark phase that scans half the heap garbage takes half the time.

![Bar chart of allocations per extraction for both Go builds](/assets/img/posts/languages/go-sync-pool-string-interning-allocs-per-extraction.webp)

The mechanism in one chart: 2 138 allocations per extraction drop to 124 (-94%), and the 137 KB of per-request heap drops to 9 KB. The surviving 124 are the strings that are genuinely new - OOV surface forms and the response body - which is the same "pay only for what is actually novel" point the Rust post landed on.

## The honest Go-vs-Rust comparison

Putting the two fixes on the same dashboard is where it gets interesting for readers picking a language for this class of service:

| Metric (5 000 req/s window) | Rust + compact_str | Go + pool/intern |
| --- | --- | --- |
| p99 extraction | 8.7 ms | 36.1 ms |
| Allocations / extraction | 12 | 124 |
| Heap churn / request | 31 KB -> 2 KB | 137 KB -> 9 KB |

Rust still wins the tail by ~4x on this workload, and the reason is structural, not a benchmark trick: the Go runtime cannot know that a `[]byte` escaping into a pooled struct is dead next request, so some garbage is irreducible, and GC pause time scales with what remains. But the delta that matters operationally is the *slope*: both fixed builds degrade linearly with load instead of step-functioning at GC pressure, which means both can be capacity-planned, which is the actual production requirement.

If you are already in Go and cannot rewrite, the two changes above are a day of work and one `ruleguard` rule. If you are choosing fresh for a tokenizer-hot sidecar, the Rust result from this morning is the stronger default - and now both posts link here so you can compare the dashboards yourself.

## Related

- [Rust Small String Optimization: How compact_str Cut Our LLM Tokenizer p99 by 77%](/posts/rust-small-string-optimization-llm-tokenizer-sidecar/) - the same workload on the Rust sidecar, where the allocator was 41% of CPU.
- [Go sync.Pool vs Allocation: Benchmarking Memory Reuse in High-Throughput Services](/posts/go-sync-pool-vs-allocation-benchmark/) - the generic scratch-buffer benchmark that motivated trying a pool here first.
- [Go Context Cancellation: Wiring Deadlines Through LLM Streaming Agents](/posts/go-context-cancellation-llm-streaming-agents/) - the caller side of this sidecar, where canceled streams were holding our pooled buffers.
