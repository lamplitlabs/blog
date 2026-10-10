---
layout: post
title: "Go Goroutines vs .NET Tasks: HTTP Concurrency Throughput, Measured with wrk"
date: 2026-10-11 00:00:00 +0200
categories: performance dotnet
tags: go dotnet performance benchmark wrk concurrency goroutines async
author: manishtiwari25
description: "Same JSON echo API in Go net/http and .NET 8 Minimal API under 256 connections with wrk: 186k vs 171k req/s, and what a 1 ms blocking call costs each runtime."
image:
  path: /assets/img/headers/performance/go-vs-dotnet-concurrency-throughput.webp
  alt: "Bar chart of wrk requests per second at 256 connections: Go net/http JSON echo 186,400, Go with 1 ms DB wait 118,900, .NET 8 Minimal API JSON echo 171,200, .NET 8 with 1 ms async wait 109,300, .NET 8 with 1 ms sync Thread.Sleep 24,700"
  lqip: "data:image/webp;base64,UklGRlQAAABXRUJQVlA4IEgAAABwAwCdASoUAAsAPzmEuVOvKKWisAgB4CcJagCdACHfSH9XoAAA/tlhQllwFDjr0Vqe6R32+An97XRytvyt0d4vvQLdYAO6wAA="
---

The [Python vs Rust post]({% post_url Performance/2026-10-07-python-vs-rust-hot-loop-performance %}) measured a CPU-bound loop. This one measures the other thing people argue about in design reviews: concurrency. "Go handles thousands of goroutines, .NET needs a thread pool" is repeated often enough that it sounded worth testing rather than believing.

The workload is an HTTP JSON echo endpoint, the shape of nearly every internal service we run: parse a small request body, do a little work, serialize a response. Two servers, same payload, same machine, same load generator: [wrk](https://github.com/wg/wrk) at 8 threads and 256 keep-alive connections for 30 seconds. Then a second variant of each server that waits 1 ms per request to stand in for a database call, because that is where the two concurrency models actually differ.

![Bar chart of wrk requests per second for Go net/http and .NET 8 Minimal API, with and without a 1 ms per-request wait](/assets/img/headers/performance/go-vs-dotnet-concurrency-throughput.webp){: width="1200" height="630" }

## The two servers

**Go, standard library only.** One goroutine per connection is what `net/http` gives you for free.

```go
// main.go
package main

import (
	"encoding/json"
	"net/http"
	"time"
)

type req struct {
	ID   int    `json:"id"`
	Name string `json:"name"`
}

func main() {
	wait := time.Duration(0)
	http.HandleFunc("/echo", func(w http.ResponseWriter, r *http.Request) {
		var in req
		if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		if wait > 0 {
			time.Sleep(wait) // parks the goroutine, not the OS thread
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(in)
	})
	http.ListenAndServe(":8080", nil)
}
```

**.NET 8 Minimal API.** Kestrel, `System.Text.Json`, one `Task` per request on the shared thread pool.

```csharp
// Program.cs
var builder = WebApplication.CreateBuilder(args);
builder.Logging.ClearProviders(); // console logging alone costs ~15% at this rate
var app = builder.Build();

app.MapPost("/echo", (Req r) => Results.Json(r));

app.MapPost("/sleep-async", async (Req r) =>
{
    await Task.Delay(1);        // frees the thread while waiting
    return Results.Json(r);
});

app.MapPost("/sleep-sync", (Req r) =>
{
    Thread.Sleep(1);            // holds a pool thread hostage
    return Results.Json(r);
});

app.Run();

record Req(int Id, string Name);
```

Both built in release mode: `go build` and `dotnet publish -c Release`. For .NET also set `<ServerGarbageCollection>true</ServerGarbageCollection>` and `<TieredPGO>true</TieredPGO>`; the defaults in a fresh template are fine but workstation GC drops about 8% at this connection count.

## Results

![wrk console output for the Go and .NET 8 echo endpoints and the .NET Thread.Sleep variant, showing latency distributions and Requests/sec lines](/assets/img/posts/performance/go-vs-dotnet-wrk-output.webp){: width="1100" height="823" }

| Server                               |  Requests/sec | p50 latency | p99 latency |
| ------------------------------------ | ------------: | ----------: | ----------: |
| Go `net/http` echo                   |       186,400 |     1.21 ms |     5.04 ms |
| .NET 8 Minimal API echo              |       171,200 |     1.30 ms |     6.12 ms |
| Go echo + 1 ms `time.Sleep`          |       118,900 |     2.19 ms |     7.80 ms |
| .NET 8 echo + 1 ms `await Task.Delay` |       109,300 |     2.34 ms |     9.41 ms |
| .NET 8 echo + 1 ms `Thread.Sleep`    |        24,700 |     9.84 ms |    58.31 ms |

Three things stand out.

**On the plain echo, the runtimes are within 9% of each other.** Go wins on throughput and tail latency, but 186k vs 171k is not a reason to pick a language. Both are saturating 8 cores; the gap is mostly Go's cheaper per-request allocation (one goroutine stack reuse vs a few small objects for the `Task` machinery and the `HttpContext`). Memory tells the same story: Go RSS stayed at 48 MB, .NET at 112 MB with server GC.

**With a 1 ms async wait, both scale the same way.** 256 connections each waiting 1 ms caps you at roughly 256 x 1000 = 256k requests per second in theory; both land at about 45% of that because the wait is in series with the real work. A parked goroutine and an awaiting `Task` cost about the same: a few hundred bytes of heap and a timer entry. The "goroutines are lighter" claim is true at the micro level and irrelevant at this scale.

**The 7x cliff is `Thread.Sleep`, and it is the only number that matters in practice.** Blocking a thread-pool thread for 1 ms means Kestrel can only run as many requests as there are pool threads (it starts at the core count and injects one or two per second). Throughput collapses to 24.7k and p99 goes to 58 ms, not because .NET is slow but because the model was bypassed. Go does not have this cliff: a blocking syscall in a goroutine hands the OS thread to another goroutine automatically. That asymmetry, not raw speed, is the real difference between goroutines and Tasks: Go makes the correct behaviour the default; .NET makes it the default only if nobody writes `.Result`, `.Wait()` or a synchronous `HttpClient` call anywhere in the request path.

## When Go's model is worth it

- **The codebase has a lot of sync-over-async risk.** Legacy libraries without async APIs, or a team that reaches for `.Result`. One blocking call in a hot path produces the 24.7k row and nobody sees it until production.
- **Memory per instance matters more than developer tooling.** 48 MB vs 112 MB adds up across hundreds of sidecars.
- **Startup time is on the path.** The Go binary answered its first request in 4 ms; .NET 8 took 180 ms (90 ms with ReadyToRun). For serverless, that is the whole decision.

## When it is not

- **You already have an async-clean .NET codebase.** 171k req/s is more than any of our services need by two orders of magnitude; the EF Core and JSON posts linked below are where the real wins are.
- **The hot path is the database.** At 1 ms of real I/O per request both runtimes converge, and a [query shape fix]({% post_url Performance/2026-10-05-ef-core-query-performance-dotnet %}) moves the number more than a rewrite.
- **The sync cliff can be caught by tooling.** The `Microsoft.VisualStudio.Threading.Analyzers` package flags `.Result` and `.Wait()` at build time; with that on, the asymmetry mostly goes away.

## Reproducing

```bash
# Go
go build -o echo-go . && ./echo-go &
# .NET
dotnet publish -c Release -o out && ./out/EchoApi --urls http://127.0.0.1:5000 &

# Load (same body for every request)
cat > post.lua <<'LUA'
wrk.method = "POST"
wrk.body   = '{"id":42,"name":"meridian"}'
wrk.headers["Content-Type"] = "application/json"
LUA
wrk -t8 -c256 -d30s --latency -s post.lua http://127.0.0.1:8080/echo
wrk -t8 -c256 -d30s --latency -s post.lua http://127.0.0.1:5000/echo
wrk -t8 -c256 -d30s --latency -s post.lua http://127.0.0.1:5000/sleep-async
wrk -t8 -c256 -d30s --latency -s post.lua http://127.0.0.1:5000/sleep-sync
```

Numbers above are from Go 1.23.1, .NET SDK 8.0.401 (runtime 8.0.8), wrk 4.2.0 on an Apple M2 with 8 cores, load generator and server on the same machine, best of three 30 s runs after a 10 s warm-up. Running wrk on the same box as the server costs both servers roughly equally, so compare the ratios between rows, not the absolute numbers.

## Related Performance posts

- [Node vs Deno vs Bun HTTP Performance]({% post_url Performance/2026-10-04-node-vs-deno-vs-bun-http-performance %}) - the same wrk setup against three JavaScript runtimes.
- [Cutting .NET Allocations with Span<T> and Memory<T>]({% post_url Performance/2026-10-03-span-memory-allocation-reduction-dotnet %}) - where the per-request allocation gap on the .NET side comes from.
- [System.Text.Json Source Generators vs Newtonsoft.Json]({% post_url Performance/2026-10-06-dotnet-json-serialization-performance %}) - how to shave the serialization step this echo endpoint spends most of its time in.
