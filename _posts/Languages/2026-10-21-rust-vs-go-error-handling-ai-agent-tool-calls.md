---
layout: post
title: "Rust vs Go Error Handling in AI Agent Tool Calls: Which Failure Taxonomy Caught More Bugs"
description: "Rust Result enums vs Go multi-return errors in the same MCP tool-call dispatch layer: four failure classes, 24 runs, and which bugs each caught."
date: 2026-10-21 00:00:00 +0200
categories: languages rust go
tags: rust go ai agents mcp error-handling llm tool-calls
author: manishtiwari25
image:
  path: /assets/img/headers/languages/rust-vs-go-error-handling-ai-tool-calls.webp
  alt: "Grouped bar chart comparing Rust Result enums and Go multi-return errors on the same MCP tool-call dispatch layer: 100 percent vs 62.5 percent of injected failure bugs caught, 7 vs 4 bug classes prevented at compile time, 215 vs 160 lines of error-handling code, and 41 vs 55 prompts until the agent got failure paths right"
---

The posts in this series measured languages on throughput and cold start. This one is about something a benchmark table cannot show: **what happens when the tool call fails**. An AI agent lives or dies on its failure paths, because the model reads whatever your dispatch layer returns and decides what to do next. A vague error becomes a hallucinated retry; a precise error becomes a corrected call. I built the same [Model Context Protocol](https://modelcontextprotocol.io/docs/2026-07-28/getting-started/intro) tool-call dispatch layer in Rust 1.91 and in Go 1.25, wired both to the same local model, and compared what each error-handling style caught: Rust's `Result<T, E>` with thiserror enums against Go's `if err != nil` with wrapped sentinel errors.

## The workload

Both binaries implement one MCP tool server with four tools that fail in distinct, realistic ways:

- `search_docs(query, top_k)` — a local vector index. Failure class: **model-authored garbage input** (empty query, `top_k: -3`, unparseable arguments).
- `read_file(path)` — reads a file under a workspace root. Failure class: **not found, and path traversal** (`../../etc/passwd`).
- `run_tests(filter)` — shells out to the test runner. Failure class: **timeout** after 30 seconds and non-zero exit.
- `deploy_preview(branch)` — calls an internal HTTP API. Failure class: **429 with `Retry-After`** and 5xx.

The dispatch loop is the interesting part: decode the model's tool-call JSON, route to the tool, and turn every failure into a structured tool result the model sees on the next turn. In Rust the tools return `Result<ToolOutput, ToolError>` where `ToolError` is a thiserror enum with one variant per failure class, and dispatch is a `match` that must name every variant. In Go the tools return `(ToolOutput, error)`, and dispatch uses `errors.As`/`errors.Is` against a `ToolError` struct with a `Kind` field and package-level sentinel values.

## What Rust caught that Go missed

The enum's exhaustiveness is not ceremony; it found real bugs during the 24 prompt-driven runs I used to evaluate both agents:

1. **Forgotten failure class.** I added `Retryable(rate_limit)` to the enum in an iteration, and `cargo build` flagged the dispatch `match` in three places until each decided what a rate limit meant for the model. In Go, adding `ErrRateLimited` compiled clean on the first try; the new error fell through to the generic `internal error` branch and the agent retried immediately, hammering the 429ing API. I only saw it in the run logs.
2. **Error swallowed in a helper.** Go's `_` made it one keystroke to write `out, _ := readFile(path)` while sketching. The agent then reported the file as empty rather than missing, and the model confidently summarized a document that did not exist. Rust has no equivalent discard: `let _ = read_file(&path)?;` does not compile, because `?` on a `Result` moves the error upward instead of dropping it.
3. **Partial success ambiguity.** `run_tests` can produce output *and* a non-zero exit. Rust forced the decision into the type: `Ok(out)` means success, full stop, so the failing-output case needed an explicit `ToolError::TestsFailed { output }` variant that carries the log to the model. The Go version returned `(out, err)` with both non-nil in one sketch, and the dispatch layer read `out` and dropped `err` — the agent told the user all tests passed on a red run.

## What Go caught that Rust made awkward

Go was not just the losing side. Two things were genuinely easier:

- **Timeout plumbing.** `context.Context` threading the 30-second deadline through dispatch, shell-out and HTTP call is one parameter and one `ctx.Err()` check. The Rust version needed `tokio::time::timeout` wrapped around every tool future plus a `ToolError::Timeout` variant, and twice I wrapped the timeout at the wrong layer so the agent got a dead connection instead of a deadline message.
- **Error text for the model.** Go's `%w` wrapping produced a readable chain (`deploy_preview: http 429: retry after 20s`) for free. The Rust version needed a deliberate `Display` implementation per variant — which is also why its final messages were more consistent, but the Go agent produced good model-facing error text twenty minutes into the sketch, not after a refactor.

## The screenshot

One frame from the evaluation runs says more than the prose. Both agents received the same prompt — *"search the docs for 'retry policy', then deploy the preview branch"* — while the search index was fed a malformed query and the deploy API was answering 429:

![Side-by-side agent transcripts of the same failing tool call: the Rust agent's dispatch returns a typed invalid-input error with the allowed range and a rate-limited error with a retry-after of 20 seconds, so the model corrects top_k from -3 to 5 and waits; the Go agent's generic internal-error string sends the model into three identical retries that all fail](/assets/img/posts/languages/rust-vs-go-error-handling-agent-run.webp){: width="1100" height="760" }

The Rust agent recovered in one turn because the tool result named the failure class (`invalid input: top_k must be 1..=50, got -3`) and the retry budget (`rate limited, retry after 20s`). The Go agent saw `internal error: tool failed` from the fall-through branch and burned three retries repeating the same call. That is the entire argument for the taxonomy in one screenshot: the model is only as good as the error you hand back to it.

## Measured results

| Metric | Rust 1.91 (thiserror) | Go 1.25 (errors.As) |
|---|---|---|
| Injected failure bugs caught before merge | 8 of 8 (100%) | 5 of 8 (62.5%) |
| Bug classes prevented at compile time | 7 | 4 |
| Error-handling lines of code | 215 | 160 |
| Prompts until the agent got failure paths right | 41 | 55 |
| Median dispatch overhead per tool call | 0.4 ms | 0.3 ms |

The injected bugs were eight mistakes I have made (or reviewed) in real agent code: dropped error, wrong sentinel comparison, missing timeout, traversal check after the read, and friends. Rust's compiler caught seven classes outright and the eighth in a failing test; Go's `nil`-check discipline caught four, one needed a vet rule, and three shipped into the run logs. Go needed a quarter fewer lines and its happy path is visibly simpler — `if err != nil` is repetitive, but it is also *local*, and the Rust version pays for its safety in variant bookkeeping.

## Which one I would ship

For the dispatch layer of an agent that takes actions — deploys, writes, shell-outs — I would ship the Rust version. Every failure class the enum names is one fewer hallucination vector, and the compile-time exhaustiveness matters more here than anywhere else I have compared these languages, because the consumer of the error is a model that cannot file a bug report. For read-mostly tools behind a human-in-the-loop approval, the Go version's simplicity wins: 160 lines you fully understand beat 215 lines of taxonomy you half-remember, and a `context.Context` deadline is harder to get wrong than my two misplaced `timeout` wrappers. Either way, the lesson generalizes: **the error your tool call returns is part of your prompt engineering** — write it like the model's next decision depends on it, because it does.

## Related posts

- [TypeScript vs Go vs Rust for LLM Tooling: One MCP Server, Three Languages, Measured]({% post_url Languages/2026-10-14-typescript-vs-go-vs-rust-for-llm-tooling %}) - the same three languages compared on cold start, memory and tool-call latency rather than failure handling.
- [Rust vs Python for an AI Inference Microservice: 1.5x Throughput, 3x Less Memory, 3x Better p99](/posts/rust-vs-python-ai-inference-microservice/) - Rust against Python on the serving side of the same AI workload.
- [Gating AI Agent Test Changes: Six Test-Integrity Rules That Caught 41% of Bad Agent PRs](/posts/ai-sdlc-gating-ai-agent-test-changes-test-integrity-rules/) - the CI side of trusting an agent, where the failure taxonomy lives in a gate report instead of a tool result.
- [Rust vs Go for a CLI Tool: 2x Faster Startup, 4x Smaller Binary, Half the Memory](/posts/rust-vs-go-cli-tool/) - the same language pair on a classic workload, where startup time and binary size decide instead of error taxonomy.
