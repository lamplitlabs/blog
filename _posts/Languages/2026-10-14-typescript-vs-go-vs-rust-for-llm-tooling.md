---
layout: post
title: "TypeScript vs Go vs Rust for LLM Tooling: One MCP Server, Three Languages, Measured"
description: "The same MCP server and streaming CLI client in TypeScript 5.9, Go 1.25 and Rust 1.91: cold start, memory, tool-call latency and SDK maturity measured."
date: 2026-10-14 00:00:00 +0200
categories: languages typescript go rust
tags: typescript go rust ai llm mcp tooling performance benchmark cli
author: manishtiwari25
image:
  path: /assets/img/headers/languages/typescript-vs-go-vs-rust-llm-tooling.webp
  alt: "Grouped bar chart comparing TypeScript, Go and Rust implementations of the same MCP server: cold start 410 vs 28 vs 19 ms, idle memory 92 vs 14 vs 6 MB, lines of code 540 vs 820 vs 1,130"
---

Most of this series compared two languages on a classic workload: a [JSON API]({% post_url Languages/2026-10-10-go-vs-nodejs-json-api %}), a [batch log job]({% post_url Languages/2026-10-06-python-vs-go-batch-log-job %}), an [embedding service]({% post_url Languages/2026-10-11-rust-vs-python-ai-inference-microservice %}). This one looks at the workload that has quietly become a category of its own: **LLM tooling**, the small programs that sit between a model and the rest of your system. Tool servers that speak the Model Context Protocol, CLI agents that stream tokens to a terminal, glue that turns a JSON tool result into something a model can read. Three languages are competing for this space, so I built the same thing in all three.

## The workload

Two programs per language, talking to each other over stdio:

1. **An MCP server** exposing three tools: `search_docs` (BM25 over a 40 MB Markdown corpus, pre-indexed on disk), `read_file` (path-restricted) and `run_tests` (spawns a subprocess and returns the tail of its output). The server has to parse JSON-RPC, validate tool arguments against a schema, and stream large results back in chunks.
2. **A CLI client** that connects to the server, lists tools, calls them in a loop driven by a scripted "model" (a fixture of 200 recorded tool calls, so no network and no API bill), and renders a streaming response to the terminal with a progress line.

The three stacks:

- **TypeScript 5.9 on Node 24** with `@modelcontextprotocol/sdk` 1.x and `zod` for schemas. Compiled with `tsc`, run with `node dist/server.js`.
- **Go 1.25** with the official `modelcontextprotocol/go-sdk` and `encoding/json/v2`. Single static binary.
- **Rust 1.91** with the official `rmcp` crate, `tokio`, `serde` and `schemars`. Release build.

```typescript
server.tool("search_docs", { query: z.string(), limit: z.number().int().max(50).default(10) },
  async ({ query, limit }) => {
    const hits = index.search(query, limit);
    return { content: hits.map(h => ({ type: "text", text: `${h.path}#L${h.line}: ${h.snippet}` })) };
  });
```

```go
mcp.AddTool(server, &mcp.Tool{Name: "search_docs"}, func(ctx context.Context, req *mcp.CallToolRequest, in SearchIn) (*mcp.CallToolResult, []Hit, error) {
    hits := index.Search(in.Query, in.Limit)
    return nil, hits, nil // SDK serialises the typed result for us
})
```

```rust
#[tool(description = "Full-text search over the docs corpus")]
async fn search_docs(&self, Parameters(p): Parameters<SearchIn>) -> Result<CallToolResult, McpError> {
    let hits = self.index.search(&p.query, p.limit.unwrap_or(10));
    Ok(CallToolResult::success(hits.into_iter().map(Content::text).collect()))
}
```

All three SDKs now give you the same shape: declare a typed input, return typed content, let the SDK handle JSON-RPC framing. The ergonomic gap between them has closed a lot in a year.

## How it was measured

- Machine: Apple M-series laptop, macOS 26, nothing else in the foreground.
- Cold start: `hyperfine -N` on a `--probe` flag that starts the server, answers one `initialize` and one `tools/list`, and exits. Warm page cache.
- Tool call round trip: client-side p50 over the 200-call fixture, server already running, local stdio.
- Streaming: time to deliver a 2,000-token canned response as 2,000 SSE-style chunks to the terminal renderer.
- Memory: resident set size via `ps`, idle after startup and again while holding a 5 MB `read_file` result in memory.
- Build: wall time from clean source to runnable artefact, plus the size of what you ship.
- Time to first working server: my own clock from empty directory to the first successful `tools/call`, with SDK docs open and no AI assistance. One developer, so a soft number, reported honestly.

## Results

![Table comparing TypeScript 5.9 on Node 24, Go 1.25 and Rust 1.91 implementations of the same MCP server and client: cold start 410 vs 28 vs 19 ms, idle memory 92 vs 14 vs 6 MB, tool call p50 1.9 vs 0.6 vs 0.4 ms, streaming 2,000 tokens 48 vs 31 vs 27 ms, memory holding a 5 MB tool result 210 vs 61 vs 38 MB, build 9 s tsc with 180 MB node_modules vs 4 s 9 MB binary vs 71 s release 6 MB binary, 540 vs 820 vs 1,130 lines of code, SDK status first-party vs official vs official, time to first working server 40 min vs 1 h 10 min vs 2 h 30 min](/assets/img/posts/languages/typescript-vs-go-vs-rust-llm-tooling-results-table.webp){: width="1200" height="560" }

| Metric | TypeScript 5.9 / Node 24 | Go 1.25 | Rust 1.91 |
|---|---|---|---|
| Cold start to first tool call | 410 ms | 28 ms | 19 ms |
| Idle resident memory | 92 MB | 14 MB | 6 MB |
| Tool call round trip p50 (local stdio) | 1.9 ms | 0.6 ms | 0.4 ms |
| Stream 2,000 tokens to terminal | 48 ms | 31 ms | 27 ms |
| Memory holding a 5 MB tool result | 210 MB | 61 MB | 38 MB |
| Build / install | 9 s `tsc`, 180 MB `node_modules` | 4 s, 9 MB binary | 71 s release, 6 MB binary |
| Lines of code (server + client) | 540 | 820 | 1,130 |
| Official SDK | First-party, gets new spec features first | Official since 2025 | Official since 2025 |
| Time to first working server | 40 min | 1 h 10 min | 2 h 30 min |

![Terminal screenshot of hyperfine comparing cold start of the three MCP servers: node dist/server.js 410.3 ms, Go binary 28.1 ms, Rust binary 19.4 ms, Rust 1.45 times faster than Go and 21 times faster than Node](/assets/img/posts/languages/typescript-vs-go-vs-rust-llm-tooling-hyperfine.webp){: width="1200" height="560" }

Four things stand out.

**Cold start is the number that matters most for MCP, and it is a 20x gap.** Editors and agents launch MCP servers as subprocesses, often one per workspace, often on every restart. 410 ms per server is invisible once; with eight servers configured it is a noticeable pause before the first prompt is usable. Go and Rust are both effectively instant. If you ship a tool server that other people install into their editor, this row alone is an argument against Node.

**Per-call latency barely matters.** 1.9 ms versus 0.4 ms for a local tool call is lost in the noise next to the 800-3,000 ms the model takes to decide to call the tool. Do not pick a language for LLM tooling because of per-call speed; nothing in this layer is the bottleneck while a model is in the loop.

**Memory under large tool results is where Node hurts in practice.** Tool results in the real world are big: a file, a log, a database dump. Holding 5 MB of text cost Node 210 MB because the string, its UTF-16 copy, the JSON-serialised form and the chunk buffers all coexist in the heap for a moment. Go and Rust stream through a byte slice. If your agent runs 10 tool servers on a developer laptop alongside an IDE and a browser, this is the difference people notice.

**TypeScript is still the fastest to write, by a lot.** 40 minutes to a working server versus 2.5 hours for Rust is not a skill gap; it is that the TypeScript SDK is first-party, has the most examples, and `zod` schemas double as runtime validation and type inference. The Rust time went into `schemars` derive attributes, lifetimes around the shared index, and one afternoon of fighting `tokio::process` stdout handling for `run_tests`. Go sat in the middle: fewer examples than TypeScript, but the type system never got in the way.

## What each language still wins

**TypeScript** wins the ecosystem. The MCP spec, the reference servers, most of the community servers and most of the agent frameworks are TypeScript-first. New protocol features (elicitation, structured output, resource subscriptions) land in the TypeScript SDK weeks before the others. If your tooling also has a web UI, you share types across the boundary for free.

**Go** wins deployment. One `go build`, one 9 MB static binary, cross-compiled for every platform in a `for` loop in CI, no runtime to install, no `node_modules` to audit. For a tool server that your company's developers install with `brew`, Go is the path of least friction, and the official SDK closed most of the ergonomic gap this year.

**Rust** wins the constrained edge. 6 MB idle, 19 ms start, no GC pause mid-stream. Where this matters: a tool server embedded in a laptop app that must never feel heavy, a WASM build of the same tool running inside a browser or a sandbox, or a tool that itself does heavy work (parsing, indexing, diffing) where the language's own speed pays off. The 71 s release build and 1,130 lines are the price.

## When to pick which

Pick TypeScript when you are prototyping, when the spec is still moving under you, or when the tool server shares code with a web product. Pick Go when you are shipping a server other teams install and run, and you want zero-runtime binaries without the Rust compile tax. Pick Rust when the server is doing real computation itself, when it has to run somewhere memory is a budget, or when you need a WASM target.

The pattern I would actually recommend: prototype in TypeScript because the SDK will get you to a working tool in an afternoon, then port to Go the moment the server is something you install rather than something you run from a repo. Reach for Rust only when the tool's own work, not the protocol glue, is what is slow. All three implementations here are small enough to rewrite against your own tools in a day, and the cold-start row will look the same on your machine.

## Related

- [Go vs Node.js for a small JSON API]({% post_url Languages/2026-10-10-go-vs-nodejs-json-api %}): the same two runtimes on a workload where throughput, not cold start, is the question.
- [Rust vs Python for an AI inference microservice]({% post_url Languages/2026-10-11-rust-vs-python-ai-inference-microservice %}): the layer below this one, where the model dominates every number.
- [Rust vs Go for a CLI tool]({% post_url Languages/2026-10-03-rust-vs-go-cli-tool %}): the build-time and binary-size trade-off in isolation.
- [Python vs TypeScript for an internal CLI]({% post_url Languages/2026-10-06-python-vs-typescript-internal-cli-tool %}): TypeScript's developer-speed advantage on a different tool.
