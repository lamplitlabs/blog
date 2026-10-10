---
layout: post
title: "pg vs Prisma vs Drizzle: PostgreSQL Driver Latency from Node.js 22, Measured with autocannon"
date: 2026-10-08 00:00:00 +0200
categories: performance javascript
tags: nodejs postgresql prisma drizzle pg typescript performance benchmark autocannon
author: manishtiwari25
description: "Runtime choice barely matters once a database is in the path. pg, Drizzle and Prisma on the same Node.js 22 query: p99 from 4.8 ms to 9.7 ms."
image:
  path: /assets/img/headers/performance/pg-vs-prisma-vs-drizzle-latency.webp
  alt: "Bar chart of p99 latency for a primary-key SELECT from Node.js 22: pg raw SQL 4.8 ms, Drizzle ORM 5.4 ms, Prisma 9.7 ms"
---

The [Node vs Deno vs Bun post]({% post_url Performance/2026-10-04-node-vs-deno-vs-bun-http-performance %}) ended with the result I found most useful: adding a 2 ms simulated database await to every request shrank the 3x runtime gap to about 20%. Most of our services are exactly that shape, an HTTP handler that waits on PostgreSQL and returns JSON. So if the runtime is not where the time goes in an I/O-bound service, where does it go? This post keeps the runtime fixed (Node.js 22) and swaps the one thing most teams actually argue about: the data-access layer.

Three candidates, all talking to the same PostgreSQL 16 through the same connection pool: the raw [`pg`](https://node-postgres.com/) driver, [Drizzle ORM](https://orm.drizzle.team/) (a typed query builder that compiles to SQL and runs it through `pg`), and [Prisma](https://www.prisma.io/) (a schema-first ORM with a separate Rust query engine process).

![Bar chart of p99 latency for a primary-key SELECT from Node.js 22 across pg, Drizzle and Prisma](/assets/img/headers/performance/pg-vs-prisma-vs-drizzle-latency.webp){: width="1200" height="630" }

## The query

The endpoint is the same `GET /users/:id` as last time, except the record now lives in a `users` table with 1 million rows, a primary key on `id`, and the same 1.2 KB JSON shape (name, email, a JSONB address, a `text[]` of roles). One round trip, one row, by primary key: the most common query in any CRUD service and the one where the driver's overhead is the largest share of the total.

**1. `pg` 8.13, raw SQL with a parameterised statement.**

```js
// pg.mjs
import pg from "pg";
const pool = new pg.Pool({ connectionString: process.env.DATABASE_URL, max: 20 });
const sql = "select id, name, email, address, roles from users where id = $1";

export async function getUser(id) {
  const { rows } = await pool.query({ text: sql, values: [id], name: "user-by-id" });
  return rows[0] ?? null;
}
```

The `name` property turns it into a prepared statement, so PostgreSQL parses and plans it once per connection.

**2. Drizzle 0.36 over the same `pg` pool.**

```ts
// drizzle.ts
import { drizzle } from "drizzle-orm/node-postgres";
import { eq, sql } from "drizzle-orm";
import { users } from "./schema.ts";
import { pool } from "./pool.ts";

const db = drizzle(pool);
const byId = db.select().from(users).where(eq(users.id, sql.placeholder("id"))).prepare("user-by-id");

export async function getUser(id: number) {
  const rows = await byId.execute({ id });
  return rows[0] ?? null;
}
```

**3. Prisma 5.21 with the default query engine.**

```ts
// prisma.ts
import { PrismaClient } from "@prisma/client";
const prisma = new PrismaClient();

export async function getUser(id: number) {
  return prisma.user.findUnique({ where: { id } });
}
```

All three are served by the same Fastify 5 app with a response schema, since the previous post showed that is the cheapest win on Node and I did not want the JSON encoder to be the variable.

## Method

- Machine: MacBook Pro, M2 Pro, 32 GB, macOS 15. PostgreSQL 16.4 in Docker on the same machine with `shared_buffers=2GB`; the whole table fits in cache, so this measures driver and protocol overhead, not disk.
- Versions: Node.js 22.9.0, Fastify 5.0.0, `pg` 8.13.0, Drizzle 0.36.0, Prisma 5.21.1.
- Pool: 20 connections for `pg` and Drizzle; Prisma's `connection_limit=20` to match.
- Load generator: [autocannon](https://github.com/mcollina/autocannon) 7.15, `-c 256 -d 30`, three runs each after a 10 s warm-up, median reported. Random `id` between 1 and 1,000,000 per request.
- Single Node process, no cluster mode, same as last time.

Here is the raw autocannon output:

![Terminal screenshot of autocannon output for the pg, Drizzle and Prisma servers showing 47,812, 44,106 and 27,941 requests per second with p99 latency of 4.8 ms, 5.4 ms and 9.7 ms](/assets/img/posts/performance/pg-prisma-drizzle-autocannon-output.webp){: width="1200" height="604" }

## Results

| Data-access layer        | Requests/sec | p50 latency | p99 latency | Peak RSS |
| ------------------------ | -----------: | ----------: | ----------: | -------: |
| `pg` raw SQL (prepared)  |       47,812 |     2.0 ms  |     4.8 ms  |  121 MB  |
| Drizzle 0.36             |       44,106 |     2.0 ms  |     5.4 ms  |  134 MB  |
| Prisma 5.21              |       27,941 |     4.0 ms  |     9.7 ms  |  212 MB  |

**Drizzle costs 8% over raw `pg`.** That is the price of building the query object and mapping rows into typed objects, and it is the same on p50. For full type safety on every query that is a very good deal, and with `.prepare()` the SQL text is generated once, so the gap does not grow with query complexity.

**Prisma is 2x the latency of `pg` on this query.** The engine runs as a separate process, so every query is Node → engine over a local socket → PostgreSQL → engine → Node, with the result serialised to JSON twice. `findUnique` is also batched through a DataLoader-style queue, which helps for N+1 patterns but adds a tick of event-loop delay to a single lookup. The 90 MB of extra RSS is the engine.

**The runtime gap is gone.** Put these numbers next to the 2 ms-await variant from the last post: moving from Node to Bun bought about 20% there. Moving from Prisma to `pg` or Drizzle buys 60-70% more throughput and halves p99, on the runtime you already run. If your service talks to a database, this is the layer to look at first.

## What moved the number, and what did not

- **Prisma with `relationMode = "prisma"` and the new `driverAdapters` preview** (Prisma over the `pg` driver instead of its own connection handling): 31,400 req/s, p99 8.1 ms. Better, still the engine round trip.
- **Dropping the prepared statement from `pg`** (plain `pool.query(text, values)`): 43,900 req/s. Parse and plan on every call costs about 8%, roughly the same as Drizzle's whole overhead. Name your hot queries.
- **Pool size 20 → 50**: no change for any of the three. With 8 cores and a cached table, PostgreSQL was not the bottleneck; the Node process was.
- **Pool size 20 → 5**: p99 went to 12-18 ms for all three because requests queued for a connection. Too small a pool looks exactly like a slow ORM in your dashboards; check `pool.waitingCount` before blaming the library.
- **Selecting all 14 columns instead of the 5 the endpoint returns**: +0.4 ms p99 across the board. `select *` is a small, steady tax.

## When each step is worth it

1. **Already on Prisma and p99 is fine?** Leave it. The schema tooling and migrations are good, and 9.7 ms is well under most SLOs. This only matters for the hot endpoints.
2. **Hot endpoint on Prisma?** Move that one query to `prisma.$queryRaw` or to Drizzle sharing the same database; you do not have to migrate the whole app. That is where the 2x lives.
3. **Starting a new service?** Drizzle over `pg` gives you typed queries at 8% over raw SQL, and the escape hatch to `pg` is the same pool object.
4. **Any of the above?** Prepare your hot statements, size the pool against real concurrency, and select only the columns you return. Those three together were worth more than any runtime change in the previous post.

## Reproduce it

```bash
docker run -d --name pg16 -e POSTGRES_PASSWORD=pw -p 5432:5432 postgres:16
psql postgres://postgres:pw@127.0.0.1/postgres -f seed-users.sql   # 1M rows

export DATABASE_URL=postgres://postgres:pw@127.0.0.1/postgres
node server.mjs --driver pg &      # or --driver drizzle / --driver prisma
autocannon -c 256 -d 30 http://127.0.0.1:3000/users/42
```

Run each three times and keep the median. Absolute numbers depend on the machine and on whether PostgreSQL is local or across a network hop; on a remote database the fixed network latency narrows the ratios but the ordering, and the pool-size lesson, stayed the same on every setup I tried.

## Related Performance posts

The database driver is one layer in the request path; these posts measure the others with the same discipline:

- [EF Core Query Tuning: AsNoTracking, Split Queries and Compiled Queries Measured with BenchmarkDotNet]({% post_url Performance/2026-10-05-ef-core-query-performance-dotnet %}) - the same "pool and query shape beat runtime choice" lesson, measured on .NET against the same kind of database round trip.
- [Node vs Deno vs Bun: HTTP Server Performance Under Load]({% post_url Performance/2026-10-04-node-vs-deno-vs-bun-http-performance %}) - the HTTP layer this driver benchmark sits behind, measured with the same autocannon workflow.
- {% include series-link.html post="Performance/2026-10-11-go-vs-dotnet-goroutines-vs-tasks-concurrency-throughput" title="Go Goroutines vs .NET Tasks: HTTP Concurrency Throughput, Measured with wrk" note=" - what the same kind of pooled-connection concurrency question looks like outside Node.js." %}
