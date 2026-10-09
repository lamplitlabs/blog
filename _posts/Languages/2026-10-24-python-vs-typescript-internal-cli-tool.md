---
title: "Python vs TypeScript for an Internal CLI Tool: Startup Time, Packaging and the 1,400 Lines Both Took"
date: 2026-10-24 08:00:00 +0200
categories: languages
tags: python typescript node bun cli programming-languages comparison developer-experience
description: "Python 3.12 vs TypeScript on Node 22 and Bun for the same internal deploy CLI: cold start measured with hyperfine, plus packaging."
image:
  path: /assets/img/headers/languages/python-vs-typescript-internal-cli.webp
  alt: "Bar chart of cold start time for the same internal CLI: Python plain 412 ms, Python with pydantic and click 688 ms, TypeScript via tsx 931 ms, TypeScript bundled with esbuild 298 ms, TypeScript compiled with bun 141 ms"
---

![Bar chart of cold start time for the same CLI: Python plain 412 ms, Python with pydantic and click 688 ms, TypeScript via tsx 931 ms, TypeScript bundled with esbuild 298 ms, TypeScript compiled with bun 141 ms](/assets/img/headers/languages/python-vs-typescript-internal-cli.webp){: width="1200" height="630" }

Internal CLIs are where language debates get personal. The platform team writes Python, the frontend team writes TypeScript, and both want the `tool deploy` command that every developer runs twenty times a day to be in their language. The earlier [Python vs Rust hot loop]({% post_url Performance/2026-10-07-python-vs-rust-hot-loop-performance %}) post was about throughput; this one is about the thing a CLI user actually feels, which is cold start.

## The tool

`tool` is a deploy helper with five subcommands: `deploy`, `diff`, `env`, `logs`, `rollback`. It reads a 4 MB YAML/JSON config tree, validates it against a schema, talks to an HTTP API, and prints tables. I wrote it twice:

- **Python 3.12** with `click`, `pydantic` v2, `httpx`, `rich`. 1,412 lines.
- **TypeScript 5.6** with `commander`, `zod`, native `fetch`, `cli-table3`. 1,655 lines, of which about 180 are type declarations that have no Python equivalent.

Same tests, same fixtures, same behaviour. The line counts are close enough that neither side can claim the "less code" argument.

## Cold start, measured

The number that matters is how long `tool deploy --dry-run` takes before the first byte of output on a developer laptop (M2, warm disk cache). `hyperfine`, 3 warmup, 20 timed runs.

![Terminal screenshot of hyperfine: python -m tool deploy --dry-run 688.4 ms mean, node dist/tool.js 298.1 ms, bun-compiled ./tool 141.3 ms, the compiled binary 2.11 times faster than node and 4.87 times faster than python, followed by wc -l showing 1,412 Python lines and 1,655 TypeScript lines](/assets/img/posts/languages/python-vs-typescript-cli-hyperfine.webp){: width="1200" height="760" }

| Variant | Mean cold start |
|---|---|
| Python, stdlib only (`argparse`, `json`) | 412 ms |
| Python with `click` + `pydantic` + `rich` | 688 ms |
| TypeScript via `tsx` (no build step) | 931 ms |
| TypeScript bundled with `esbuild`, run with Node 22 | 298 ms |
| TypeScript compiled with `bun build --compile` | 141 ms |

The spread inside each language is larger than the gap between them. Python's 276 ms penalty is entirely imports: `pydantic` alone is 160 ms of it, `rich` another 70 ms. TypeScript's worst case is `tsx` transpiling on every start, and its best case is a bundle where Node (or Bun) has one file to parse instead of 400 modules under `node_modules`.

## What fixed Python

- Lazy imports inside subcommands: `rich` is only imported by `logs` and `diff`. Cold start for `deploy` dropped from 688 to 530 ms.
- `python -X importtime` to find the rest. `httpx` pulls in `anyio` and `h2` at import; switching to `urllib.request` for the three calls the tool makes saved another 90 ms.
- Final Python number: **441 ms**, 30 ms over the stdlib-only baseline. I could not get `pydantic` cheaper than that without dropping it.

## What fixed TypeScript

- A single `esbuild --bundle --platform=node --format=esm` step at install time. That is it. 931 ms to 298 ms.
- `bun build --compile` produces a 58 MB single binary at 141 ms. It is the fastest option here but requires every developer machine to accept a 58 MB file per release and a toolchain the platform team does not otherwise use.

## Packaging, the part people forget

| Concern | Python | TypeScript |
|---|---|---|
| Install for a developer | `pipx install tool` (needs a Python 3.12 on the machine) | `npm i -g @org/tool` (needs Node 22) or download the Bun binary |
| Reproducible dependency set | `uv lock`, worked first try | `package-lock.json`, worked first try |
| CI image size for the tool's own tests | 180 MB | 230 MB (Node) / 95 MB (Bun) |
| Typed config schema | `pydantic` model, 60 lines | `zod` schema, 55 lines, and the inferred type is free |

Neither is painful any more. `uv` closed most of the historical gap on the Python side.

## The decision

We kept the TypeScript version, bundled with esbuild and run on Node. Not because 298 ms beats 441 ms - nobody notices 140 ms once a day - but because the people who maintain the tool day to day are the ones who also maintain the frontend build, and the schema types flow into the admin UI without a second definition. If the platform team owned it, the Python version at 441 ms would have been a perfectly good answer.

The measurable lesson is the same one as in the hot-loop post: measure the version you would actually ship, not the one you got running first. The 931 ms `tsx` number nearly lost TypeScript the argument before anyone had run a bundler.

## Related

- [Python vs Rust in a Hot Loop: What 10 Million Iterations Cost, Measured with hyperfine]({% post_url Performance/2026-10-07-python-vs-rust-hot-loop-performance %}) - the same hyperfine method applied to compute.
- [pg vs Prisma vs Drizzle: PostgreSQL Driver Latency from Node.js 22, Measured with autocannon]({% post_url Performance/2026-10-08-postgres-driver-latency-pg-vs-prisma-vs-drizzle %}) - another case where the library choice inside one language outweighed the language.
- [Node.js 22 vs Deno 2 vs Bun 1.1: HTTP JSON API Throughput, Measured with wrk]({% post_url Performance/2026-10-04-node-vs-deno-vs-bun-http-performance %}) - where Bun's runtime advantage does and does not hold.
- [Python vs Go for a Batch Log-Processing Job: Wall Time, Memory, Lines of Code and the Day-Two Costs]({% post_url Languages/2026-10-20-python-vs-go-batch-log-job %}) - the same language-comparison method with Go as the second contender.
- [Regex Engine Performance: Rust regex vs Go regexp vs .NET 8 Regex vs Node 22, Measured with hyperfine]({% post_url Performance/2026-10-15-regex-engine-performance-rust-go-dotnet-node %}) - why the Node regex path in the TypeScript tool is faster than you would guess.
