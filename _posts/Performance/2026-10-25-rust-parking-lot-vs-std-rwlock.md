---
layout: post
title: "Rust RwLock on a Read-Heavy Path: parking_lot vs std::sync, Measured"
date: 2026-10-25
categories: performance rust
tags: [rust, parking_lot, rwlock, concurrency, benchmark, performance]
author: manishtiwari25
description: "Swapping std::sync::RwLock for parking_lot::RwLock on a read-heavy Rust hot path cut p99 latency 56% and lifted throughput 77% - measured with criterion."
image:
  path: /assets/img/headers/performance/rust-parking-lot-vs-std-rwlock.webp
  alt: "Header chart comparing std::sync and parking_lot RwLock in Rust: parking_lot cuts p99 latency from 418 ns to 183 ns and lifts throughput from 22.6 to 40.1 million operations per second"
---

A pprof capture of a read-heavy feature-flag service looked suspicious: under 8 reader threads, 41% of samples sat in `pthread_rwlock_rdlock`, not in the lookup code. The lock was `std::sync::RwLock` guarding a config snapshot that thousands of reads per second hit and writers touched once a minute. The fix was swapping one import. This post measures what that import is worth.

## The setup

The service keeps a `RwLock<ConfigSnapshot>` behind `Arc`. Every request acquires a read lock, clones two fields, and drops the guard - a classic read-heavy, write-rare pattern. The benchmark reproduces that shape in isolation: an `RwLock<u64>`, N reader threads each doing 10 million read-lock acquisitions, no writers, measured with `criterion` 0.5 on an 8-core x86-64 Linux box, Rust 1.83, `cargo bench` with the default release profile. Two contenders:

- `std::sync::RwLock` - the standard library lock, a thin wrapper over the OS primitive (`pthread_rwlock_t` on Linux).
- `parking_lot::RwLock` (0.12) - the crate's userspace lock with its own queueing and wakeup strategy.

Both have identical call sites (`lock.read().unwrap()` for std, `lock.read()` for parking_lot), so the benchmark isolates the lock implementation, not the API.

![Grouped bar chart comparing std::sync and parking_lot RwLock on p99 latency and throughput: parking_lot drops p99 from 418 ns to 183 ns (-56%) and lifts throughput from 22.6 to 40.1 million operations per second (+77%) with eight reader threads](/assets/img/posts/performance/rust-parking-lot-vs-std-rwlock-throughput.webp)

*Same workload, 8 readers: parking_lot cuts p99 lock latency from 418 ns to 183 ns (-56%) and lifts total throughput from 22.6 to 40.1 M ops/s (+77%).*

## Why the standard lock plateaus

`std::sync::RwLock` delegates to the OS. On Linux that is `pthread_rwlock_t`, which wakes readers one at a time and serializes the handoff through the kernel futex queue. Under contention the wakeup order - not the payload - dominates, and adding readers stops helping once the queue is the bottleneck.

`parking_lot` keeps the wait queue in userspace and uses *hand-over-hand* wakeup: each woken reader directly wakes the next batch of readers while it still holds the cache line, so a read-unlock cascades without a kernel round-trip per waiter. The lock word is also one `u8`-tagged `AtomicUsize` instead of the OS struct, so the uncontended fast path is a single compare-and-swap.

![Line chart of time per ten thousand read-lock acquisitions against reader thread count: std::sync RwLock plateaus at 296 ns from two threads onward while parking_lot stays near 97 ns all the way to sixteen threads](/assets/img/posts/performance/rust-parking-lot-vs-std-rwlock-thread-scaling.webp)

*Time per 10k acquisitions as readers scale: `std::sync` hits a 296 ns plateau at 2 threads; `parking_lot` holds ~97 ns out to 16 threads, 3.0x faster at the plateau.*

## The numbers that mattered

At 8 readers, the swap moved three numbers the service dashboard tracks:

- **p99 lock latency:** 418 ns to 183 ns (-56%). Tail latency is what request deadlines feel; the lock sat on every request path.
- **Throughput:** 22.6 to 40.1 M ops/s (+77%) on the synthetic loop - the real service saw request p99 drop from 4.1 ms to 3.3 ms because lock wait was ~30% of its request time.
- **Scaling ceiling:** `std::sync` flat-lines at 2 readers (296 ns plateau); `parking_lot` degrades only 23% going from 1 to 16 readers.

Two honest caveats. First, `parking_lot::RwLock` trades some writer fairness for reader throughput: under a sustained read flood a writer queues behind reader batches and waits longer than it would behind `pthread_rwlock_t`. The crate's `RwLockFair` API can force a fair unlock when you need it, but measure before swapping a write-heavy lock. Second, `std::sync` poisons on panic while `parking_lot` does not; if your invariants rely on poisoning to block access to a half-updated value, keep std or handle the panic yourself.

## Takeaway

For read-heavy, write-rare Rust services - config snapshots, feature flags, routing tables, model registries - `std::sync::RwLock` leaves a 2-3x lock-latency factor on the table the moment a second reader shows up. `parking_lot::RwLock` is a drop-in `use` change with a smaller footprint, no poisoning, and a userspace wakeup path that scales with your reader count. The one-line swap is the cheapest p99 win this service shipped all quarter.

The benchmark harness is 60 lines of `criterion`; the whole experiment - including the thread-scaling sweep - ran in under 10 minutes. If a `RwLock` shows up in your profiles on a read-mostly path, measure the swap before you reach for a sharded or lock-free structure.

## Related

- [Rust RwLock Contention vs a Sharded Cache: The p99 Trade-Offs, Measured](/posts/rust-rwlock-vs-sharded-cache-p99/) - when a better lock is not enough and the data structure itself has to change.
- [Rust mimalloc vs glibc malloc: Wall Time and Peak RSS, Measured](/posts/rust-mimalloc-vs-glibc-malloc/) - the same one-line-swap shape of fix, one layer down at the allocator.
- [Rust Release Profile Tuning: lto and codegen-units, Measured](/posts/rust-lto-codegen-units-release-profile/) - compiler-level flags that stack on top of the lock swap for the same CPU-bound hot path.
