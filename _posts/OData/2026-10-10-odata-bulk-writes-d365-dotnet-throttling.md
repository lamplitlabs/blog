---
layout: post
title: "Bulk Writes to D365 Over OData in .NET - Upserting 250,000 Rows Without Getting Throttled"
description: "Measured wall time for four ways to write 250,000 rows into Dynamics 365 over OData from .NET: per-row PATCH, parallel workers, $batch and return=minimal."
date: 2026-10-10 00:00:00 +0200
categories: coding odata dotnet d365
tags: odata csharp dotnet d365 performance batch throttling
author: manishtiwari25
image:
  path: /assets/img/headers/odata/odata-bulk-writes-d365.webp
  alt: Bar chart comparing wall time to write 250,000 rows to Dynamics 365 over OData - one PATCH per row at 2,110 s, 8 parallel PATCH workers at 612 s, $batch with changesets at 238 s and $batch with Prefer return=minimal at 151 s
---

The [paging post](/posts/odata-paging-strategies-large-d365-datasets-dotnet/) ended with 250,000 `SalesOrderLines` rows read out of Dynamics 365 in just over two minutes. This post is about the trip back: a nightly job that recalculates a discount column for every one of those rows and has to write the result into D365 again.

Reading is forgiving. Writing is where the service-protection limits in D365 Finance and Dataverse actually bite, because every write is a transaction, every transaction holds locks, and the platform throttles you per user the moment you look like you are trying to load a table. The job that produced the numbers below started life as a `foreach` with one `PATCH` per row and took **35 minutes**. The last version takes **two and a half**.

## The measurement

Same sandbox tenant as the paging post, same .NET 8 console client over a 12 ms RTT link, same 250,000 rows. Each row needs one `PATCH` that updates two columns (`LineDiscountPercentage`, `LineDiscountAmount`). Numbers are the median of 5 runs.

![Table comparing four write strategies for 250,000 rows: one PATCH per row sends 250,000 requests in 2,110 s with 0 throttles at 118 rows per second and 188 MB; 8 parallel PATCH workers take 612 s with 37 throttles at 408 rows per second; $batch with 100 operations per changeset sends 2,500 requests in 238 s with 4 throttles at 1,050 rows per second and 172 MB; $batch with return=minimal takes 151 s with 2 throttles at 1,655 rows per second and 96 MB](/assets/img/posts/odata/odata-bulk-writes-results-table.webp){: width="1400" height="560" }
_The per-row version never gets throttled - it is simply too slow to trigger the limit. Everything faster than it has to deal with 429s._

Three things stand out:

1. **Parallelism alone hits the wall fast.** Eight workers is a 3.4x win, but 37 of the runs' requests came back `429 Too Many Requests` with `Retry-After`, and at 12 workers the job spent more time sleeping than writing.
2. **`$batch` changes what the server counts.** D365 service-protection limits count *requests* and *execution time*, not rows. One `$batch` with 100 `PATCH` operations is one request. 2,500 requests instead of 250,000 is what buys the next 2.6x.
3. **`Prefer: return=minimal` is the cheapest line in the table.** By default a `PATCH` to D365 returns the full updated entity - here about 380 bytes of JSON per row that the job never read. Asking for `204 No Content` halves the bytes on the wire and cuts another 36% off wall time, because the server skips re-serialising the row.

## Version 1: one PATCH per row

This is what most integrations start as, and it is correct.

```csharp
foreach (var line in lines)
{
    using var req = new HttpRequestMessage(HttpMethod.Patch,
        $"data/SalesOrderLines(dataAreaId='usmf',SalesOrderNumber='{line.OrderNumber}',LineNumber={line.LineNumber})");
    req.Headers.Add("If-Match", "*");
    req.Content = JsonContent.Create(new
    {
        LineDiscountPercentage = line.DiscountPercentage,
        LineDiscountAmount = line.DiscountAmount
    });

    using var res = await http.SendAsync(req, ct);
    res.EnsureSuccessStatusCode();
}
```

Two details matter even here. `If-Match: *` tells D365 you do not care about the ETag; without it some entities reject the `PATCH` with `428 Precondition Required`. And the body only contains the two columns you are changing - sending the whole entity back makes D365 validate every field and is a common source of "I only changed the discount, why did it fail on the warehouse?" errors.

At 118 rows/second this version takes 35 minutes. It never sees a 429 because a single sequential caller is below the limit by design.

## Version 2: parallel workers and the 429 dance

The obvious fix is `Parallel.ForEachAsync`:

```csharp
await Parallel.ForEachAsync(lines,
    new ParallelOptions { MaxDegreeOfParallelism = 8, CancellationToken = ct },
    async (line, token) => await PatchWithRetryAsync(http, line, token));
```

The moment you do this you need to handle throttling, because D365 will throttle you. The service-protection limits for Dataverse are documented as 6,000 requests per 5 minutes per user, 20 minutes of combined execution time per 5 minutes, and 52 concurrent requests - and D365 Finance applies similar per-user priority-based throttling. Eight workers doing 50 ms calls is roughly 160 requests/second, or 48,000 per 5 minutes: eight times the quota.

The retry has to honour `Retry-After`, and it has to be per request, not per job:

```csharp
static async Task PatchWithRetryAsync(HttpClient http, SalesLine line, CancellationToken ct)
{
    for (var attempt = 0; ; attempt++)
    {
        using var req = BuildPatch(line);
        using var res = await http.SendAsync(req, ct);

        if (res.StatusCode != HttpStatusCode.TooManyRequests)
        {
            res.EnsureSuccessStatusCode();
            return;
        }

        if (attempt >= 5) throw new HttpRequestException($"Throttled 5 times on {line.OrderNumber}/{line.LineNumber}");

        var delay = res.Headers.RetryAfter?.Delta ?? TimeSpan.FromSeconds(Math.Pow(2, attempt));
        await Task.Delay(delay, ct);
    }
}
```

With this in place the job finished in 612 s. But it only got there because of the retries: 37 of them, averaging 28 seconds of `Retry-After` each. That is 17 minutes of worker time spent sleeping, and it explains why going from 8 to 12 workers made the job *slower*, not faster. If you are using `Microsoft.Extensions.Http.Resilience`, the standard pipeline's retry handles `429` and `Retry-After` for you; the point is that you must have *something* doing it.

## Version 3: $batch with changesets

The [earlier $batch post](/posts/odata-batch-requests-dotnet-one-round-trip/) covered the request format for reads. Writes add one concept: a **changeset**. Operations inside a changeset are atomic - D365 either applies all of them or none - and the OData spec requires each changeset to be an all-write group.

The JSON batch format makes this an `atomicityGroup` field. Here the 250,000 rows are chunked into 2,500 batches of 100, each batch being one changeset:

```csharp
foreach (var chunk in lines.Chunk(100))
{
    var requests = chunk.Select((line, i) => new
    {
        id = i.ToString(),
        atomicityGroup = "g1",
        method = "PATCH",
        url = $"SalesOrderLines(dataAreaId='usmf',SalesOrderNumber='{line.OrderNumber}',LineNumber={line.LineNumber})",
        headers = new Dictionary<string, string>
        {
            ["Content-Type"] = "application/json",
            ["If-Match"] = "*"
        },
        body = new
        {
            LineDiscountPercentage = line.DiscountPercentage,
            LineDiscountAmount = line.DiscountAmount
        }
    });

    using var req = new HttpRequestMessage(HttpMethod.Post, "data/$batch")
    {
        Content = JsonContent.Create(new { requests })
    };

    using var res = await SendWithRetryAsync(http, req, ct);
    var batch = await res.Content.ReadFromJsonAsync<BatchResponse>(ct);

    foreach (var r in batch!.Responses.Where(r => r.Status >= 400))
        failures.Add((chunk[int.Parse(r.Id)], r.Status, r.Body?.ToString()));
}
```

Two production notes on changesets:

- **Pick the changeset size by failure cost, not throughput.** 100 was the sweet spot here: 1,000 was only 8% faster but a single bad row rolled back 999 good ones and the retry logic became a project of its own. If rows are independent, you can also omit `atomicityGroup` entirely so each `PATCH` succeeds or fails on its own - throughput was identical, only the semantics differ.
- **D365 Finance caps a batch at 1,000 operations** and Dataverse at 1,000 as well; the request is rejected outright above that, not partially applied.

With 2,500 requests instead of 250,000 the job dropped to 238 s and saw only 4 throttles, all of them because the *execution-time* budget was hit, not the request count.

## Version 4: stop asking for the row back

Every `PATCH` response in versions 1-3 carried the updated entity: about 380 bytes of JSON the job discarded. The `Prefer` header fixes that:

```csharp
req.Headers.Add("Prefer", "return=minimal");
```

Inside a batch the header goes on each subrequest's `headers` dictionary. D365 then answers each operation with `204 No Content` and an `OData-EntityId` header instead of a body. The measured effect was larger than the byte count suggests - 238 s to 151 s - because the server also skips reloading and serialising the row after the update, which on `SalesOrderLines` involves several computed columns.

The remaining 2 throttles were on execution time. Going to 16 parallel *batches* pushed that to 11 throttles and the wall time back up to 190 s; 4 parallel batches stayed throttle-free at 160 s, which is the configuration the job now runs with. Find your tenant's number the same way as for reads: watch for 429 and `Retry-After`, then back off one step.

## What the 429 handling must do differently for writes

Reads are idempotent, so a blanket retry is safe. For writes:

- **A throttled `$batch` has not been applied.** D365 returns 429 for the whole batch before executing any subrequest, so retrying the entire batch is safe. A `500` or a timeout in the *middle* of a batch is not - re-read the rows or use `If-Match` with real ETags instead of `*` so a retry on an already-updated row fails cleanly with `412`.
- **Use a dedicated integration user.** Service-protection limits are per user. A sync job sharing a user with interactive Power Apps sessions throttles the humans too.
- **Log `x-ms-service-request-id` from every 429.** Microsoft support will ask for it, and it is the only way to correlate a throttle with the tenant-level telemetry in LCS.

## Checklist

1. Never write one row per request to D365 when you have more than a few hundred rows; the per-request budget, not your bandwidth, is the limit.
2. Use `$batch` with 100-operation changesets; 2,500 requests are an order of magnitude easier to keep under service protection than 250,000.
3. Add `Prefer: return=minimal` to every write whose response you do not read - it was worth 36% here.
4. Send only the columns that changed and `If-Match: *` (or a real ETag if retries must be safe).
5. Honour `Retry-After` per request, log the service request id, and find the parallelism ceiling by watching for 429 - then run one step below it.

## Related

- [OData Paging Strategies for Large D365 Datasets in .NET](/posts/odata-paging-strategies-large-d365-datasets-dotnet/) - the read side of the same job, and where the 250,000 rows came from.
- [OData $batch in .NET - Replace 50 Round Trips With One Request](/posts/odata-batch-requests-dotnet-one-round-trip/) - the batch request format this post builds on, measured for reads.
- [OData Query Performance Pitfalls in .NET - $expand, Paging and Payload Size Explained](/posts/odata-query-performance-pitfalls-dotnet/) - the start of the series.
