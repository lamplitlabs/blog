---
layout: post
title: "Enterprise AI: Stop the 429 Storm - Client-Side Rate Limiting for Azure OpenAI, Measured Five Ways"
date: 2026-10-21 08:00:00 +0200
categories: ai enterprise-ai
tags: ai azure openai enterprise enterprise-ai performance reliability dotnet python architecture
author: manishtiwari25
description: "90 requests vs a 60 RPM Azure OpenAI deployment, five client strategies: retries lose 40-80% of calls, a client-side token bucket finishes 90/90 with zero 429s."
image:
  path: /assets/img/headers/ai/enterprise-ai-client-side-rate-limiting-azure-openai.webp
  alt: "Two bar charts comparing five client strategies against one 60 requests-per-minute Azure OpenAI deployment: completed requests out of 90 are 53, 19, 21, 52 and 90, and 429 responses received are 676, 755, 737, 513 and 0; only the client-side token bucket plus semaphore of four completes every request"
---

![Bar charts: completed out of 90 requests 53, 19, 21, 52, 90 and 429s received 676, 755, 737, 513, 0 for strategies A to E](/assets/img/headers/ai/enterprise-ai-client-side-rate-limiting-azure-openai.webp){: width="1200" height="630" }

The [429 retry post](/posts/azure-openai-429-rate-limit-retry-dotnet/) covered what one request should do when Azure OpenAI says no. This post is about what happens when **ninety** of them arrive at once, which is what an enterprise batch job, a nightly document pipeline or a Monday-morning login spike actually looks like. Retrying well per request turns out to be nearly irrelevant: the only strategy that finished the work was the one that never produced a 429 in the first place.

The headline: **against a 60 RPM deployment, every retry-based strategy lost between 40 % and 80 % of the requests after ten attempts each and generated 500-750 rejected calls; a client-side token bucket matched to the quota completed 90/90 with zero 429s and ran at exactly the deployment's limit.**

## Why this matters at enterprise scale

Azure OpenAI quota is per deployment, per region, shared by every caller. A 429 is not a free "try later": each rejected call still costs a round trip through APIM and the gateway, it burns the retry budget of the caller, and on a shared deployment one noisy team's retry storm becomes everyone's latency. We saw exactly this on a shared `gpt-4o` deployment: a back-office import job hammered it at 03:00, and the on-call page came from the customer-facing assistant whose p95 went from 2 s to 14 s. The import job had "exponential backoff with jitter" - textbook, and useless.

## The harness

Rather than burn real quota, I built a mock deployment in Python that behaves like the Azure OpenAI front door: a token bucket of **60 requests per minute with a burst of 10**, a **300-900 ms** service time for accepted calls, and on rejection a `429` with a `Retry-After` header computed from the bucket's refill time. The workload is 90 chat completions arriving at the same moment, each allowed up to 10 attempts. Five client strategies:

| | Strategy | Concurrency | Backoff |
|---|---|---|---|
| **A** | Fire-and-forget, exponential backoff + jitter (200 ms base) | 90 | ignores `Retry-After` |
| **B** | Fire-and-forget | 90 | sleeps `Retry-After` |
| **C** | Semaphore of 4 in-flight | 4 | sleeps `Retry-After` |
| **D** | Semaphore of 1 (fully serial) | 1 | sleeps `Retry-After` |
| **E** | Client-side token bucket at 60 RPM + semaphore of 4 | 4 | sleeps `Retry-After` (never needed) |

The full harness is about 80 lines and sits at the end of this post.

## Results

![Terminal output of bench.py: strategy A ok=53 failed=37 429s=676 wall 206.5 s; B ok=19 failed=71 429s=755 wall 11.1 s; C ok=21 failed=69 429s=737; D ok=52 failed=38 429s=513 p50 18 s wall 44 s; E ok=90 failed=0 429s=0 p50 45.8 s p99 89.9 s wall 89.9 s rpm 60.1](/assets/img/posts/ai/enterprise-ai-client-side-rate-limiting-bench-output.webp){: width="1500" height="360" }

| Strategy | Completed | Gave up | 429s | Attempts | p50 | p99 | Wall | Effective RPM |
|---|---|---|---|---|---|---|---|---|
| A exp backoff | 53 / 90 | 37 | 676 | 729 | 26.9 s | 104.7 s | 206.5 s | 15.4 |
| B Retry-After | 19 / 90 | 71 | 755 | 774 | 1.0 s | 10.1 s | 11.1 s | 103.1 |
| C sem(4) + Retry-After | 21 / 90 | 69 | 737 | 758 | 2.1 s | 12.3 s | 12.8 s | 98.6 |
| D sem(1) + Retry-After | 52 / 90 | 38 | 513 | 565 | 18.0 s | 42.6 s | 44.0 s | 70.9 |
| **E token bucket + sem(4)** | **90 / 90** | **0** | **0** | **90** | 45.8 s | 89.9 s | 89.9 s | **60.1** |

Three things in that table surprised the team.

**1. Honouring `Retry-After` made the failure rate worse, not better.** Strategy B looks great on p50 (1.0 s) and finishes fast - because it gives up fast. The server tells all 80 rejected callers "retry in 1 s", all 80 come back in the same second, 10 get in, 70 are rejected again, and ten rounds later the job has burnt its attempts. `Retry-After` is correct advice for *one* client; it is a synchronisation signal for a crowd. The "Effective RPM" above 60 for B and C is the tell: the client is finishing faster than the deployment can possibly serve because most of what it "finished" is failures.

**2. Exponential backoff spreads the crowd but at a brutal cost.** Strategy A eventually completed 53 requests, but took 206 s and 729 attempts to do it - 7.5 calls for every successful one, each a billable-by-APIM-policy, logged, traced round trip. Its p99 of 104 s is the user-facing timeout nobody budgeted for.

**3. Serialising is not the answer either.** Strategy D (one in flight) still got 513 rejections. With a 300-900 ms service time one serial caller runs at ~100 RPM, which is above the 60 RPM quota, so it hits the limit anyway and then stalls on `Retry-After`. Concurrency is the wrong knob; **rate** is the knob.

**Strategy E** removes the problem. A client-side bucket that releases one request per second (60 RPM) with four in flight for the service-time variance never asks the deployment for more than it has. Zero 429s, 90 attempts for 90 completions, and the wall time of 89.9 s is simply 90 requests at the quota - the physical floor. Its p50 of 45 s looks terrible next to B's 1 s until you remember that B's p50 is measured over the 19 requests that survived.

## The pattern in .NET

The production version is a `DelegatingHandler` in front of `AzureOpenAIClient`, so every caller in the process shares one budget. .NET 7+ ships `System.Threading.RateLimiting`, so there is nothing to write by hand:

```csharp
using System.Threading.RateLimiting;

public sealed class QuotaPacingHandler : DelegatingHandler
{
    private readonly TokenBucketRateLimiter _rpm;
    private readonly SemaphoreSlim _inFlight;

    public QuotaPacingHandler(int requestsPerMinute, int maxInFlight)
    {
        _rpm = new TokenBucketRateLimiter(new TokenBucketRateLimiterOptions
        {
            TokenLimit = Math.Max(1, requestsPerMinute / 6),   // ~10 s of burst
            TokensPerPeriod = Math.Max(1, requestsPerMinute / 6),
            ReplenishmentPeriod = TimeSpan.FromSeconds(10),
            QueueLimit = int.MaxValue,
            QueueProcessingOrder = QueueProcessingOrder.OldestFirst,
            AutoReplenishment = true,
        });
        _inFlight = new SemaphoreSlim(maxInFlight);
    }

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken ct)
    {
        using RateLimitLease lease = await _rpm.AcquireAsync(1, ct);
        if (!lease.IsAcquired) throw new InvalidOperationException("rate limiter queue rejected the request");

        await _inFlight.WaitAsync(ct);
        try
        {
            return await base.SendAsync(request, ct);
        }
        finally
        {
            _inFlight.Release();
        }
    }
}
```

Wire it once:

```csharp
builder.Services.AddHttpClient("aoai")
    .AddHttpMessageHandler(() => new QuotaPacingHandler(requestsPerMinute: 60, maxInFlight: 4));

// then pass the HttpClient into AzureOpenAIClientOptions.Transport
```

Keep the 429 retry policy from the earlier post *behind* this handler: it is still right for the occasional rejection caused by another team sharing the deployment. It just should no longer be your throughput plan.

## Sizing the bucket

- **Requests per minute** comes from the deployment's quota in Azure AI Foundry (or from the APIM `llm-token-limit` policy if a gateway fronts it). If several processes share a deployment, divide it: three replicas of the import job get 20 RPM each, not 60. For a fleet, move the bucket into APIM or Redis rather than trusting each replica's arithmetic.
- **Tokens per minute** is usually the tighter limit on long prompts. The same handler takes a second `TokenBucketRateLimiter` keyed on an estimated prompt-token count ([the token counter](/posts/azure-openai-token-counting-cost-dotnet/) gives you that before the call); acquire `estimatedTokens` permits instead of 1.
- **Max in flight** is service time x rate: 60 RPM at a 900 ms p99 needs ~1 in flight; 4 gives headroom without ever being the limiting factor.
- **Queue, do not drop.** `QueueLimit = int.MaxValue` is deliberate for batch work. For an interactive path set a bounded queue and fail fast with a user-facing message; a 45 s p50 is fine for a nightly import and unacceptable for a chat box.

## What changed in production

After the import job moved onto the pacing handler, the shared deployment's 429 rate at 03:00 dropped from about 38 % of calls to under 1 % (the residue is a second team), the import finished 20 minutes *sooner* despite "slowing down", because it stopped spending its time being rejected, and the customer-facing assistant's p95 no longer moves overnight. The cost line also moved: APIM logged 7x fewer requests for the same number of completions.

## The harness

```python
import threading, time, json, random, urllib.request, urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor

CAP, RATE = 10, 1.0                      # burst 10, 1 token/s => 60 RPM
lock, tokens, last = threading.Lock(), CAP, time.monotonic()

class Mock(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        global tokens, last
        self.rfile.read(int(self.headers.get('content-length', 0)))
        with lock:
            now = time.monotonic(); tokens = min(CAP, tokens + (now - last) * RATE); last = now
            ok = tokens >= 1; wait = 0 if ok else (1 - tokens) / RATE
            if ok: tokens -= 1
        if not ok:
            self.send_response(429); self.send_header('Retry-After', str(max(1, int(wait + 0.999))))
            self.end_headers(); self.wfile.write(b'{"error":{"code":"429"}}'); return
        time.sleep(random.uniform(0.3, 0.9))
        self.send_response(200); self.end_headers()
        self.wfile.write(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

ThreadingHTTPServer.request_queue_size = 512
threading.Thread(target=ThreadingHTTPServer(('127.0.0.1', 8089), Mock).serve_forever, daemon=True).start()
URL = 'http://127.0.0.1:8089/openai/deployments/gpt-4o/chat/completions'

def call():
    try:
        with urllib.request.urlopen(urllib.request.Request(URL, data=b'{}'), timeout=30) as r: r.read(); return 200, 0
    except urllib.error.HTTPError as e: return e.code, int(e.headers.get('Retry-After', '1'))

def run(name, concurrency, honor_retry_after, n=90, max_attempts=10, pace=None):
    lat, stats = [], {'429': 0, 'failed': 0, 'attempts': 0}
    gate, pace_lock, nxt, start = threading.Semaphore(concurrency), threading.Lock(), [time.monotonic()], time.monotonic()
    def one(_):
        t0 = time.monotonic()
        for a in range(max_attempts):
            if pace:                                          # client-side token bucket
                with pace_lock:
                    nxt[0] = max(nxt[0], time.monotonic()); d = nxt[0] - time.monotonic(); nxt[0] += pace
                time.sleep(max(0, d))
            with gate:
                stats['attempts'] += 1; code, ra = call()
            if code == 200: lat.append(time.monotonic() - t0); return
            stats['429'] += 1
            time.sleep(ra if honor_retry_after else 0.2 * 2 ** a + random.uniform(0, 0.1))
        stats['failed'] += 1
    with ThreadPoolExecutor(max_workers=200) as ex: list(ex.map(one, range(n)))
    wall = time.monotonic() - start; lat.sort()
    p = lambda q: lat[min(len(lat) - 1, int(q * len(lat)))] if lat else 0
    print(f"{name:<40} ok={len(lat):>3} failed={stats['failed']:>2} 429s={stats['429']:>3} "
          f"attempts={stats['attempts']:>3} p50={p(.5):5.2f}s p99={p(.99):5.2f}s wall={wall:5.1f}s rpm={len(lat)/wall*60:5.1f}")

run("A  fire-and-forget, exp backoff", 90, False)
run("B  fire-and-forget, honor Retry-After", 90, True)
run("C  semaphore(4), honor Retry-After", 4, True)
run("D  semaphore(1), honor Retry-After", 1, True)
run("E  client bucket 60 RPM + semaphore(4)", 4, True, pace=1.0)
```

Change `CAP`/`RATE` to your deployment's quota and `n` to your batch size, and you have the argument for the pacing handler in under two minutes of runtime.

## Related posts

- [Handling 429 Rate Limits from Azure OpenAI in .NET: Backoff That Actually Works](/posts/azure-openai-429-rate-limit-retry-dotnet/)
- [Enterprise AI: Azure OpenAI Provisioned Throughput (PTU) vs Pay-as-you-go - Cost and Latency Under Sustained Load](/posts/enterprise-ai-azure-openai-ptu-vs-pay-as-you-go-sustained-load/)
- [Enterprise AI: Per-Team Token Quotas and Chargeback for Azure OpenAI with Azure API Management](/posts/enterprise-ai-apim-token-quotas-chargeback-azure-openai/)
- [Counting Tokens and Controlling Azure OpenAI Cost in .NET](/posts/azure-openai-token-counting-cost-dotnet/)
- [Azure OpenAI Batch API in .NET: Process Thousands of Prompts at Half the Price](/posts/azure-openai-batch-api-dotnet/)
