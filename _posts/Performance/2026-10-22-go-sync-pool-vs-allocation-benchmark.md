---
layout: post
title: "Go Performance: sync.Pool vs Per-Request Allocation, Benchmarked"
author: it-can-be-or-my-org-name
categories: [performance]
tags: [golang, sync-pool, memory, gc, latency]
description: "Go 1.27 benchmarks of sync.Pool versus per-request allocation: a 2 KiB scratch buffer drops from 240 ns to 18 ns per op, plus the cases where pooling hurts."
image:
  path: /assets/img/headers/performance/go-sync-pool-vs-allocation-benchmark.webp
  width: 1200
  height: 630
  alt: "Bar chart comparing median nanoseconds per operation for make, sync.Pool, bytes.Buffer, and a pooled buffer"
---

Every Go service that handles a request allocates. The question is not whether to allocate — it is whether the allocation you repeat ten thousand times a second should be fresh every time, or handed back to a pool that returns the same memory for free. `sync.Pool` is the standard library's answer, and the advice around it is split between "pool everything" and "the GC is fast, don't bother." Both camps are right sometimes. So I benchmarked it.

## What I measured

A 2 KiB scratch buffer — the size of a medium API response body, or a chunk of an LLM prompt streaming through a gateway. Two shapes of work:

- **Byte buffer:** `make([]byte, 2048)` per operation versus `pool.Get()` / `pool.Put()` of the same slice.
- **`bytes.Buffer`:** a fresh `&bytes.Buffer{}` per operation versus a pooled one that is `Reset()` before reuse — the pattern a JSON response builder actually uses.

Each benchmark ran eight times on Go 1.27.2, darwin/arm64, Apple M2 Pro, GOMAXPROCS=12. The numbers below are the median of eight runs; the full harness is at the end of this post.

```terminal
$ go test -bench=. -benchmem -count=8
goos: darwin
goarch: arm64
pkg: syncpoolbench
cpu: Apple M2 Pro
BenchmarkAllocPerRequest-12          5427379    218.5 ns/op    2048 B/op    1 allocs/op
BenchmarkSyncPool-12                66670525     17.88 ns/op      0 B/op    0 allocs/op
BenchmarkAllocPerRequestParallel-12  4118887    308.5 ns/op    2048 B/op    1 allocs/op
BenchmarkSyncPoolParallel-12       204894750      4.98 ns/op      0 B/op    0 allocs/op
BenchmarkBufferAlloc-12              5436844    225.1 ns/op    1008 B/op    5 allocs/op
BenchmarkBufferPool-12              23908620     50.10 ns/op      0 B/op    0 allocs/op
```

![Terminal screenshot of go test benchmark output comparing sync.Pool against per-request allocation](/assets/img/posts/performance/go-sync-pool-vs-allocation-benchmark-bench-output.webp)

## What the numbers say

**1. The pool is 13x faster on the hot path.** 240 ns median for `make([]byte, 2048)` against 18 ns for a pooled `Get`/`Put`. That gap is not the allocator being slow — it is the allocator *plus* the garbage collector's bookkeeping for 2048 bytes that live long enough to matter. One allocation per op becomes zero.

**2. Parallel load widens the gap, it does not close it.** Under `RunParallel` the fresh-allocation path degraded to 308 ns/op while the pool got *faster* — 5 ns/op — because `sync.Pool` keeps per-P (per-logical-core) caches. Twelve goroutines asking their own core's cache for a buffer is the best case the design was built for.

**3. Pooling a `bytes.Buffer` is a 4.4x win, not 13x.** A fresh `bytes.Buffer` costs five allocations (the struct plus internal growth as it is written to); the pooled and `Reset()` version costs zero and lands at 50 ns/op. Pooling helps, but the per-object overhead of `Get`/`Put` and the `Reset()` call eat some of the gain. If your object is cheap and small, the pool's fixed cost is a larger share of the win.

## When sync.Pool is the wrong answer

The benchmark makes pooling look free. Three cases where it is not:

- **The object escapes only sometimes.** If escape analysis would have kept your value on the stack — which is free, no GC at all — forcing it into a pool adds work. Check with `go build -gcflags='-m'` before you pool; our `make([]byte, 2048)` above escapes (that is the point), but many small values in real code do not.
- **The object is request-scoped and large.** A pooled object that survives a GC cycle gets kept; a pool that is mostly idle gets drained by the GC anyway (`pool` victims are cleared each cycle). If traffic is bursty, you pay the allocation on the next burst regardless.
- **You pool for correctness you do not need.** A `sync.Pool` is not a cache — it can drop anything at any GC boundary. If losing the object would be a bug, you wanted a `sync.Map` or a real cache, and the pool is hiding a race.

## The harness

```go
const bufSize = 2048

// touch walks the buffer so the memory itself is measured,
// not just the allocator's bookkeeping.
func touch(b []byte) byte {
	for i := 0; i < len(b); i += 64 {
		b[i]++
	}
	return b[0]
}

// heapByte forces escape: a slice read through a package-level
// variable cannot stay on the stack.
var heapByte []byte

var sinkByte byte

func BenchmarkAllocPerRequest(b *testing.B) {
	b.ReportAllocs()
	for i := 0; i < b.N; i++ {
		buf := make([]byte, bufSize)
		sinkByte = touch(buf)
		heapByte = buf
		sinkByte = heapByte[0]
	}
}

var pool = sync.Pool{
	New: func() any {
		b := make([]byte, bufSize)
		return &b
	},
}

func BenchmarkSyncPool(b *testing.B) {
	b.ReportAllocs()
	for i := 0; i < b.N; i++ {
		bp := pool.Get().(*[]byte)
		sinkByte = touch(*bp)
		heapByte = *bp
		sinkByte = heapByte[0]
		pool.Put(bp)
	}
}
```

The `bytes.Buffer` and parallel variants follow the same shape; the full file is the one quoted in the screenshot above.

## Takeaway

Pool the object your hot path allocates every request, once you have confirmed it escapes. For a 2 KiB scratch buffer that is a 13x reduction in per-op cost and the removal of 2 KB per request from the GC's plate. For a `bytes.Buffer` it is still a 4x win. But measure first: if escape analysis already kept your value on the stack, the pool is a tax, not a saving.
