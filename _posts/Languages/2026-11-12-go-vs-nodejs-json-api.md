---
layout: post
title: "Go vs Node.js for a Small JSON API: 4-6x Throughput, 6x Less Memory, and What Node Still Wins"
description: "Go 1.27 vs Node.js 24 serving the same 50-item JSON endpoint under 64 connections: req/s, p50/p99 latency, resident memory and build step measured on a laptop."
date: 2026-11-12 00:00:00 +0200
categories: languages go nodejs
tags: go nodejs performance benchmark api json latency memory
author: manishtiwari25
image:
  path: /assets/img/headers/languages/go-vs-node-json-api.webp
  alt: "Bar chart comparing Go 1.27 and Node.js 24 serving the same JSON API with 64 connections: 9,400 vs 2,000 requests per second, p50 latency 2.4 vs 12.2 ms, p99 latency 85 vs 196 ms, resident memory 10 vs 61 MB"
---

Earlier posts in this series compared [Rust against Go]({% post_url Languages/2026-10-16-rust-vs-go-cli-tool %}) for a command-line tool and [TypeScript against Kotlin]({% post_url Languages/2026-10-14-typescript-vs-kotlin-backend-services %}) for backend services. This one takes the most common backend question I get from teams that already run Node.js: if we wrote the next small internal API in Go instead, what would we actually gain, and what would we give up? Rather than argue from reputation, I wrote the same endpoint twice and measured it on one machine.

## The workload

The endpoint is deliberately boring, because most internal APIs are: `GET /items?page=N` returns a page of 50 items, each with an id, a name, a price and a three-element tag list, plus a timestamp. The response is about 3.2 KB of JSON. There is no database, so the numbers isolate the HTTP stack and JSON encoding of each runtime rather than measuring Postgres.

The Go version uses only the standard library, `net/http` and `encoding/json`, in 24 lines. The Node.js version uses the built-in `http` module and `JSON.stringify` in 9 lines. No frameworks on either side; adding Express or Gin would shift the absolute numbers but not the ratio much, and the point is to compare the runtimes.

```go
func main() {
    http.HandleFunc("/items", func(w http.ResponseWriter, r *http.Request) {
        p, _ := strconv.Atoi(r.URL.Query().Get("page"))
        items := make([]Item, 50)
        for i := range items {
            items[i] = Item{ID: p*50 + i, Name: "item-" + strconv.Itoa(p*50+i),
                Price: float64(i) * 1.25, Tags: []string{"a", "b", "c"}}
        }
        w.Header().Set("Content-Type", "application/json")
        json.NewEncoder(w).Encode(Resp{Page: p, Items: items,
            Generated: time.Now().UTC().Format(time.RFC3339)})
    })
    http.ListenAndServe(":8081", nil)
}
```

```js
const http = require('http');
http.createServer((req, res) => {
  const u = new URL(req.url, 'http://x');
  const p = parseInt(u.searchParams.get('page') || '0');
  const items = [];
  for (let i = 0; i < 50; i++)
    items.push({ id: p * 50 + i, name: 'item-' + (p * 50 + i), price: i * 1.25, tags: ['a', 'b', 'c'] });
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify({ page: p, items, generated: new Date().toISOString() }));
}).listen(8082);
```

## How it was measured

- Machine: Apple M-series laptop, macOS 26, nothing else running in the foreground.
- Versions: Go 1.27.1, Node.js 24.
- Load generator: a small Go program opening 64 keep-alive connections and hammering the endpoint for 10 seconds, recording every request latency. I ran it twice against each server, back to back, and report both runs rather than the best one.
- Memory: resident set size of the server process read with `ps` while the load was running.
- Build: `go build -ldflags="-s -w"` timed with `time`; Node has no build step.

A single laptop is not a production fleet, and the load generator shares the CPU with the server, which caps both. Treat the ratios as the finding, not the absolute numbers.

## Results

![Table comparing Go 1.27 and Node.js 24 serving the same 50-item JSON endpoint with 64 keep-alive connections: throughput 9,678 vs 1,591 req/s in run 1 and 9,081 vs 2,371 req/s in run 2, p50 latency 2.3-2.6 vs 8.4-15.9 ms, p99 latency 72-98 vs 172-221 ms, p99.9 latency 165-177 vs 267-302 ms, resident memory 9.7 vs 61 MB, Go build 0.29 s producing a 6.2 MB static binary versus no build step for Node, 24 vs 9 lines of code](/assets/img/posts/languages/go-vs-node-json-api-results-table.webp)

| Metric | Go 1.27 | Node.js 24 | Ratio |
|---|---|---|---|
| Throughput, run 1 | 9,678 req/s | 1,591 req/s | 6.1x |
| Throughput, run 2 | 9,081 req/s | 2,371 req/s | 3.8x |
| p50 latency | 2.3-2.6 ms | 8.4-15.9 ms | 3.3-6.9x |
| p99 latency | 72-98 ms | 172-221 ms | 2.2-3.1x |
| p99.9 latency | 165-177 ms | 267-302 ms | 1.7x |
| Resident memory under load | 9.7 MB | 61 MB | 6.3x |
| Build step | 0.29 s, 6.2 MB static binary | none | - |
| Lines of code | 24 | 9 | - |

Three things stand out.

**Throughput and median latency are a 4-6x gap, and it is structural.** Go serves each connection on its own goroutine across all cores; the single Node process runs JavaScript on one thread, so with 64 concurrent connections the requests queue behind each other. Node's second run was noticeably faster than its first because V8 had finished optimising the hot path, which is why I report both. You can close part of the gap by running Node under `cluster` with one worker per core, but then you also multiply the memory figure by the worker count.

**Tail latency is closer than the median suggests.** At p99.9 the ratio drops to about 1.7x. Both runtimes are paying for garbage collection pauses and for the load generator competing for the same CPU. If your SLO is written against the tail rather than the median, Go helps less than the headline number implies.

**Memory is the quiet win.** The Go server sat at under 10 MB resident while saturated; Node sat at 61 MB. For one service that is irrelevant. For a platform team running two hundred small internal APIs on shared Kubernetes nodes, a 50 MB per-pod difference is the difference between fitting on the current node pool and ordering more.

## What Node.js still wins

The table is one-sided on performance, so it is worth being explicit about where Node earned its place.

- **No build, instant iteration.** The Go binary took 0.29 s to build, which is fast, but it is still a step, and a cross-compile matrix for Linux containers is real work the first time. Node runs the file you just saved.
- **Shared language with the frontend.** If the same team owns a React or Angular app, the types, validation schemas and tooling carry across. That was the whole argument of the [TypeScript vs Kotlin]({% post_url Languages/2026-10-14-typescript-vs-kotlin-backend-services %}) post and it still holds here.
- **Ecosystem breadth for glue.** Talking to a SaaS API, signing a JWT, rendering an email template: the npm package usually exists and is usually the vendor's official one. Go's standard library is excellent, but third-party coverage is thinner.
- **Less code for the same thing.** 9 lines versus 24. In a real service the ratio shrinks, but Go's explicit structs and error handling never go away.

## When to pick which

Pick Go when the service is on a hot path, when you run many small services and pay for memory, or when a static binary in a `FROM scratch` container simplifies the deploy. Pick Node.js when the service is mostly orchestration and glue, when the team is already a TypeScript team, or when iteration speed on a low-traffic endpoint matters more than throughput you will never use.

Neither answer is wrong. What is wrong is choosing on reputation. Both servers here are small enough to rewrite in an afternoon against your own workload; the numbers you get on your hardware with your payload will be more persuasive than mine.

## Related

- [Rust vs Go for a CLI tool]({% post_url Languages/2026-10-16-rust-vs-go-cli-tool %}): the same measured approach applied to a command-line workload.
- [TypeScript vs Kotlin for backend services]({% post_url Languages/2026-10-14-typescript-vs-kotlin-backend-services %}): the team-and-ecosystem side of the Node.js argument.
- [Python vs Go for a batch log job]({% post_url Languages/2026-10-20-python-vs-go-batch-log-job %}): Go against another dynamic runtime, on a throughput-bound job.
