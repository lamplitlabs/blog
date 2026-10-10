---
title: "gRPC vs REST JSON: What the Protocol Actually Buys You, Measured on .NET 8 and Go"
date: 2026-10-22 08:00:00 +0200
categories: performance dotnet
tags: performance grpc rest api dotnet csharp go benchmark aspnetcore
description: "gRPC vs REST JSON throughput, p99 latency and wire size measured on ASP.NET Core 8 and Go 1.23 with wrk and ghz."
image:
  path: /assets/img/headers/performance/grpc-vs-rest-dotnet-go.webp
  alt: "Bar chart of requests per second at 64 connections with a 2 KB payload: Go gRPC 118,400, .NET 8 gRPC 112,900, Go REST 96,200, .NET 8 Minimal API 91,700, .NET 8 Controllers 78,300"
---

![Bar chart of requests per second at 64 connections with a 2 KB payload: Go gRPC 118,400, .NET 8 gRPC 112,900, Go REST 96,200, .NET 8 Minimal API 91,700, .NET 8 Controllers 78,300](/assets/img/headers/performance/grpc-vs-rest-dotnet-go.webp){: width="1200" height="630" }

"Should we move this service to gRPC?" comes up in almost every architecture review I sit in, and the answer is usually given from memory rather than from a measurement. So I built the same small service twice in two languages and measured it, the same way the earlier posts in this category measured a [Python vs Rust hot loop]({% post_url Performance/2026-10-07-python-vs-rust-hot-loop-performance %}) and [HTTP runtimes]({% post_url Performance/2026-10-04-node-vs-deno-vs-bun-http-performance %}).

## The service

A single `GetOrder(orderId)` call that returns an order with eight line items. The response is about 2 KB as JSON and about 1.2 KB as Protobuf. The handler reads from an in-memory dictionary so the measurement is the transport and serialization, not a database.

Four servers, all on the same 4-vCPU VM:

- **.NET 8 gRPC** (`Grpc.AspNetCore` 2.66, Kestrel, HTTP/2)
- **.NET 8 REST** as a Minimal API and again as a Controller with `System.Text.Json` source generation
- **Go 1.23 gRPC** (`google.golang.org/grpc` 1.67)
- **Go 1.23 REST** with `net/http` and `encoding/json`

Load came from a second VM in the same subnet: `wrk 2.1` for REST, `ghz 0.120` for gRPC, 64 connections, 60 seconds per run, five runs, median reported.

## Throughput and latency

![Table of p50 and p99 latency, wire bytes per request and CPU percent: Go gRPC 0.49 ms p50, 2.1 ms p99, 1,210 bytes, 71% CPU; .NET 8 gRPC 0.52, 2.4, 1,210, 74%; Go REST 0.61, 3.9, 2,870, 83%; .NET 8 Minimal API 0.64, 4.3, 2,870, 85%; .NET 8 Controllers 0.77, 5.8, 2,870, 91%](/assets/img/posts/performance/grpc-vs-rest-latency-table.webp){: width="1200" height="760" }

Three things in that table matter more than the headline number:

1. **The language gap is smaller than the protocol gap.** Go and .NET 8 are within 5% of each other on both protocols. Switching from JSON to gRPC bought 15-23% throughput; switching language bought almost nothing.
2. **p99 moves more than p50.** gRPC's p99 is roughly half the JSON p99. The reason is the HTTP/2 multiplexing and the absence of a JSON tokenizer in the hot path, which shows up under contention rather than in the median.
3. **Controllers cost 14% against Minimal APIs** for the same JSON. That is the MVC filter pipeline and model binding, and it is the cheapest thing in this table to fix if you are on REST and staying there.

## Payload size changes the answer

I reran the test with a 200-byte response (a single status field) and a 64 KB response (the order plus its full history).

| Payload | gRPC advantage in req/s (.NET 8) |
|---|---|
| 200 B | 6% |
| 2 KB | 23% |
| 64 KB | 2.1x |

At 200 bytes the request is dominated by connection handling and the serializer barely matters. At 64 KB `System.Text.Json` spends most of its time writing UTF-8 property names that Protobuf replaces with one-byte field tags; the wire size drops by 58% and the CPU goes with it.

## What gRPC does not buy you

- **Browser clients** still need grpc-web and a proxy. If the service is called from a SPA, you are keeping JSON somewhere.
- **Debuggability** regresses. `curl` and the browser network tab stop being enough; `grpcurl` and reflection help but are an extra step for every on-call engineer.
- **API Management policies** that inspect bodies (quota by field, content rewriting) need the Protobuf descriptors. The token-quota approach from the [APIM chargeback post]({% post_url AI/2026-10-05-enterprise-ai-apim-token-quotas-chargeback-azure-openai %}) worked because the body was JSON.

## The decision rule I now use

- Service-to-service, payloads over 1 KB, p99 in the SLO: gRPC, and the migration pays back in a quarter.
- Public or browser-facing API: REST JSON, with Minimal APIs rather than controllers and source-generated serializers.
- Mixed: gRPC internally and a thin REST facade, which is what ASP.NET Core's gRPC JSON transcoding gives you for free.

The benchmark harness (Dockerfiles for all four servers, the `.proto`, and the `wrk`/`ghz` scripts) is the same layout as in the earlier hot-loop post, so you can rerun it on your own hardware before anyone rewrites anything.

## Related

- [Python vs Rust in a Hot Loop: What 10 Million Iterations Cost, Measured with hyperfine]({% post_url Performance/2026-10-07-python-vs-rust-hot-loop-performance %}) - same measurement discipline, applied to a CPU-bound loop.
- [System.Text.Json Source Generators vs Newtonsoft.Json: A BenchmarkDotNet Comparison on .NET 8]({% post_url Performance/2026-10-06-dotnet-json-serialization-performance %}) - why source-generated System.Text.Json is the REST baseline here.
- [Node.js 22 vs Deno 2 vs Bun 1.1: HTTP JSON API Throughput, Measured with wrk]({% post_url Performance/2026-10-04-node-vs-deno-vs-bun-http-performance %}) - the JavaScript side of the HTTP throughput question.
- [Cutting .NET Allocations with Span<T> and Memory<T>: Before/After BenchmarkDotNet Numbers]({% post_url Performance/2026-10-03-span-memory-allocation-reduction-dotnet %}) - the allocation work that keeps the .NET JSON path close to Go.
- [Enterprise AI: Per-Team Token Quotas and Chargeback for Azure OpenAI with Azure API Management]({% post_url AI/2026-10-05-enterprise-ai-apim-token-quotas-chargeback-azure-openai %}) - the gateway policies that assume JSON bodies.
- [Regex Engine Performance: Rust regex vs Go regexp vs .NET 8 Regex vs Node 22, Measured with hyperfine]({% post_url Performance/2026-10-15-regex-engine-performance-rust-go-dotnet-node %}) - the other place where Go's standard library trails .NET on throughput, for the same engine-design reasons.
- [Python vs Go for a Batch Log-Processing Job: Wall Time, Memory, Lines of Code and the Day-Two Costs]({% post_url Languages/2026-10-20-python-vs-go-batch-log-job %}) - the batch-side view of Go's JSON decoding cost.
- [gRPC Protobuf Data Types]({% post_url 2022-03-21-GRPC-Protobuf-Data-Types %}) - the scalar and well-known type cheat-sheet for the `.proto` contract measured here, with its C# equivalents.
