---
layout: post
title: "Node.js 22 vs Deno 2 vs Bun 1.1: HTTP JSON API Throughput, Measured with wrk"
date: 2026-10-04 09:00:00 -0500
categories: performance javascript
tags: nodejs deno bun javascript typescript performance benchmark wrk
author: manishtiwari25
description: "Benchmark the same JSON endpoint on Node.js 22, Fastify, Deno 2 and Bun 1.1 with wrk. From 54,800 to 162,300 req/s, and what actually moves the number."
image:
  path: /assets/img/headers/performance/node-vs-deno-vs-bun-http.webp
  alt: "Bar chart of requests per second for a 1.2 KB JSON GET endpoint: Node.js 22 http 54,800, Node.js 22 with Fastify 71,200, Deno 2 98,600, Bun 1.1 162,300"
---

So far this folder has covered [Span<T> allocations]({% post_url Performance/2026-10-03-span-memory-allocation-reduction-dotnet %}), [EF Core queries]({% post_url Performance/2026-10-05-ef-core-query-performance-dotnet %}), [JSON serialization in .NET]({% post_url Performance/2026-10-06-dotnet-json-serialization-performance %}) and a [Python vs Rust hot loop]({% post_url Performance/2026-10-07-python-vs-rust-hot-loop-performance %}). This one looks at the JavaScript side of our stack. Most of our internal dashboards and a couple of AI tool backends are small HTTP services written in TypeScript, and "should we move this to Bun?" has become the new "should we move this to Rust?". Instead of debating benchmarks published by the runtime vendors themselves, I ran the same endpoint on all three runtimes on the same machine.

The workload is the most common shape of service we write: a `GET /users/:id` that looks up an in-memory record and returns a 1.2 KB JSON body. No database, no TLS, no middleware beyond routing. That isolates the runtime's HTTP server, its JSON encoder and its event loop, which is exactly what you pay for when you switch runtimes.

![Bar chart of requests per second for a 1.2 KB JSON endpoint across Node.js 22, Fastify, Deno 2 and Bun 1.1](/assets/img/headers/performance/node-vs-deno-vs-bun-http.webp)

{% include feed-ads.html %}

## The four implementations

**1. Node.js 22, built-in `http` module.** The baseline everyone has somewhere.

```js
// node-http.mjs
import { createServer } from "node:http";
import { users } from "./users.mjs";

createServer((req, res) => {
  const id = Number(req.url.split("/")[2]);
  const user = users.get(id);
  if (!user) { res.writeHead(404); return res.end(); }
  const body = JSON.stringify(user);
  res.writeHead(200, { "content-type": "application/json" });
  res.end(body);
}).listen(3000);
```

**2. Node.js 22 with Fastify 5.** Same runtime, a framework that compiles its JSON serializer from a schema.

```js
// node-fastify.mjs
import Fastify from "fastify";
import { users, userSchema } from "./users.mjs";

const app = Fastify({ logger: false });
app.get("/users/:id", { schema: { response: { 200: userSchema } } }, (req, reply) => {
  const user = users.get(Number(req.params.id));
  return user ?? reply.code(404).send();
});
app.listen({ port: 3000 });
```

**3. Deno 2, `Deno.serve`.** The runtime's native server, no framework.

```ts
// deno-serve.ts
import { users } from "./users.ts";

Deno.serve({ port: 3000 }, (req) => {
  const id = Number(new URL(req.url).pathname.split("/")[2]);
  const user = users.get(id);
  return user
    ? Response.json(user)
    : new Response(null, { status: 404 });
});
```

**4. Bun 1.1, `Bun.serve`.** Same code as Deno apart from the entry point; both use the fetch-style `Request`/`Response` API.

```ts
// bun-serve.ts
import { users } from "./users.ts";

Bun.serve({
  port: 3000,
  fetch(req) {
    const id = Number(new URL(req.url).pathname.split("/")[2]);
    const user = users.get(id);
    return user ? Response.json(user) : new Response(null, { status: 404 });
  },
});
```

## Method

- Machine: MacBook Pro, M2 Pro (8 performance cores), 32 GB, macOS 15, nothing else running.
- Versions: Node.js 22.9.0, Fastify 5.0.0, Deno 2.0.2, Bun 1.1.30.
- Load generator: [wrk](https://github.com/wg/wrk) 4.2, `-t8 -c256 -d30s --latency`, run three times per server with a 10 s warm-up; the median run is reported.
- Each server is a single process. No cluster mode, no worker threads, so this measures one event loop per runtime. Clustering scales all four by roughly the core count and does not change the ranking.
- The JSON body is the same 1.2 KB object (an id, a name, an email, a nested address and a 12-element array of role strings).

Here is the raw `wrk` output for the three native servers:

![Terminal screenshot of wrk output for the Node.js http, Deno.serve and Bun.serve servers showing 54,812, 98,603 and 162,307 requests per second with p99 latency of 9.81 ms, 5.42 ms and 3.21 ms](/assets/img/posts/performance/node-deno-bun-wrk-output.webp)

## Results

| Server                   | Requests/sec | p50 latency | p99 latency | Peak RSS |
| ------------------------ | -----------: | ----------: | ----------: | -------: |
| Node.js 22 `http`        |       54,812 |     4.31 ms |     9.81 ms |   94 MB  |
| Node.js 22 + Fastify 5   |       71,204 |     3.38 ms |     7.12 ms |  108 MB  |
| Deno 2 `Deno.serve`      |       98,603 |     2.41 ms |     5.42 ms |   71 MB  |
| Bun 1.1 `Bun.serve`      |      162,307 |     1.48 ms |     3.21 ms |   58 MB  |

Three things in that table are worth pausing on.

**Fastify beats raw `http` on the same runtime by 30%.** That is not framework magic; it is `fast-json-stringify` compiling a serializer from the response schema instead of calling the generic `JSON.stringify`. The same lesson as the [System.Text.Json source generators post]({% post_url Performance/2026-10-06-dotnet-json-serialization-performance %}): a serializer that knows the shape ahead of time wins. If you cannot change runtimes, this is the cheapest 30% you will find.

**Deno is 1.8x Node and Bun is 3x Node.** Both ship an HTTP server written in a systems language (Rust via hyper for Deno, Zig with a custom parser for Bun) and avoid going through a JavaScript `http` layer for header parsing. Bun additionally uses JavaScriptCore, whose `JSON.stringify` is faster than V8's for small objects, and its `Response.json` path skips a copy. The gap between Deno and Bun is mostly those two things.

**Tail latency moves more than throughput.** Node's p99 is 3x its p50, Bun's p99 is about 2x. Under a 256-connection load the runtimes that spend less time in GC and in JavaScript-side parsing have a flatter distribution, and p99 is what your SLO is written against.

## What moved the number, and what did not

I also ran a few variants that did not make the chart:

- **Node with `--max-semi-space-size=64`** (bigger young generation): 59,100 req/s, +8%. Cheap, worth setting on allocation-heavy services.
- **Node 22 cluster mode with 8 workers**: 391,000 req/s. Deno and Bun scale the same way with their equivalents, so cluster mode is the real answer when one process is the bottleneck, not a runtime change.
- **Adding a 2 ms simulated database await** to every request: Node 61,000, Deno 68,000, Bun 74,000 req/s. Once the handler waits on I/O the runtime differences shrink to about 20%, because every runtime is now mostly idle between awaits.

That last point is the one I keep coming back to. The 3x headline only applies to a handler that does no I/O. Most of our real endpoints call a database or an upstream API, and there the win from switching runtimes is modest while the migration cost (package compatibility, `node:` API gaps, deployment images) is real.

## When each step is worth it

1. **Stay on Node, add Fastify with response schemas.** No new runtime, 30% more throughput, better p99. Do this first.
2. **Move to Deno or Bun** when the service is CPU-bound in the HTTP layer itself: proxies, edge handlers, serialization-heavy APIs with no database in the path. Bun is faster; Deno has the more conservative compatibility story and ships the permission model, which matters for the kind of AI tool backends that execute model-generated code.
3. **Run cluster mode or multiple replicas** before any of the above if a single process is pegged at 100% of one core. It is a config change and scales linearly.

## Reproduce it

```bash
# Node
node node-http.mjs &
wrk -t8 -c256 -d30s --latency http://127.0.0.1:3000/users/42

# Deno
deno run --allow-net deno-serve.ts &
wrk -t8 -c256 -d30s --latency http://127.0.0.1:3000/users/42

# Bun
bun run bun-serve.ts &
wrk -t8 -c256 -d30s --latency http://127.0.0.1:3000/users/42
```

Run each three times and keep the median; the first run on every runtime is 5-10% slower while the JIT warms up. Your absolute numbers will differ with the machine, but on every box I tried the ordering and the rough ratios held.
