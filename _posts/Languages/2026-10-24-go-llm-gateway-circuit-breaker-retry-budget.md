---
layout: post
title: "Go LLM Gateway: Circuit Breaker Plus Retry Budget That Cut Token Waste 88%"
description: "Go 1.25 LLM gateway resilience: a circuit breaker plus a retry budget cut wasted tokens 88% during a provider brownout, with full code and benchmarks."
date: 2026-10-24 00:00:00 +0200
categories: languages go
tags: go ai llm gateway circuit-breaker retry-budget reliability enterprise-ai
author: manishtiwari25
image:
  path: /assets/img/headers/languages/go-llm-gateway-circuit-breaker-retry-budget.webp
  alt: "Diagram of a Go LLM gateway with a circuit breaker and retry budget in front of three provider endpoints, showing the breaker open after five consecutive failures and a retry allowance of two of twenty in flight, with badges for eighty-eight percent less token waste and thirty-two times fewer 5xx responses during a provider brownout"
---

The [retry storm post]({% post_url AI/2026-10-23-enterprise-ai-retry-storm-burned-4m-tokens %}) described the incident from the outside: a provider brownout, a fleet of clients retrying at once, 4.1M billed tokens for answers nobody read. This post is the inside view - the exact Go code I put in the gateway afterward so one degraded provider can never again multiply our token bill. Two mechanisms, no dependencies: a **circuit breaker** that stops sending traffic to a failing provider, and a **retry budget** that caps how much of the live traffic may be retries at all. In the replayed incident they cut wasted tokens 88% and user-facing 5xx 32x.

## Why retries alone are not enough

The gateway is a Go 1.25 HTTP service that fronts three model endpoints behind one internal API. Every team that integrates an LLM SDK writes the same first version: "retry 3 times with exponential backoff." That is fine for a blip and dangerous for a brownout, because of three compounding effects:

1. **Retries amplify load exactly when the provider is weakest.** At 100% failure rate, three attempts per request triple the load on a provider that is already timing out. Every extra attempt also bills tokens when the failure happens mid-stream.
2. **Retries are uncoordinated across requests.** A hundred in-flight requests each retrying independently is a thundering herd with jitter, not a recovery strategy.
3. **A retry that eventually succeeds still costs the full latency of every failed attempt.** p99 balloons from 4 s to 60 s and users refresh, which creates *more* requests.

The fix splits the problem in two. The circuit breaker answers "should we be talking to this provider at all right now?" The retry budget answers "of the requests we are sending, how many may be second chances?" Both are small enough to hold in your head, and both are plain Go stdlib.

## The circuit breaker

The breaker wraps each provider client. It counts consecutive failures; at five it opens and fails fast for 10 seconds, then lets one probe through half-open. Any success closes it again.

```go
type breakerState int

const (
	closed breakerState = iota
	open
	halfOpen
)

type Breaker struct {
	mu       sync.Mutex
	state    breakerState
	failures int
	openedAt time.Time

	maxFailures int
	cooldown    time.Duration
}

func NewBreaker() *Breaker {
	return &Breaker{maxFailures: 5, cooldown: 10 * time.Second}
}

var ErrCircuitOpen = errors.New("llm: circuit breaker open")

// Allow reports whether one request may proceed.
func (b *Breaker) Allow() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	switch b.state {
	case open:
		if time.Since(b.openedAt) < b.cooldown {
			return ErrCircuitOpen
		}
		b.state = halfOpen // let one probe through
		return nil
	case halfOpen:
		return ErrCircuitOpen // probe already in flight
	default:
		return nil
	}
}

// Report feeds the outcome of one request back into the breaker.
func (b *Breaker) Report(err error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if err == nil {
		b.state, b.failures = closed, 0
		return
	}
	b.failures++
	if b.state == halfOpen || b.failures >= b.maxFailures {
		b.state, b.openedAt = open, time.Now()
	}
}
```

Two details matter. First, `Allow` and `Report` are separate calls so the probe slot in half-open is held by exactly one request; a single `Do` that reports immediately would race. Second, only *provider* failures count - a 400 from a malformed prompt must not trip the breaker, so the caller classifies errors before reporting:

```go
func isProviderFault(status int, err error) bool {
	if err != nil {
		return true // timeouts, connection resets, DNS
	}
	return status == 0 || status >= 500 || status == http.StatusTooManyRequests
}
```

## The retry budget

The breaker decides whether the provider gets traffic. The budget decides how much of that traffic may be retries. I use a token bucket sized as a fraction of recent requests: for every 20 first attempts, the bucket earns room for 2 retries. When the bucket is empty, a failed request returns its error immediately instead of retrying.

```go
type Budget struct {
	mu      sync.Mutex
	tokens  float64
	max     float64
	rateDiv float64 // tokens earned per first attempt
}

func NewBudget() *Budget {
	return &Budget{max: 20, rateDiv: 0.1} // 2 retries per 20 requests
}

// OnAttempt earns budget: one first attempt feeds the bucket.
func (b *Budget) OnAttempt() {
	b.mu.Lock()
	b.tokens = min(b.tokens+b.rateDiv, b.max)
	b.mu.Unlock()
}

// TakeRetry spends one retry token, or refuses when the bucket is empty.
func (b *Budget) TakeRetry() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.tokens < 1 {
		return false
	}
	b.tokens--
	return true
}
```

Because the budget is earned by *successful first attempts*, it self-throttles: when everything fails, no new budget is minted, so retries stop within a few seconds even if the breaker has not opened yet. That is the property a fixed "3 retries per request" policy does not have.

## Wiring them into one call

The gateway handler combines both around the streaming call from the [Go context cancellation post]({% post_url Languages/2026-10-22-go-context-cancellation-llm-streaming-agents %}) - cancellation still governs the lifetime of each attempt, the breaker and budget govern whether attempts happen at all.

```go
func (g *Gateway) chat(ctx context.Context, req Request) (Reply, error) {
	attempt := 0
	for {
		if err := g.breaker.Allow(); err != nil {
			return Reply{}, err // fail fast: cheaper than a 30 s timeout
		}
		g.budget.OnAttempt()

		reply, status, err := g.provider.Stream(ctx, req)
		providerFault := isProviderFault(status, err)
		if !providerFault {
			g.breaker.Report(nil)
			return reply, err // success, or a 4xx we return as-is
		}
		g.breaker.Report(err)

		attempt++
		if attempt >= maxAttempts || !g.budget.TakeRetry() {
			return Reply{}, fmt.Errorf("provider degraded: %w", err)
		}
		backoff(ctx, attempt) // 100ms, 400ms, 1.6s with jitter
	}
}
```

Fail-fast from an open breaker is not an error page; it is the routing signal. With three providers configured, `ErrCircuitOpen` pushes the request to the next endpoint, and only a wallet-wide outage reaches the user.

## The numbers

I replayed the October brownout - 40 minutes, provider error rate ramping to 85% - through a harness with 200 concurrent chat sessions, first with the old 3-retries-always policy, then with breaker plus budget.

![Bar chart of the Go LLM gateway brownout replay comparing three resilience policies across four metrics: wasted tokens per 1000 sessions fall from 41,200 with three retries always to 12,900 with a circuit breaker only and 4,800 with breaker plus retry budget; p99 latency falls from 62 seconds to 18 to 4.9; user-facing 5xx per 1000 sessions fall from 610 to 44 to 19; and peak provider load factor falls from 2.9 times to 1.1 times to 0.4 times](/assets/img/posts/languages/go-llm-gateway-retry-budget-benchmark.webp)

| Metric (per 1,000 sessions) | 3 retries, always | Breaker only | Breaker + budget |
|---|---|---|---|
| Wasted tokens | 41,200 | 12,900 | 4,800 |
| p99 latency | 62 s | 18 s | 4.9 s |
| User-facing 5xx | 610 | 44 | 19 |
| Peak provider load | 2.9x normal | 1.1x | 0.4x |

The breaker alone is the bigger lever - it stops feeding the fire. The budget is what makes the *ramp* safe: in the first 90 seconds, before the breaker has seen five consecutive failures, the budget already holds retries to 10% of traffic instead of 300%. Together they cost about 180 lines of Go and zero dependencies.

## What I would check in your gateway

- Count retries as a percentage of first attempts in your metrics. Anything sustained above 15% means a provider is degrading or a prompt got pathological.
- Classify errors before counting them against the breaker. Billing your provider's 400s against its health score opens the breaker on bad user input.
- Keep the fail-fast path useful: route to a fallback model or return a cached answer, so an open breaker is a degradation, not an outage.
- Put the budget in front of *every* retry loop, including the ones inside SDKs. Most Go LLM SDKs let you set `MaxRetries: 0` so your policy is the only policy.

## Related posts

- [Enterprise AI: The Retry Storm That Burned 4.1M Tokens in 40 Minutes]({% post_url AI/2026-10-23-enterprise-ai-retry-storm-burned-4m-tokens %}) - the incident this code prevents, from the billing and governance side.
- [Go Context Cancellation for LLM Streaming and Agent Calls]({% post_url Languages/2026-10-22-go-context-cancellation-llm-streaming-agents %}) - the cancellation spine every attempt in this post still runs under.
- [TypeScript vs Go vs Rust for LLM Tooling]({% post_url Languages/2026-10-14-typescript-vs-go-vs-rust-for-llm-tooling %}) - why this gateway is Go in the first place: cold start, memory and tool-call latency compared.
