---
layout: post
title: "Rust Async Under Load: Tokio Backpressure in an LLM Gateway"
date: 2026-10-22
categories: performance rust
tags: rust tokio async llm gateway backpressure axum sse performance
description: "An unbounded Tokio channel pushed our Rust LLM gateway's p99 from 41 ms to 46 s at 4,000 SSE streams. Bounding it and shedding load fixed the tail."
image:
  path: /assets/img/headers/performance/rust-tokio-async-llm-gateway-backpressure.webp
  alt: Dark header chart comparing p99 added queueing delay at 4,000 SSE streams - unbounded channel 46 s, bounded 7.3 s, bounded with load shedding 58 ms
---

Backpressure is the property you only notice when it is missing. Our Rust inference gateway — the one from the [Go vs Rust comparison](/posts/go-vs-rust-ai-inference-gateway-latency-memory/) — ran for months without it, because the natural way to wire a streaming LLM relay in Tokio is `mpsc::unbounded_channel`, and an unbounded channel never says no. It also never frees you: under a slow-client burst, the queue becomes the place where latency goes to die silently. This post shows the failure, the fix, and the benchmark numbers behind both.

## The workload

The gateway fronts a GPU cluster and exposes one streaming endpoint per tenant. Each HTTP connection is a server-sent event (SSE) stream relaying tokens from the model runner to the browser:

1. A request arrives and the gateway opens an upstream streaming call to the model runner.
2. A relay task forwards each token chunk from the upstream stream into a Tokio channel.
3. An axum handler consumes the channel and writes each chunk as an SSE event on the client socket.

Stage 2 is where backpressure lives or dies. The upstream produces at GPU speed; the client consumes at network speed. When the client is a phone on hotel Wi-Fi, those two speeds differ by orders of magnitude, and the channel between them absorbs the difference.

The naive wiring, which is also the first thing every Tokio tutorial shows:

```rust
use tokio::sync::mpsc;
use tokio_stream::wrappers::UnboundedReceiverStream;

let (tx, rx) = mpsc::unbounded_channel::<TokenChunk>();

tokio::spawn(async move {
    while let Some(chunk) = upstream.next().await {
        // Never blocks, never fails: the queue just grows.
        let _ = tx.send(chunk);
    }
});

let stream = UnboundedReceiverStream::new(rx);
Sse::new(stream.map(Ok::<_, Infallible>))
```

Under happy-path load this is fine. p99 added queueing delay — the time a chunk spends sitting in the channel instead of moving — was 41 ms at 500 concurrent streams. The failure appeared when we raised the load generator to match the traffic we actually see at peak.

## The failure mode

At 2,000 concurrent streams with a mix of fast and slow clients, the unbounded version did not fall over. It did something worse: it kept accepting work and degraded every stream at once. Memory climbed linearly with queued chunks, and because chunks were being relayed to sockets far slower than they arrived, the queue delay compounded. At 4,000 streams, p99 added delay reached 46 seconds. Users saw a spinner that outlasted the generation itself, then a burst of stale tokens all at once. No error, no signal, nothing to alert on except the memory graph — the exact failure we wrote about in the [time-to-first-token comparison](/posts/llm-streaming-time-to-first-token-dotnet-vs-node/), where Node hid the same stall inside an unbounded `res.write` buffer.

A queue that never says no is not a buffer; it is a leak with good manners.

## The fix, in two moves

**Move one: bound the channel.** Switching to `mpsc::channel(4096)` makes `send` async: when 4,096 chunks are waiting for one slow client, the relay task suspends instead of allocating. That alone pushed the backpressure upstream — the gateway stops reading from the model runner's socket, TCP flow control kicks in, and the runner's own scheduler sheds work. Tail latency improved roughly 6×, because the queue could no longer grow without limit, but a full queue still meant 7.3 seconds of delay at 4,000 streams. Bounded-but-full is still slow.

**Move two: shed load at the edge with `try_send`.** A bounded queue buys you the *ability* to apply backpressure; it does not decide what to do when the queue is full. We decided that a client 4,096 chunks behind is not going to have a good experience no matter what we do, so the gateway returns 429 with a `Retry-After` and frees the upstream capacity for clients that can keep up:

```rust
use tokio::sync::mpsc;
use tokio_stream::wrappers::ReceiverStream;

const QUEUE_DEPTH: usize = 4096;

let (tx, rx) = mpsc::channel::<TokenChunk>(QUEUE_DEPTH);

tokio::spawn(async move {
    while let Some(chunk) = upstream.next().await {
        // Suspends when the queue is full: flow control, not a pile.
        if tx.send(chunk).await.is_err() {
            break; // client disconnected, stop pulling upstream
        }
    }
});
```

And at the admission edge, before a new stream is accepted into a tenant's pool:

```rust
match tenant_slots.try_acquire() {
    Ok(permit) => serve_stream(req, permit).await,
    Err(_) => (
        StatusCode::TOO_MANY_REQUESTS,
        [(header::RETRY_AFTER, "1")],
        "gateway at capacity",
    ).into_response(),
}
```

`shed` rejected 7.3% of requests at 4,000 streams, and the 92.7% it served stayed at a 58 ms p99 — indistinguishable from the 500-stream baseline. Every refused client got an immediate, retriable answer instead of a 46-second stall. This is the same shape as the [`sync.Pool` and worker-pool decision](/posts/go-vs-rust-ai-inference-gateway-latency-memory/) on the Go side: the correct number of things in flight is the number you chose, not the number that arrived.

## Results

Same pod (4 vCPU, 8 GiB), same model-runner stub, same closed-loop load generator holding N concurrent SSE streams open, 15% of them throttled to 100 kb/s to stand in for real networks. Median of three 10-minute runs; p99 computed per connection over inter-chunk gaps and reported as delay added beyond direct upstream timing:

| Streams | Unbounded p99 | Bounded 4,096 p99 | Bounded + shed p99 | Shed rejects |
|---------|---------------|-------------------|--------------------|--------------|
| 500     | 41 ms         | 38 ms             | 39 ms              | 0%           |
| 1,000   | 220 ms        | 96 ms             | 87 ms              | 0%           |
| 2,000   | 4.2 s         | 610 ms            | 54 ms              | 0.4%         |
| 4,000   | 46.0 s        | 7.3 s             | 58 ms              | 7.3%         |

![Grouped bar chart of p99 added queueing delay on a log scale: unbounded grows from 41 ms to 46 s, bounded reaches 7.3 s, bounded with load shedding stays flat near 55 ms](/assets/img/posts/performance/rust-tokio-async-llm-gateway-backpressure.webp)

The chart is log-scale because the honest linear version looks like the unbounded series eats the frame. That is the point: backpressure bugs do not show up as a gradual slowdown, they show up as a cliff you only find in production.

## The discipline

The channel shape is a policy decision, not a performance tweak, and Tokio makes the policy explicit in the type you pick:

- **`unbounded_channel`** — you have decided that memory is the queue. Acceptable when the producer is strictly internal and rate-limited by something else (a fixed thread pool, a bounded iterator). Never acceptable at a network edge.
- **`channel(n)` with `.send().await`** — you have decided to slow the producer. Correct when the producer can afford to wait and slowness upstream is safe, as with TCP flow control here.
- **`channel(n)` with `try_send` / `try_acquire` at admission** — you have decided to refuse work. Correct when a delayed answer is a wrong answer, which is exactly what a token stream is.
- **`broadcast` with lagging receivers** — you have decided slow consumers get dropped frames. Right for metrics fan-out, wrong for anything a user reads.

We settled on the rule that every channel in the gateway has a declared owner, a declared bound, and a declared full-policy in the code review template. Two of the three were already true by convention; writing them down is what caught the last unbounded channel (it was in the health-aggregator, of course).

For the benchmark harness shape — closed-loop client, percentile capture, the throttle mix — we reused the setup from the [.NET vs Node gateway throughput test](/posts/dotnet-vs-node-llm-gateway-throughput/); the load generator is the same `wrk2`-style driver with an SSE-aware client in front of it.

## Related reading

- [Go vs Rust for an AI Inference Gateway: Latency and Memory at the Tail](/posts/go-vs-rust-ai-inference-gateway-latency-memory/) - the gateway this post profiles, and where its 2.4x tail advantage comes from.
- [LLM Streaming: Time to First Token, .NET vs Node](/posts/llm-streaming-time-to-first-token-dotnet-vs-node/) - the same missing-backpressure bug in two other runtimes.
- [.NET vs Node.js: Building an AI Inference Gateway for Maximum Throughput](/posts/dotnet-vs-node-llm-gateway-throughput/) - the benchmark harness and closed-loop methodology this post reuses.
- [Rust vs Go: CPU-Bound Microservice Performance](/posts/rust-vs-go-cpu-bound-microservice/) - where the runtime difference is computation rather than flow control.
