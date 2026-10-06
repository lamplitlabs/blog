---
layout: post
title: "Java 21 Virtual Threads vs .NET 8 async/await: Blocking I/O Throughput, Measured with wrk"
date: 2026-10-13 09:00:00 -0500
categories: performance java
tags: java dotnet go performance benchmark wrk virtual-threads async-await concurrency
author: manishtiwari25
description: "A 20 ms downstream wait behind 1,000 connections: Java platform threads 9,850 req/s, virtual threads 47,300, .NET 8 async/await 48,600, Go 49,400."
image:
  path: /assets/img/headers/performance/java-virtual-threads-vs-dotnet-async.webp
  alt: "Bar chart of requests per second at 1,000 connections with a 20 ms wait: Java platform threads 9,850, Java virtual threads on Tomcat 47,300 and Helidon 49,100, .NET sync-over-async 4,120, .NET async/await 48,600, Go goroutines 49,400"
  lqip: "data:image/webp;base64,UklGRlYAAABXRUJQVlA4IEoAAABQAwCdASoUAAsALvmczmclLy8vDwD4SyAF2AId/Dwa/QwkAAD+6MvmFw4L/gYTrErvdlqOGLWE4RoFrpuiNTux2VXZpIPlgDgAAA=="
---

The [Go vs .NET concurrency post]({% post_url Performance/2026-10-11-go-vs-dotnet-goroutines-vs-tasks-concurrency-throughput %}) compared two runtimes that both solved blocking I/O years ago: goroutines on one side, `async`/`await` on the other. Java took a different route. JDK 21 shipped virtual threads (JEP 444), which keep the plain blocking `InputStream.read()` / `JDBC` style of code but park a cheap user-mode thread instead of an OS thread. The pitch is "Go-like scaling without rewriting to async". This post checks that pitch against .NET 8's `async`/`await` and Go's `net/http` on the same workload.

The workload is deliberately boring: an HTTP endpoint that waits 20 ms on a downstream call (a stub service on localhost that sleeps 20 ms before answering) and returns 140 bytes of JSON. Nothing is CPU-bound, so the only thing being measured is how each runtime handles 1,000 connections that are each blocked most of the time. With 1,000 connections and a 20 ms wait the theoretical ceiling is 1,000 / 0.020 s = **50,000 req/s**; a runtime that gets close is not wasting threads.

![Bar chart of requests per second for Java platform threads, Java virtual threads, .NET sync-over-async, .NET async/await and Go goroutines at 1,000 connections](/assets/img/headers/performance/java-virtual-threads-vs-dotnet-async.webp)

{% include feed-ads.html %}

## The six servers

**Java 21, platform threads (Tomcat, default pool).** Spring Boot 3.3 with `server.tomcat.threads.max=200` (the default). The handler calls the downstream with `HttpClient.send(...)`, which blocks the Tomcat worker thread.

```java
@GetMapping("/wait")
String wait() throws Exception {
    var res = client.send(HttpRequest.newBuilder(DOWNSTREAM).build(), BodyHandlers.ofString());
    return res.body();
}
```

**Java 21, virtual threads (Tomcat).** Same code, one property: `spring.threads.virtual.enabled=true`. Tomcat now runs each request on a virtual thread; the blocking `send` parks the virtual thread and frees the carrier.

**Java 21, virtual threads (Helidon 4).** Helidon 4's Níma server was built for virtual threads from the start, included to see whether a framework designed around them beats a retrofitted one.

**.NET 8, sync-over-async (Kestrel).** The anti-pattern, on purpose: `client.GetStringAsync(url).Result` inside a synchronous minimal API handler. This is the .NET equivalent of the Tomcat platform-thread row, and it is in the chart because a lot of production code still does this.

**.NET 8, async/await (Kestrel).**

```csharp
app.MapGet("/wait", async (HttpClient client) => await client.GetStringAsync(Downstream));
```

**Go 1.23, goroutines (net/http).** `http.Get(downstream)` in the handler; net/http gives every connection its own goroutine.

## Results

`wrk -t8 -c1000 -d30s --latency`, three runs each, median shown. Downstream stub is Go, pinned to its own cores, and never showed above 4% CPU.

| Server | req/s | p50 | p99 | Threads (OS) | RSS |
|---|---:|---:|---:|---:|---:|
| Java 21 platform threads, Tomcat 200 pool | 9,850 | 101.2 ms | 142.7 ms | 231 | 412 MB |
| Java 21 virtual threads, Tomcat | 47,300 | 20.9 ms | 31.8 ms | 27 | 388 MB |
| Java 21 virtual threads, Helidon 4 | 49,100 | 20.4 ms | 24.1 ms | 21 | 196 MB |
| .NET 8 sync-over-async, Kestrel | 4,120 | 218.6 ms | 1,420 ms | 312 | 240 MB |
| .NET 8 async/await, Kestrel | 48,600 | 20.6 ms | 27.4 ms | 19 | 118 MB |
| Go 1.23 goroutines, net/http | 49,400 | 20.3 ms | 23.6 ms | 12 | 41 MB |

![wrk output for the Java platform-thread, Java virtual-thread and .NET async/await servers showing 9,850, 47,303 and 48,604 requests per second](/assets/img/posts/performance/java-virtual-threads-wrk-output.webp)

### What the rows mean

**Platform threads are capped by the pool, exactly as the arithmetic predicts.** 200 threads / 0.020 s = 10,000 req/s, and Tomcat delivered 9,850. The p50 of 101 ms is not the downstream being slow; it is 800 of the 1,000 connections queueing for a worker. Raising `threads.max` to 1,000 pushed throughput to 46,900 req/s but RSS to 1.1 GB and the OS thread count to 1,031, and it falls over again at 2,000 connections. The pool is the limit, and the pool is sized by hand.

**Virtual threads remove the cap without touching the handler.** One property moved Tomcat from 9,850 to 47,300 req/s with 27 OS threads. The remaining gap to Helidon (49,100) and to .NET async (48,600) came from Tomcat's connector doing its own accept/poll work on platform threads; Helidon, which has no such layer, matched Go within 1%.

**Sync-over-async in .NET is worse than Java's platform threads.** 4,120 req/s and a 1.4 s p99. The thread pool injects at most a couple of threads per second when it detects starvation, so under 1,000 blocked connections it spends most of the 30 s window growing the pool, and each blocked thread also pins a `Task` continuation that cannot run until the pool catches up. Java's fixed 200-thread pool is at least predictable; .NET's starvation recovery is not. If a service has `.Result` or `.Wait()` on an I/O call in a hot path, this is the row it is on.

**async/await, virtual threads and goroutines land in the same place.** 47,300 to 49,400 req/s, 20 to 21 ms p50, all within 6% of the 50,000 ceiling. At this workload the programming model does not decide throughput; whether a blocked request holds an OS thread does.

**Memory is where they differ.** Go at 41 MB, .NET at 118 MB, Helidon at 196 MB and Tomcat at 388 MB are all serving the same 1,000 connections. The JVM numbers are dominated by heap sizing (`-Xmx` was left at the 25% default); with `-Xmx256m` Tomcat-virtual ran at 262 MB with no throughput change. Virtual threads themselves cost about 1 KB each here, so they are not the memory story; the runtime baseline is.

## Where virtual threads still lose

Two things showed up while running this that the summary table hides:

1. **Pinning.** A `synchronized` block around the downstream call (common in older client libraries) pins the virtual thread to its carrier for the duration of the block. With `-Djdk.tracePinnedThreads=full` and a deliberately `synchronized` handler, throughput fell to 11,400 req/s, close to the platform-thread row. `ReentrantLock` instead of `synchronized` restores it. JDK 24 removes this limitation (JEP 491), but JDK 21 LTS has it.
2. **CPU-bound work does not benefit.** Replacing the 20 ms wait with 20 ms of SHA-256 hashing gave 395 to 410 req/s on every server (8 cores / 0.020 s = 400). Virtual threads, `async`/`await` and goroutines are all about waiting cheaply; none of them makes computation faster.

## What to take from it

- If a Java service is on JDK 21 and its pool size is the bottleneck, `spring.threads.virtual.enabled=true` (or the equivalent executor) is a one-line change worth measuring before any rewrite to reactive.
- If a .NET service has sync-over-async on an I/O path, fixing that is worth more than any runtime upgrade: 4,120 to 48,600 req/s on this workload.
- Once blocking no longer holds OS threads, Java, .NET and Go are within a few percent of each other on I/O-bound throughput. Pick on memory footprint, ecosystem and the team, not on this chart.

## Reproduce it

```bash
# downstream stub: Go, sleeps 20 ms and returns 140 bytes
go run ./downstream &            # :9000

# Java (Spring Boot 3.3, JDK 21.0.4)
./gradlew bootRun                                        # platform threads, :8080
SPRING_THREADS_VIRTUAL_ENABLED=true ./gradlew bootRun    # virtual threads,  :8081
# .NET 8 (SDK 8.0.401)
dotnet run -c Release --project WaitApi                  # :5000
# Go 1.23
go run ./waitgo                                          # :8082

wrk -t8 -c1000 -d30s --latency http://localhost:8080/wait
```

Numbers above are from an Apple M2 (8 cores), macOS 14.6, `ulimit -n 65536`, JDK 21.0.4 (Temurin), Spring Boot 3.3.4, Helidon 4.1.1, .NET 8.0.8, Go 1.23.1, wrk 4.2.0. Servers and the downstream stub ran on the same machine; the stub's 20 ms sleep was verified at 20.1 ms p50 with `wrk -c1` before each run.

## Related Performance posts

- [Go Goroutines vs .NET Tasks]({% post_url Performance/2026-10-11-go-vs-dotnet-goroutines-vs-tasks-concurrency-throughput %}) - the same two runtimes on a CPU-and-I/O mixed workload.
- [Node.js 22 vs Deno 2 vs Bun 1.1]({% post_url Performance/2026-10-04-node-vs-deno-vs-bun-http-performance %}) - the single-threaded event-loop answer to the same question.
- [In-Process Cache vs Redis in .NET 8]({% post_url Performance/2026-10-12-dotnet-cache-latency-memory-vs-redis-hybridcache %}) - what the 20 ms downstream wait costs once it is a cache instead of a service.
