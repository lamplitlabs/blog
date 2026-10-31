---
layout: post
title: "Rust Release Profiles in Production: LTO, codegen-units, and target-cpu Cut Our p99 by 54%"
date: 2026-10-24
categories: performance rust
tags: rust performance lto codegen-units target-cpu cargo axum benchmark release-profile
description: "Our Rust dedup prefilter ran a 38 ms p99 on the default release profile. Adding lto=fat, codegen-units=1, and target-cpu=native cut it to 17.6 ms."
image:
  path: /assets/img/posts/performance/rust-lto-codegen-units-p99-latency.webp
  alt: Bar chart of Rust dedup prefilter p99 latency across five cargo release profiles, dropping from 412 ms in debug to 17.6 ms with lto fat codegen-units 1 and target-cpu native
---

The fastest Rust code change is the one you never write. Our dedup prefilter — the axum service that strips duplicate records from an ingestion stream before they hit the downstream writer — shipped for a month on `cargo build --release` with no `[profile.release]` block at all. It met its throughput target, so nobody looked. When a capacity review flagged that the service was our second-largest CPU consumer per request, the fix was not a rewrite: it was three lines in `Cargo.toml`. This post shows what each flag did, measured on the live binary, and why the defaults leave that much on the table.

## The workload

The prefilter is a small tokio + axum service. Each request carries a batch of records; the service hashes each one, checks it against an in-memory shard map, and forwards only the records the shard has not seen:

1. A POST arrives with a JSON array of records (median batch ~400 records, ~90 KiB).
2. Each record is hashed with a non-cryptographic hash and looked up in a sharded `DashMap`.
3. New records are serialized and forwarded; duplicates are counted and dropped.

The hot path is tight and CPU-bound: hash, compare, serialize. There is no I/O wait worth mentioning — the downstream writer is co-located and the shard map is in memory. That makes the service a clean lens for compiler optimization, because wall-clock latency is dominated by how well the generated code runs, not by what it waits on.

## The default release profile is not optimized for production

Here is the part that surprises people coming from Go or Java: `cargo build --release` turns on optimizations, but it does not turn on *all* of them. The default release profile is a compromise between runtime speed and compile time:

```toml
# What you get with an empty [profile.release]:
# opt-level = 3        (full optimization)  -- yes
# lto = false          (no link-time opt)   -- left off
# codegen-units = 16   (parallel, but fragments optimization)
# panic = "unwind"     (unwinding tables kept)
```

`opt-level = 3` is on, but two things are not: link-time optimization, and single-codegen-unit compilation. Both default off to keep `cargo build --release` fast, and both matter for a CPU-bound hot path.

## Step 1: lto = "thin" — the free win

Link-time optimization lets the optimizer see across crate boundaries. Without it, every call into a dependency — and the prefilter leans on `axum`, `serde`, `dashmap`, and `ahash` — is an opaque function call the optimizer cannot inline. With `lto = "thin"`, LLVM runs a lean cross-module pass at link time and inlines the hot ones:

```toml
[profile.release]
lto = "thin"
```

One line. p99 dropped from 38.4 ms to 27.9 ms — a 27% improvement — because the hash-and-compare loop is exactly the kind of code that benefits: small functions from dependency crates, called millions of times, that the optimizer can now inline and specialize at the call site.

## Step 2: lto = "fat" — see the whole program

`"thin"` LTO parallelizes the cross-module pass by splitting the module graph, which is fast but conservative. `"fat"` LTO merges everything into one module before optimizing, so the optimizer sees the entire program — your code and every dependency — as a single unit:

```toml
[profile.release]
lto = "fat"
```

p99 fell to 24.1 ms. The gain over `"thin"` was smaller here (about 14%) because the prefilter's hot path is already narrow, but it was consistent across runs. The cost is compile time: the link step got noticeably slower. For a service we build once per release in CI, that trade is trivially worth it.

## Step 3: codegen-units = 1 — optimize as one unit

This is the flag most people have never heard of. To speed up compilation, rustc splits each crate into multiple *codegen units* that are optimized in parallel — 16 by default in release. The catch: the optimizer cannot inline or reorder across codegen-unit boundaries within your own crate, so splitting the hot path across units blocks optimizations that would otherwise fire.

Setting it to 1 tells rustc to compile the crate as a single unit:

```toml
[profile.release]
lto = "fat"
codegen-units = 1
```

p99 dropped to 21.3 ms. Combined with `lto = "fat"`, this is where the biggest single jump came from: the optimizer could finally see the whole hot loop — our code and the inlined dependency calls — as one unit and keep the record data in registers instead of round-tripping through memory.

## Step 4: target-cpu = native — use the actual silicon

Everything so far is portable. This last one is not, and it is the reason the post has a caveat section. By default, rustc compiles for a generic x86-64 baseline, which means it will not emit instructions your CPU supports but the baseline does not — most importantly AVX2 vector instructions. The hash loop and the serializer both vectorize well.

Setting `target-cpu=native` tells LLVM to tune for the exact build machine:

```toml
# .cargo/config.toml — not [profile.release], this is a rustflag
[build]
rustflags = ["-C", "target-cpu=native"]
```

p99 fell to 17.6 ms — another 17% — as the hash inner loop and the JSON serializer both got vectorized. Cumulative, from 38.4 ms to 17.6 ms is a 54% reduction, with zero changes to application code.

![Bar chart of Rust dedup prefilter p99 latency across five cargo release profiles, dropping from 412 ms in debug to 38.4 ms at default release and down to 17.6 ms with lto fat codegen-units 1 and target-cpu native](/assets/img/posts/performance/rust-lto-codegen-units-p99-latency.webp){: width="1200" height="630" }

The debug column is there for scale and as a warning: a `cargo build` (dev) binary of the same service runs a 412 ms p99, eleven times slower than even default release. If you have ever benchmarked a dev build and concluded Rust is slow, this is why.

## Throughput tells the same story

Latency is what users feel; throughput is what the capacity review cared about. Measured as sustained requests/second under the same wrk2 load, each flag added headroom on top of the last:

![Bar chart of sustained throughput in requests per second as release-profile flags accumulate, rising from 52.1k at default release to 113.6k with lto fat codegen-units 1 and target-cpu native, a cumulative gain of 118 percent](/assets/img/posts/performance/rust-lto-codegen-units-throughput.webp){: width="1200" height="630" }

From 52.1k to 113.6k req/s is a 118% throughput increase on the same hardware and the same code. In capacity terms, the service went from our second-largest CPU consumer per request to comfortably inside its original budget — the review that triggered this work closed with no hardware change.

## The caveat: target-cpu=native is not portable

`lto` and `codegen-units` are safe to commit for any service. `target-cpu=native` is different: the binary is tuned to the machine that built it, and if that machine is newer than your oldest production host, the binary can execute an instruction the older CPU does not have and crash with `SIGILL` on startup.

Three rules make it safe:

1. **Build on your oldest production CPU, or older.** If your fleet is uniform, build anywhere. If it is mixed, build on the oldest model so "native" means the common denominator.
2. **Or pin an explicit microarchitecture level** like `-C target-cpu=x86-64-v3` instead of `native`. This gets you AVX2 without tuning to one specific chip, and any v3-capable machine runs it. For most fleets this is the right choice — nearly all the gain, none of the guesswork.
3. **Smoke-test the artifact on a production-class host before rollout.** A binary that starts and serves one request has proven it does not hit an illegal instruction on that hardware.

We run a homogeneous fleet and build in CI on a host that matches it, so `native` is safe for us. If we did not, we would use `x86-64-v3` and keep almost all of the step-4 gain.

## What we did not do, and why

Two flags people reach for next are `panic = "abort"` and `opt-level = "z"`. We skipped both. `panic = "abort"` shrinks the binary and removes unwinding overhead, but it turns a panicking worker thread into a dead process — the wrong trade for a service we want to degrade, not die, on a bad input. `opt-level = "z"` optimizes for size, which matters for embedded targets, not for a service binary on a host with gigabytes of disk. Neither moved our p99 in a way that justified its cost.

## The final profile

The whole change, committed to `Cargo.toml` and `.cargo/config.toml`:

```toml
[profile.release]
lto = "fat"
codegen-units = 1
```

```toml
# .cargo/config.toml
[build]
rustflags = ["-C", "target-cpu=native"]  # or x86-64-v3 on a mixed fleet
```

Three effective lines, no application code touched, and a 54% p99 reduction plus a 118% throughput increase on a CPU-bound service. The broader lesson generalizes: `cargo build --release` is the starting point of release optimization, not the end. Before you rewrite a hot Rust service, check its release profile — the compiler may already know how to make it faster and is simply waiting for permission.

## Related

- [Rust RwLock on a Read-Heavy Path: parking_lot vs std::sync, Measured](/posts/rust-parking-lot-vs-std-rwlock/) — the lock swap stacks on top of the compiler flags here; both were measured on the same CPU-bound hot path.
- [Rust Small-String Optimization: compact_str Cut Our Tokenizer Sidecar p99](/posts/rust-small-string-optimization-llm-tokenizer-sidecar/) — a data-layout change that pairs well with the compiler flags here; both target a CPU-bound Rust hot path.
- [Rust Async Under Load: Tokio Backpressure in an LLM Gateway](/posts/rust-tokio-async-llm-gateway-backpressure/) — when the bottleneck is queueing rather than codegen, the fix is architectural, not a compiler flag.
- [Rust vs Go for a CPU-Bound Microservice](/posts/rust-vs-go-cpu-bound-microservice/) — the same release-profile flags used in a head-to-head language benchmark.
