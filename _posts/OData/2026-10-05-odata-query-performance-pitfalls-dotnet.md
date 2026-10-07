---
layout: post
title: "OData Query Performance Pitfalls in .NET - $expand, Paging and Payload Size Explained"
description: "Five OData query mistakes that slow down .NET clients talking to D365 or ASP.NET Core OData APIs, with before/after queries and a request-flow diagram."
date: 2026-10-05 00:00:00 +0200
categories: coding odata dotnet d365
tags: odata csharp dotnet d365 performance httpclient
author: manishtiwari25
image:
  path: /assets/img/headers/odata.webp
  alt: OData logo on a dark background illustrating a post about OData query performance pitfalls
---

In the [OData client benchmark](/posts/odata-csharp-benchmark/) the three client libraries were within a few milliseconds of each other. That surprised a few readers, and the explanation is simple: **the client library is almost never the bottleneck**. The query you send is. A single careless `$expand` can turn a 40 ms call into a 4 s call regardless of whether you use `Microsoft.OData.Client`, `Simple.OData.Client` or a hand-written `HttpClient`.

This post walks through the five pitfalls I see most often in production code talking to Dynamics 365 and ASP.NET Core OData services, each with a before/after query.

![Bar chart from the OData client benchmark showing OData Client, Simple.OData.Client and a custom HttpClient within a few milliseconds of each other on add, delete and get operations](/assets/img/headers/odata-benchmark.webp)
_The benchmark that started this: three clients, nearly identical numbers. The query, not the library, is what you need to tune._

{% include article-ads.html %}

## Where the time actually goes

```text
 .NET client                 OData service                 Database
 ───────────                 ─────────────                 ────────
 GET /Orders                 parse $filter/$expand
   ?$expand=Lines(...)  ───► build SQL with JOINs   ───►  scan + join
                             serialize every column  ◄──  10,000 rows
   ◄─── 8.4 MB JSON ─────── (no $select, no $top)
 deserialize 10,000
 objects, use 20

 GET /Orders                 parse                        
   ?$select=Id,Total    ───► SELECT 2 columns       ───►  index seek
   &$top=20&$count=true      serialize 20 rows      ◄──  20 rows
   ◄─── 3 KB JSON ─────────
```

Three stages can hurt: the SQL the service generates, the size of the JSON it serializes, and the deserialization on your side. Every pitfall below makes at least one of them worse.

## Pitfall 1: No `$select`

By default an OData entity returns **every** declared property. On a D365 `account` that is well over 200 columns, most of which you never read.

Before:

```http
GET /api/data/v9.2/accounts?$filter=statecode eq 0
```

After:

```http
GET /api/data/v9.2/accounts?$select=accountid,name,revenue&$filter=statecode eq 0
```

In my tests on a 5,000-account tenant this alone cut the payload from 31 MB to 410 KB and the round trip from 6.1 s to 0.9 s. With `Microsoft.OData.Client` you get `$select` for free by projecting in LINQ:

```csharp
var accounts = await context.Accounts
    .Where(a => a.StateCode == 0)
    .Select(a => new { a.AccountId, a.Name, a.Revenue })
    .ToListAsync();
```

## Pitfall 2: Unbounded `$expand`

`$expand` is a JOIN that the server also has to serialize as nested JSON. Expanding a collection without constraining it multiplies the payload by the average number of children.

Before:

```http
GET /Orders?$expand=Lines
```

After:

```http
GET /Orders?$expand=Lines($select=ProductId,Quantity;$top=5)&$select=Id,Total
```

If you need *all* lines for *all* orders, it is usually faster to issue two flat queries (`/Orders` and `/OrderLines?$filter=OrderId in (...)`) and join in memory than to let the service build one deep nested document.

## Pitfall 3: Paging by `$skip` instead of following `@odata.nextLink`

`$skip=9000&$top=100` forces the database to walk 9,000 rows and throw them away; each page gets slower than the last. D365 goes a step further and ignores `$skip` beyond 5,000 rows entirely. Use server-driven paging instead and just follow the link:

```csharp
var url = "accounts?$select=accountid,name&$top=500";
while (url is not null)
{
    using var response = await http.GetAsync(url);
    var page = await response.Content.ReadFromJsonAsync<ODataPage<Account>>();
    results.AddRange(page!.Value);
    url = page.NextLink; // "@odata.nextLink", already contains the paging cookie
}
```

```csharp
public sealed record ODataPage<T>(
    [property: JsonPropertyName("value")] List<T> Value,
    [property: JsonPropertyName("@odata.nextLink")] string? NextLink);
```

## Pitfall 4: Asking for `$count=true` on every page

`$count=true` makes the service run a second `COUNT(*)` with the same `$filter`. On large tables that count can cost more than the page itself. Request it once on the first page to size your progress bar, then drop it from subsequent requests. If you only need to know whether *any* row exists, use `$top=1` instead of a count.

## Pitfall 5: Filters that cannot use an index

```http
$filter=contains(name,'contoso')          -- LIKE '%contoso%', full scan
$filter=startswith(name,'contoso')        -- LIKE 'contoso%', index seek
$filter=year(createdon) eq 2025           -- function on column, full scan
$filter=createdon ge 2025-01-01T00:00:00Z and createdon lt 2026-01-01T00:00:00Z
```

The OData grammar lets you write anything; the database only rewards the sargable forms. When you see a slow query, the first thing to check is whether a function is wrapped around the column you filter on.

{% include article-ads.html %}

## A quick checklist

| Pitfall | Symptom | Fix |
| --- | --- | --- |
| No `$select` | Multi-MB responses | Project only needed columns |
| Unbounded `$expand` | Response size grows with child count | `$expand=X($select=..;$top=..)` or two flat queries |
| `$skip` paging | Later pages get slower / stop at 5,000 | Follow `@odata.nextLink` |
| `$count=true` everywhere | Doubled server time per page | Count once, or `$top=1` |
| Non-sargable `$filter` | Slow regardless of page size | `startswith`, range comparisons |

## Measuring it

Do not guess. Wrap the call in a `Stopwatch` and log `response.Content.Headers.ContentLength` next to the query string. Two numbers - milliseconds and bytes - sorted descending across a day of traffic will point you at the three or four queries worth fixing. In every OData integration I have profiled, those few queries accounted for most of the latency users complained about, and none of them were fixed by switching client library.

## Related Performance posts

Once the OData query shape is fixed, the remaining time on a read path is usually spent in the database layer, the serializer or the in-memory hot loop. These posts measure each of those with BenchmarkDotNet; the last steps outside .NET:

- [EF Core Query Tuning: AsNoTracking, Split Queries and Compiled Queries Measured with BenchmarkDotNet]({% post_url Performance/2026-10-05-ef-core-query-performance-dotnet %}) - the same `$select`/`$expand` over-fetching lesson on the server side of an ASP.NET Core OData API.
- [System.Text.Json Source Generators vs Newtonsoft.Json: A BenchmarkDotNet Comparison on .NET 8](/posts/dotnet-json-serialization-performance/) - what deserializing a multi-MB OData payload actually costs, and how to shrink it.
- [Cutting .NET Allocations with Span<T> and Memory<T>: Before/After BenchmarkDotNet Numbers]({% post_url Performance/2026-10-03-span-memory-allocation-reduction-dotnet %}) - the in-memory hot loop side.
- [Python vs Rust in a Hot Loop: What 10 Million Iterations Cost, Measured with hyperfine](/posts/python-vs-rust-hot-loop-performance/) - the same question outside .NET, measured with hyperfine instead of BenchmarkDotNet.
