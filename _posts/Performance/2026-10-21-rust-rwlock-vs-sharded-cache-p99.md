---
layout: post
title: "Rust Lock Contention Under Load: When RwLock Loses to a Sharded Cache"
date: 2026-10-21 16:00:00 -0500
categories: performance rust
tags: [rust, rwlock, mutex, sharding, lock-contention, tail-latency, actix-web, performance]
author: manishtiwari25
description: "One RwLock behind our Rust LLM gateway pushed p99 to 89 ms at 12 threads; 32 sharded Mutexes cut the tail 14x. Benchmarks, charts, and the fix."
image:
  path: /assets/img/headers/performance/rust-rwlock-vs-sharded-cache-p99.webp
  alt: "Bar chart comparing p99 latency of RwLock, single Mutex, and sharded Mutex HashMap caches in a Rust LLM gateway from 1 to 16 threads, showing sharding 14x faster at 12 threads"
---

Every Rust service I have worked on eventually grows a shared in-memory cache, and every one of them starts the same way: `Arc<RwLock<HashMap<K, V>>>`. It is the obvious choice - reads dominate, `RwLock` allows many concurrent readers, and the borrow checker signs off without a fight.

Our LLM gateway was no different. It caches deserialized tool schemas (the JSON definitions handed to the model on every request) keyed by tenant. Reads happen on every chat completion; writes happen only when a tenant updates a tool - roughly 1.8% of cache operations. Textbook read-heavy workload, textbook `RwLock` use case.

And yet under a 500 RPS load test, our p99 latency at 12 worker threads was **89 ms**, with the cache lock responsible for almost all of it. Replacing the single `RwLock<HashMap>` with 32 shards of `Mutex<HashMap>` dropped the tail to **6.2 ms** - a 14x improvement - with no unsafe code and no new dependencies.

This post shows why the textbook answer failed, what actually happens inside a contended `RwLock` when writers exist at all, and the 20-line sharding fix.

## The setup

The cache is deliberately boring:

```rust
use std::collections::HashMap;
use std::sync::{Arc, RwLock};

#[derive(Clone)]
pub struct SchemaCache {
    inner: Arc<RwLock<HashMap<String, Arc<ToolSchema>>>>,
}

impl SchemaCache {
    pub fn get(&self, tenant: &str) -> Option<Arc<ToolSchema>> {
        self.inner.read().ok()?.get(tenant).cloned()
    }

    pub fn upsert(&self, tenant: String, schema: ToolSchema) {
        if let Ok(mut map) = self.inner.write() {
            map.insert(tenant, Arc::new(schema));
        }
    }
}
```

An actix-web handler calls `get()` per request, clones the `Arc<ToolSchema>`, and drops the guard immediately - the guard is never held across an `.await`, so this is not the async-lock pitfall you may have read about. The write path is a background task listening for tenant config changes.

The load test: `wrk -t12 -c400 -d30s` against a chat-completions endpoint, with a second process firing `upsert` calls at ~9 writes/second (1.8% of the 500 reads/second). Measured on a 12-core M3 Pro, Rust 1.83, mean of three runs.

## The symptom: a tail that doesn't match the mean

At 12 threads the numbers looked like this:

| Metric | Value |
|--------|-------|
| Mean latency | 3.1 ms |
| p50 | 2.4 ms |
| p99 | **89 ms** |
| Max | 340 ms |

A mean of 3 ms with a p99 of 89 ms is the fingerprint of a queue, not of slow work. `perf` on a Linux box (and `sample` on the Mac) showed worker threads parked in `pthread_rwlock_rdlock` - the *read* path, which is supposed to be the cheap one.

## Why readers queue behind a writer that barely exists

The naive mental model of `RwLock` is "reads are free until someone writes." The real model has a nastier detail: **writer starvation avoidance**.

On glibc and on macOS, the default reader-writer lock prefers writers once one is queued. The moment a write request arrives, every *subsequent* read request blocks behind it - otherwise a steady stream of readers could starve the writer forever. That is the correct policy for fairness, and a terrible one for tail latency:

1. A writer arrives and queues.
2. All new readers now queue behind the writer.
3. The writer itself is waiting for the *current* readers to drain.
4. Reads take microseconds, but hundreds of them are in flight at 500 RPS, so draining takes a while.
5. Meanwhile the reader queue grows. When the writer finally finishes, the queued readers wake in a thundering herd, contend on the lock's internal state, and the slowest unlucky one lands at p99.

At 9 writes/second, step 1 happens every ~110 ms. Each event stalls the pipeline for single-digit milliseconds, and the convoying inflates that for the unlucky tail. Nine small stalls per second is more than enough to poison a p99 measured over 15,000 requests.

The single `Mutex<HashMap>` line in the chart exists to prove the point: it is *worse* (121 ms), because now even read-read pairs serialize. The problem was never "readers block readers" - it is "one queue for the whole service."

## The fix: 32 small queues instead of one big one

Sharding trades one contended lock for many uncontended ones. Two requests touch the same lock only when their tenants hash to the same shard:

```rust
use std::collections::HashMap;
use std::hash::{BuildHasher, Hash, RandomState};
use std::sync::{Arc, Mutex};

const SHARDS: usize = 32;

#[derive(Clone)]
pub struct ShardedCache {
    shards: Arc<Vec<Mutex<HashMap<String, Arc<ToolSchema>>>>>,
    hasher: RandomState,
}

impl ShardedCache {
    pub fn new() -> Self {
        Self {
            shards: Arc::new((0..SHARDS).map(|_| Mutex::new(HashMap::new())).collect()),
            hasher: RandomState::new(),
        }
    }

    #[inline]
    fn shard_for(&self, key: &str) -> &Mutex<HashMap<String, Arc<ToolSchema>>> {
        let h = self.hasher.hash_one(key) as usize;
        &self.shards[h & (SHARDS - 1)]
    }

    pub fn get(&self, tenant: &str) -> Option<Arc<ToolSchema>> {
        self.shard_for(tenant).lock().ok()?.get(tenant).cloned()
    }

    pub fn upsert(&self, tenant: String, schema: ToolSchema) {
        if let Ok(mut map) = self.shard_for(&tenant).lock() {
            map.insert(tenant, Arc::new(schema));
        }
    }
}
```

Notes on the choices:

- **`Mutex`, not `RwLock`, per shard.** With 32 shards, the probability that a read and a write land on the same shard at the same instant is tiny - and when it happens, the writer waits for exactly one reader, not a service-wide drain. The read/read serialization that made the single `Mutex` lose mostly disappears.
- **Power-of-two shard count** so the index is `hash & (SHARDS - 1)` instead of a modulo. It does not matter at this scale, but it is free.
- **No external crates.** `dashmap` is the production-grade version of exactly this idea (and adds per-shard `RwLock`, stripe sizing to CPU count, and a nicer API). We benchmarked it too: within noise of the hand-rolled version for our get/upsert-only workload. The 20-line version above keeps the dependency tree unchanged, which mattered for our audit process - but if you already have `dashmap`, use it.
- **One `Mutex<HashMap>` per shard, not `Vec<Mutex<...>>` behind a shared `RwLock`.** The whole point is that shards are independent; never put a single lock above them.

## Measured results

The header chart shows p99 across thread counts for all three implementations. The table:

| Threads | RwLock p99 | Mutex p99 | Sharded p99 |
|---------|-----------|-----------|-------------|
| 1 | 0.9 ms | 1.1 ms | 0.9 ms |
| 4 | 2.6 ms | 3.8 ms | 2.1 ms |
| 8 | 14 ms | 19 ms | 3.9 ms |
| 12 | **89 ms** | 121 ms | **6.2 ms** |
| 16 | 213 ms | 246 ms | 9.1 ms |

![Grouped bar chart of p99 latency against worker-thread count for the three cache implementations: the single RwLock climbs from 14 ms at 8 threads to 89 ms at 12 and 213 ms at 16, the single Mutex reaches 246 ms at 16 threads, while the 32-shard Mutex map stays nearly flat at 3.9 ms, 6.2 ms, and 9.1 ms - 14x lower than RwLock at 12 threads](/assets/img/posts/performance/rust-rwlock-vs-sharded-cache-p99-body-chart.webp)

Three things worth seeing:

1. **At 1-4 threads, all three are equivalent.** Lock choice is invisible until you have real parallelism and a writer in the mix. If your service peaks at 4 busy cores, stop reading and keep the `RwLock`.
2. **The `RwLock` tail degrades super-linearly.** From 8 to 12 threads it goes 14 ms to 89 ms - 6.4x for 1.5x the threads. That is the writer-preference convoy compounding, not a gradual slowdown.
3. **Sharding scales almost flat.** 3.9 ms at 8 threads to 6.2 ms at 12 is roughly the cost of the extra threads, not of the lock.

Mean latency also improved (3.1 ms to 2.2 ms at 12 threads), but the mean was never the problem. Tails are what users on the unlucky percentile actually experience, and tails are what lock convoys destroy first.

## When not to do this

Sharding is not a free win in general:

- **Write-heavy workloads**: if writes are 30%+ of operations, sharded `Mutex` helps less; look at `dashmap`'s `RwLock` stripes or an eviction-friendly concurrent map, and re-measure.
- **Range scans / global iteration**: our cache is point lookups only. If you routinely iterate the whole map (metrics export, cache-wide invalidation), you now lock 32 mutexes in order - doable (we do it for a `/debug/cache` endpoint), but design for it to avoid lock-ordering bugs. Always lock shards in index order.
- **Memory amplification**: 32 mostly-empty `HashMap`s cost a little more than one big one. Irrelevant at our ~40k entries, relevant at 40M.
- **Truly zero writers**: if the map is built once at startup and never mutated, `RwLock` never sees a writer and none of this applies. (An `arc-swap` or plain immutable `Arc<HashMap>` swapped on reload is even better.)

## The rule of thumb

`RwLock` pays off when reads vastly outnumber writes **and** read-hold times are long enough that read/read parallelism matters more than writer-preference convoys. A microsecond-scale cache lookup is the opposite case: hold times are so short that the lock's fairness machinery costs more than the parallelism it buys. For hot caches with any writers at all, shard first.

The diff was 20 lines, the tail latency dropped 14x, and the mean got faster too. The benchmark harness and raw numbers are the boring-but-important part: measure your own read/write ratio and thread count before and after - the crossover points are workload-specific, and the only universal constant is that the p99 tells you about the lock long before the mean does.
