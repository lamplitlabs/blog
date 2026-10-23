---
layout: post
title: "Go Context Cancellation for LLM Streaming and Agent Calls: One Pattern That Cut Waste 47x"
description: "Go context.Context deadlines and cancellation for LLM token streaming and agent tool calls: four leak patterns, fixes, and measured savings."
date: 2026-10-22 00:00:00 +0200
categories: languages go
tags: go ai agents llm streaming context cancellation timeouts reliability
author: manishtiwari25
image:
  path: /assets/img/headers/languages/go-context-cancellation-llm-streaming-agents.webp
  alt: "Diagram of a Go agent runner passing one request context with a 45 second deadline into a streaming LLM call, an HTTP tool call and a queue publish, with panels showing a cancelled token stream at 40 kilobytes per second, a green badge for zero goroutine leaks and a red badge for 47 times less wasted token spend after the context fixes"
---

My Go agent service had a leak you could not see in a dashboard: every time a user closed a chat tab mid-answer, the server kept streaming tokens from the provider, kept running tool calls, and kept paying for both. The fix was not a new dependency or a refactor of the agent loop. It was taking Go's `context.Context` seriously as the **one cancellation spine** that runs from the HTTP handler down to the token stream and every tool call. After wiring it correctly, wasted token spend on abandoned sessions dropped 47x and goroutine count stopped climbing between deploys.

## The workload

The service is a Go 1.25 API that fronts a coding assistant. One request to `POST /chat` does three things, sometimes in sequence, sometimes concurrently:

- **Streams the answer** from an LLM provider over server-sent events. A typical answer is 200-400 tokens over 8-15 seconds.
- **Calls tools** when the model asks: an internal search API over HTTP and a code-index lookup with a p50 of 900 ms and a p99 of 11 s.
- **Publishes audit events** to a queue after the turn completes.

Everything hangs off one handler, and Go gives that handler a `*http.Request` whose `Context()` is cancelled the moment the client disconnects. The entire reliability story of this service is about whether that cancellation actually reaches the three leaves.

## Four leaks the context fixes

Each of these was a real defect in my first version, and each maps to one `context` idiom:

1. **The stream ignored the disconnect.** The provider call was made with `context.Background()`, so a closed tab changed nothing: tokens kept arriving into a response writer that errored on every write, and the provider billed the full completion. Fix: pass the request context into the streaming call so the provider sees the connection drop and stops generating.
2. **The agent loop had no deadline.** A model that loops on tool calls could run for minutes. Fix: `context.WithTimeout(r.Context(), 45*time.Second)` at the top of the agent runner, so a turn has a hard budget no matter what the model decides.
3. **Tool calls outlived the turn.** The code-index lookup ran in a goroutine with its own background context; when the turn ended, the lookup kept burning CPU for up to 11 seconds. Fix: derive the tool call's context from the turn's, so abandoning the turn abandons the lookup.
4. **The audit publish blocked the exit path.** Publishing used the request context, which is already cancelled at that point, so publishes failed silently on every abandoned turn. Fix: this is the one place you *detach*: `context.WithoutCancel` keeps the values (trace ID, user ID) but drops the cancellation, giving the publish its own short timeout.

## The pattern

The whole design fits in a few lines. One parent context per request, child contexts with tighter deadlines where a component needs a stricter budget, and `select` on `ctx.Done()` anywhere you poll:

```go
func (h *Handler) chat(w http.ResponseWriter, r *http.Request) {
	// Hard budget for the whole turn; cancelled early if the client leaves.
	ctx, cancel := context.WithTimeout(r.Context(), 45*time.Second)
	defer cancel()

	stream, err := h.llm.StreamChat(ctx, req) // provider sees the disconnect
	if err != nil {
		writeError(w, err)
		return
	}
	defer stream.Close()

	for {
		ev, err := stream.Recv() // returns promptly on cancel or deadline
		if err != nil {
			break
		}
		if err := writeSSE(w, ev); err != nil {
			return // client gone; defer cancel() stops the provider stream
		}
	}
}

func (r *Runner) callTool(ctx context.Context, call ToolCall) (Result, error) {
	// A tool gets the turn's context with a tighter cap of its own.
	tctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	return r.tools[tool.Name].Run(tctx, call.Args)
}

// The one deliberate detach: audit must publish even on abandoned turns.
func (r *Runner) audit(ctx context.Context, ev Event) {
	pctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
	defer cancel()
	r.queue.Publish(pctx, ev)
}
```

Three details carry most of the weight:

- **`defer cancel()` is not optional.** Without it the timer from `WithTimeout` lives until it fires, which on a 45-second budget across thousands of requests is a slow leak of timer goroutines.
- **Check `ctx.Err()` to tell cancel from failure.** `context.Canceled` means the *client* left (log at debug, no alert); `context.DeadlineExceeded` means your *budget* blew (log at warn, page if it spikes). Treating them as one error hid the fact that my 10 s tool cap was too tight for the code index's p99.
- **Propagate, don't restart.** The bug farm is `context.Background()` (or `context.TODO()`) appearing deep in the call tree. I added a `revet`-style lint rule that fails the build on `context.Background()` outside `main` and tests, and it has caught every regression since.

## What the checks measured

I exercised the fixed service with a harness that abandons streams at random points and loops tool calls until the deadline, over 200 sessions per configuration:

| Metric | Before fixes | After fixes |
|---|---|---|
| Wasted tokens per abandoned session | 412 | 8.8 |
| Wasted token spend per day (4.1k abandons) | $25.30 | $0.54 |
| Goroutines after 200 abandoned sessions | 1,847 | 43 |
| Turns ended within 1 s of client disconnect | 3% | 99.5% |
| Audit events lost on abandoned turns | 100% | 0% |

The screenshot below is the harness mid-run: abandoned sessions cancel their streams in about 3 ms, and the goroutine count returns to baseline between waves instead of ratcheting upward.

![Terminal output of the Go context harness running 200 sessions with 30 percent abandoned mid-stream: 99.5 percent of abandons cancel within 50 milliseconds, p50 cancel latency 3.2 milliseconds, wasted tokens per abandon down from 412 to 8.8, goroutines at 43 against a 1,847 baseline before the fixes, and goleak reporting no leaks](/assets/img/posts/languages/go-context-cancellation-harness.webp)

Two results were not obvious up front. The goroutine win came almost entirely from fix 3: each orphaned code-index lookup pinned a worker and its buffers for up to 11 seconds. And the audit fix mattered more than expected: a third of all turns end in abandonment on a coding assistant (users close the tab when the answer is visibly wrong), so "abandoned" is the common case, not the edge case — anything keyed to turn completion must survive cancellation.

## What I would ship

If your Go service calls an LLM, the checklist is short: the provider call takes the request context, the agent loop wraps it in `WithTimeout`, every tool and goroutine derives from that turn context, exactly one component (audit/telemetry) detaches with `WithoutCancel`, and a lint rule keeps `context.Background()` out of the call tree. That is five decisions, all in the standard library, and they turned cancellation from a billing bug into the most reliable path in the service — the client leaving is now the *fastest* way a turn ends, which is exactly what it should be.

## Related posts

- [Rust vs Go Error Handling in AI Agent Tool Calls: Which Failure Taxonomy Caught More Bugs]({% post_url Languages/2026-10-21-rust-vs-go-error-handling-ai-agent-tool-calls %}) - the error side of the same agent dispatch layer, where the message your tool returns is part of your prompt engineering.
- [Go vs Node.js for a JSON API: 2.1x Throughput, 4x Lower p99 Latency, One-Third the Memory](/posts/go-vs-nodejs-json-api/) - the same language on a classic API workload, where throughput and p99 decide instead of cancellation semantics.
- [TypeScript vs Go vs Rust for LLM Tooling: One MCP Server, Three Languages, Measured]({% post_url Languages/2026-10-14-typescript-vs-go-vs-rust-for-llm-tooling %}) - the same tool server in three languages, measured on cold start, memory and tool-call latency.
- [Rust vs Python for an AI Inference Microservice: 1.5x Throughput, 3x Less Memory, 3x Better p99](/posts/rust-vs-python-ai-inference-microservice/) - the serving side of the same AI stack, where latency under load is the constraint.
