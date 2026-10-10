---
layout: post
title: "Go vs Rust for a GC-Sensitive AI Inference Gateway: p99 Latency, Memory and GC Pauses, Measured"
date: 2026-11-26 00:00:00 +0200
categories: performance languages ai
tags: go rust ai-inference gateway batching latency garbage-collection memory performance benchmark enterprise-ai
author: manishtiwari25
description: "Same routing + micro-batching gateway in Go and Rust, 3,000 req/s on 4 vCPU. Added p99: Go 9.4 ms, Rust 2.7 ms; RSS 148 MB vs 34 MB; where Go still wins."
image:
  path: /assets/img/headers/performance/go-vs-rust-ai-inference-gateway.webp
  alt: "Bar chart of added latency for a Go and a Rust AI inference gateway at 3,000 requests per second: p50 1.9 vs 1.1 ms, p99 9.4 vs 2.7 ms, p99.9 27.8 vs 4.6 ms, Go max GC pause 3.1 ms"
---

An inference gateway is the thin service between your clients and the model servers: it authenticates, picks a backend (model, version, region), coalesces requests into micro-batches, and streams tokens back. It does almost no compute of its own, so it is tempting to call the language choice irrelevant. It is not. The gateway sits on the critical path of every token, and when it stalls for a garbage-collection pause, the model's 286 ms time-to-first-token becomes 290 ms for everyone in the batch at once.

We built the same gateway twice, in Go and in Rust, and measured it the way we measured the [CPU-bound microservice](/posts/rust-vs-go-cpu-bound-microservice/): same hardware, same load generator, same backend, numbers reported at the tail where users actually feel them.

## The workload

- **Shape**: HTTP/1.1 JSON in, Server-Sent Events out. Each request carries a 400-token prompt and asks for 128 output tokens.
- **Logic**: JWT validation (cached key set), tenant lookup, routing by model name to one of four vLLM pools, a 5 ms micro-batcher that merges up to 16 requests per pool, and fan-out of streamed tokens back to each client.
- **Backend**: a stub that behaves like vLLM at p50 (streams one token every 14 ms after a 90 ms first-token delay) so the gateway, not the GPU, is the only variable. The real-vLLM numbers from the [serving-framework comparison](/posts/vllm-vs-tgi-vs-tensorrt-llm-serving-latency/) were used as a sanity check at the end.
- **Hardware**: one 4 vCPU / 8 GB pod per gateway (AKS, Standard_D4s_v5), load generator on a separate node, 10 minutes per rate after a 2 minute warm-up, three runs, median reported.
- **Load**: 1,000, 3,000 and 6,000 req/s open-loop with 2,000 concurrent streaming connections.

Implementation sizes were close: Go 1.23 with `net/http` and `encoding/json`, 1,840 lines; Rust 1.82 with `axum`, `tokio` and `serde_json`, 2,210 lines. Both were written by engineers who use the language daily and both went through one profiling pass before measurement.

## Added latency at 3,000 req/s

"Added" means gateway-in minus backend-out, so the backend's token delays are excluded.

| Metric | Go 1.23 | Rust 1.82 |
| --- | ---: | ---: |
| p50 | 1.9 ms | 1.1 ms |
| p99 | 9.4 ms | 2.7 ms |
| p99.9 | 27.8 ms | 4.6 ms |
| Max observed | 41 ms | 9 ms |
| CPU at 3,000 req/s | 2.9 cores | 1.6 cores |

At the median the gap is 0.8 ms and nobody would notice. At p99 it is 3.5x and at p99.9 it is 6x, and the shape of Go's tail is the interesting part: it is not a smooth curve, it is a flat line with spikes every 400-600 ms. Those spikes line up exactly with `runtime/trace` GC cycles.

## GC pauses, measured, not guessed

Go's collector is concurrent and its stop-the-world phases are short - the `gctrace` log showed STW pauses of 0.1-0.4 ms. That is not where the 27 ms came from. The cost was the *assist* phase: when allocation outruns the background marker, goroutines doing the allocating are drafted into marking. With 2,000 streaming connections each allocating a small buffer per token, the gateway allocates around 180 MB/s at 3,000 req/s, and the mutator spends up to 25% of a cycle assisting.

| GC metric (Go, 3,000 req/s) | GOGC=100 | GOGC=400 | GOMEMLIMIT=6GiB, GOGC=off |
| --- | ---: | ---: | ---: |
| Cycles per second | 2.3 | 0.6 | 0.1 |
| Max STW pause | 0.4 ms | 0.5 ms | 0.6 ms |
| Max mutator assist stall | 3.1 ms | 1.2 ms | 0.3 ms |
| p99 added latency | 9.4 ms | 5.8 ms | 3.9 ms |
| p99.9 added latency | 27.8 ms | 12.1 ms | 6.3 ms |
| RSS | 148 MB | 512 MB | 4.9 GB |

Rust has no collector, so the equivalent column is simply "none": every allocation is freed when the token buffer is dropped, and `jemalloc` kept RSS flat. Rust's residual p99.9 of 4.6 ms came from `tokio` task wake-up jitter under 2,000 connections, visible with `tokio-console`, and from the batcher's 5 ms timer firing late by up to 1 ms when all four workers were busy.

The honest reading: with tuning, Go closes most of the latency gap. The price is memory - 33x more RSS to get within 1.5x of Rust's p99.

## Memory under load

![Grouped bar chart of gateway resident memory in MB: Go 96, 148, 241 MB at 1,000, 3,000 and 6,000 requests per second and 512 MB with GOGC=400, Rust 31, 34, 39 MB at the same rates](/assets/img/posts/performance/go-vs-rust-ai-inference-gateway-memory.webp){: width="1200" height="700" }
_Resident set size after 10 minutes at each offered rate. Rust's footprint is almost independent of load; Go's grows with allocation rate and with any GC tuning that trades memory for pauses._

| Offered rate | Go RSS | Rust RSS | Go p99 | Rust p99 |
| --- | ---: | ---: | ---: | ---: |
| 1,000 req/s | 96 MB | 31 MB | 4.1 ms | 1.9 ms |
| 3,000 req/s | 148 MB | 34 MB | 9.4 ms | 2.7 ms |
| 6,000 req/s | 241 MB | 39 MB | 31.6 ms | 4.8 ms |

At 6,000 req/s the Go gateway was CPU-saturated (3.9 of 4 cores) and the p99 reflects queueing, not GC. Rust reached the same rate at 2.7 cores. On a fleet of 40 gateway pods that is roughly 60 fewer vCPU and 8 GB less memory for the Rust build at the 6,000 req/s tier, which on D4s_v5 list price is about $2,100 a month.

## What Go did better

- **Time to working build**: Go 3 days, Rust 7. Most of the Rust delta was lifetimes around the shared batcher state and getting cancellation right when a client disconnects mid-stream (`tokio::select!` with a `CancellationToken` solved it, after two wrong attempts).
- **Compile time**: 4 s vs 71 s for an incremental release build. Over a hundred iterations a day this matters.
- **Debugging a leak**: a goroutine leak on client disconnect showed up in `pprof` in minutes. The equivalent Rust bug (a `JoinHandle` never awaited) took longer to find because nothing reports an orphaned task by default.
- **Operational familiarity**: our platform team already runs eight Go services; the Rust gateway added a toolchain, a `cargo audit` step and a second set of profiler habits.

## Decision

For a gateway that fronts a model with a 90 ms time-to-first-token, Go at GOGC=100 adds 9.4 ms at p99 - about 10% of what the user already waits. If your SLO is on the whole request, that is noise and Go's faster delivery wins. If your SLO is on the gateway itself (the common case when the inference team and the platform team are different teams), or if you run at the 6,000 req/s tier where Go needs 1.5x the pods, Rust pays for the extra week within the first quarter.

We shipped the Rust gateway for the shared multi-tenant tier and kept Go for the internal, single-model tier where nobody measures the gateway separately. Both decisions came from the table above, not from the language debate.

## Related

- [Rust vs Go for a CPU-Bound Microservice](/posts/rust-vs-go-cpu-bound-microservice/) - the same pair of languages on a compute-heavy service, where the gap comes from codegen rather than from the collector.
- [vLLM vs TGI vs TensorRT-LLM: LLM Serving Latency](/posts/vllm-vs-tgi-vs-tensorrt-llm-serving-latency/) - the backend numbers this gateway sits in front of, and why 9 ms at the gateway matters against a 286 ms TTFT.
- [Go vs .NET: Goroutines vs Tasks Concurrency Throughput](/posts/go-vs-dotnet-goroutines-vs-tasks-concurrency-throughput/) - how Go's scheduler and GC behave on a pure I/O-bound workload.
