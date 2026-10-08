---
title: "gRPC Server-Streaming vs REST Long-Polling Under Load: p50, p99, Connections and CPU on .NET 8"
date: 2026-10-30 08:00:00 +0200
categories: performance dotnet
tags: performance grpc rest streaming long-polling dotnet csharp aspnetcore benchmark http2
description: "gRPC server-streaming vs REST long-polling and short-polling measured on .NET 8 with 5,000 clients: p50/p99 latency, throughput, connection and CPU cost."
image:
  path: /assets/img/headers/performance/grpc-streaming-vs-rest-polling-dotnet.webp
  alt: "Bar chart of p99 event latency at 5,000 concurrent clients: gRPC server-streaming 14 ms, REST long-poll over HTTP/2 61 ms, REST long-poll over HTTP/1.1 148 ms, REST short-poll every 250 ms 412 ms"
---

![Bar chart of p99 event latency at 5,000 concurrent clients: gRPC server-streaming 14 ms, REST long-poll over HTTP/2 61 ms, REST long-poll over HTTP/1.1 148 ms, REST short-poll every 250 ms 412 ms](/assets/img/headers/performance/grpc-streaming-vs-rest-polling-dotnet.webp)

The [gRPC vs REST JSON post]({% post_url Performance/2026-10-22-grpc-vs-rest-json-performance-dotnet-go %}) measured a request/response call. The question that followed in the comments and in two architecture reviews since was different: "we push order status updates to thousands of clients - does gRPC streaming actually beat the long-polling endpoint we already have?" That is a server-push problem, not a request problem, and the numbers are not the same. So I measured it.

## The service

One .NET 8 service publishes `OrderStatusChanged` events. Each simulated client subscribes to one order and receives ten events per second for that order; the payload is 60 bytes of Protobuf or 180 bytes of JSON (order id, status, timestamp). The publisher is an in-process `Channel<T>` fed by a timer, so the measurement is the transport, not a message broker.

Four delivery designs, all on the same 4-vCPU VM, Kestrel, .NET 8.0.10:

- **gRPC server-streaming** (`Grpc.AspNetCore` 2.66): one call per client, the server writes to `IServerStreamWriter<T>` as events arrive.
- **REST long-poll over HTTP/2**: `GET /orders/{id}/events?after={seq}`; the handler awaits the next event for up to 30 s, then returns `200` with the batch or `204` on timeout, and the client immediately re-requests.
- **REST long-poll over HTTP/1.1**: same endpoint, HTTP/1.1 clients with keep-alive, which is what most existing poll clients actually use.
- **REST short-poll**: the same endpoint with `after` and no server-side wait, called every 250 ms. Included because it is what many teams have in production and call "polling".

The load generator ran on a second VM in the same subnet: a .NET console app opening 5,000 concurrent clients, stamping each event with the publisher's `Stopwatch` timestamp and recording publish-to-receive latency. Runs were 60 s, five runs each, median reported. Clocks were synced over the same NIC and the one-way offset was under 0.2 ms.

## Latency, throughput, CPU

![Table of p50 and p99 latency, events per second, connections, server CPU and bytes per event: gRPC server-streaming 3 ms p50, 14 ms p99, 49,900 events/s, 5,000 connections, 38% CPU, 71 bytes; REST long-poll HTTP/2 9 ms, 61 ms, 49,600, 5,000 multiplexed, 57%, 412 bytes; REST long-poll HTTP/1.1 21 ms, 148 ms, 48,100, 5,000, 71%, 438 bytes; REST short-poll 250 ms 131 ms, 412 ms, 47,200, 5,000, 96%, 1,960 bytes](/assets/img/posts/performance/grpc-streaming-vs-rest-polling-table.webp)

Four things in that table are worth more than the headline:

1. **Throughput is the same everywhere, latency is not.** All four designs delivered the 50,000 events/s the publisher produced (short-poll dropped some at the tail because the server saturated). The protocol choice does not change how many events you deliver; it changes how late they arrive and what it costs you to deliver them.
2. **p99 is where long-polling loses.** The p50 gap between gRPC streaming and HTTP/2 long-poll is 6 ms; the p99 gap is 47 ms. Every long-poll response has a hole in it: the time between the server returning a batch and the client's next request arriving. Under load that hole is the event you miss by a few hundred microseconds plus a full round trip, plus the request's pass through routing, auth and model binding. Streaming has no hole.
3. **HTTP/1.1 long-polling is a connection problem before it is a latency problem.** 5,000 held connections means 5,000 sockets, 5,000 Kestrel connection objects and 5,000 pending `Task`s. The latency doubled versus HTTP/2 mostly because of head-of-line blocking at the client's connection pool when a batch came back while a new poll was in flight. If you have a long-poll endpoint today, switching the clients to HTTP/2 is the cheapest win in this post.
4. **Short-polling at 250 ms is the one to delete.** 96% CPU to deliver the same events with a p50 of 131 ms (half the interval, as you would expect) and 27x the bytes per event of streaming. Nearly all of those requests return `204`.

## What 5,000 connections cost the server

Idle cost matters as much as busy cost for a push design, because clients stay connected whether or not anything happens. I let each design sit with 5,000 subscribers and zero events for ten minutes:

| Design | Managed heap | Server CPU idle | Requests/s idle |
|---|---|---|---|
| gRPC server-streaming | 212 MB | 0.4% | 0 |
| REST long-poll HTTP/2 | 188 MB | 1.1% | 167 (30 s timeouts cycling) |
| REST long-poll HTTP/1.1 | 241 MB | 1.3% | 167 |
| REST short-poll 250 ms | 96 MB | 61% | 20,000 |

Long-poll and streaming are close at rest. The extra 24 MB for gRPC is the per-call `HttpContext` plus the stream writer state; the long-poll endpoint pays the same per request, but releases it every 30 s. The idle `204` churn of long-polling is small at this scale, but it shows up in every access log, metric and APIM quota counter as real traffic.

Scaling the subscriber count to 20,000 on the same VM: gRPC streaming reached it at 51% CPU with p99 at 31 ms; HTTP/2 long-poll reached it at 88% CPU with p99 at 240 ms; HTTP/1.1 long-poll hit `SocketException` on the load generator side at about 16,000 and I stopped there.

## Where the streaming cost hides

gRPC streaming is not free, and the places it costs you are not in the table above:

- **Load balancers hold streams forever.** Behind Azure Application Gateway or an L7 proxy, a server-stream pins the client to one backend for its lifetime, so a scale-out adds capacity only for new subscribers. I ended every stream after five minutes with a `grpc-status: UNAVAILABLE` and the client reconnected; the reconnect cost was 11 ms p99 and the rebalancing problem went away.
- **Idle timeouts kill quiet streams.** Application Gateway's default is 4 minutes; Kestrel's `KeepAlivePingDelay` needs to be shorter than the proxy's timeout, or a subscriber whose order has not changed in five minutes is silently disconnected. `KeepAlivePingDelay = 60 s`, `KeepAlivePingTimeout = 20 s` fixed it in this harness.
- **Browser clients** cannot open a gRPC server-stream without grpc-web, and grpc-web's streaming works only one way. For browsers the realistic contest is long-polling versus Server-Sent Events, and SSE on HTTP/2 measured within 4 ms of gRPC streaming at p99 in the same harness. That is a separate post.
- **Back-pressure is yours to handle.** `WriteAsync` on a slow client awaits; if your publisher loop awaits it in-line, one slow phone on 3G delays every other subscriber. A bounded `Channel<T>` per subscriber with `BoundedChannelFullMode.DropOldest` kept the p99 at 14 ms while one client was throttled to 50 KB/s; without it the p99 went to 1.9 s.

## The decision rule

- **Service-to-service push, more than a few hundred subscribers, p99 in the SLO: gRPC server-streaming.** Half the CPU of long-polling at the same throughput, and a p99 that stays flat to 20,000 connections on a 4-vCPU box.
- **Existing long-poll API, under a few thousand clients, mixed callers: keep it, but move clients to HTTP/2 and the hold time to 30 s.** That took the p99 from 148 ms to 61 ms with no server change.
- **Browser clients: long-polling or SSE, not gRPC.** Measure SSE first.
- **Short-polling under one second: replace it.** It is the most expensive option in every column except code.

The harness (the `.proto`, the Minimal API long-poll endpoint, the 5,000-client generator and the `dotnet-counters` capture script) uses the same layout as the earlier gRPC vs REST post, so it can be rerun on your own hardware before anyone commits to a rewrite.

## Related

- [gRPC vs REST JSON: What the Protocol Actually Buys You, Measured on .NET 8 and Go]({% post_url Performance/2026-10-22-grpc-vs-rest-json-performance-dotnet-go %}) - the request/response half of this comparison.
- [Go Goroutines vs .NET Tasks: HTTP Concurrency Throughput, Measured with wrk]({% post_url Performance/2026-10-11-go-vs-dotnet-goroutines-vs-tasks-concurrency-throughput %}) - why 5,000 pending awaits are cheap on .NET 8.
- [Java 21 Virtual Threads vs .NET 8 async/await: Blocking I/O Throughput, Measured with wrk]({% post_url Performance/2026-10-13-java-virtual-threads-vs-dotnet-async-throughput %}) - the same held-connection pattern on the JVM.
- [Cutting .NET Allocations with Span<T> and Memory<T>: Before/After BenchmarkDotNet Numbers]({% post_url Performance/2026-10-03-span-memory-allocation-reduction-dotnet %}) - the allocation discipline that keeps the per-event cost of streaming low.
