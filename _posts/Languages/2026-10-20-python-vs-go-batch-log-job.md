---
layout: post
title: "Python vs Go for a Batch Log-Processing Job: Wall Time, Memory, Lines of Code and the Day-Two Costs"
date: 2026-10-20 00:00:00 +0200
categories: languages python go
tags: python go batch-processing performance benchmark hyperfine polars
author: manishtiwari25
description: "Python 3.12 vs Go 1.23 on the same 10 GB JSON-lines aggregation job: wall time, peak memory, lines of code, deploy artifact, and when Polars changes the answer."
image:
  path: /assets/img/headers/languages/python-vs-go-batch-log-job.webp
  alt: "Bar chart comparing Python and Go for the same 10 GB batch log job: wall time 148 s vs 9.8 s, peak RSS 1.9 GB vs 210 MB, lines of code 212 vs 338, clean build or start 0.0 s vs 1.4 s, deploy artifact 320 MB image vs 7.1 MB binary"
---

The earlier posts in this category compared languages that sit at roughly the same level: [Rust vs Go]({% post_url Languages/2026-10-16-rust-vs-go-cli-tool %}) for a CLI, [Zig vs C]({% post_url Languages/2026-10-18-zig-vs-c-systems-tool %}) for a proxy, [TypeScript vs Kotlin]({% post_url Languages/2026-10-14-typescript-vs-kotlin-backend-services %}) for an API. This one is deliberately lopsided. The most common "should we rewrite this?" conversation I hear in enterprise teams is about a Python batch job that started as a notebook, became a cron job, and now takes long enough that someone suggests Go.

So, the same method again: one job, written twice, measured rather than argued about. `agg` reads 10 GB of JSON-lines access logs (about 38 million records), parses each line, and produces per-tenant, per-hour counts of requests, 5xx responses and p95 latency. Python 3.12 (CPython, `orjson`) against Go 1.23 (`encoding/json` swapped for `goccy/go-json`, one goroutine per CPU core), both measured with hyperfine on an 8-core Linux box reading from local NVMe.

## The job under test

- Input: 10 GB, one JSON object per line, 14 fields, no nesting.
- Output: a CSV of `tenant,hour,requests,errors,p95_ms` - around 40,000 rows.
- Python: a single process, `orjson.loads` per line, a `dict` of lists per key, `statistics.quantiles` at the end. 212 lines.
- Go: a reader goroutine fanning chunks of lines out to 8 worker goroutines, each with its own map, merged at the end. 338 lines.

## Wall time and memory

![Terminal screenshot of hyperfine comparing python3 agg.py at 148.212 s mean against ./agg-go at 9.812 s mean, 15.11 times faster for Go, followed by /usr/bin/time showing 1992294400 and 220200960 bytes maximum resident set size, a Polars version of the Python job at 14.306 s, and go build producing a 7.1M binary](/assets/img/headers/languages/python-vs-go-batch-hyperfine-terminal.webp){: width="1200" height="760" }

| | Python 3.12 | Go 1.23 |
|---|---|---|
| Wall time, 10 GB, mean of 10 runs | 148.2 s | 9.8 s |
| CPU time (user) | 146.1 s | 31.2 s |
| Peak RSS | 1.9 GB | 210 MB |
| Lines of code | 212 | 338 |
| Build / start-up | none / 0.0 s | 1.4 s clean build |
| Deploy artifact | 320 MB container image | 7.1 MB static binary |

Fifteen times faster is a bigger gap than any of the compiled-vs-compiled comparisons earlier in this series, and almost all of it is the obvious thing: the Python version uses one core and the Go version uses eight. Pin Go to `GOMAXPROCS=1` and the gap drops to about 3.4x, which is the honest "same algorithm, one core" number - JSON parsing and map updates in CPython are interpreted, in Go they are not.

The memory gap is a different story. Python's 1.9 GB is the per-key lists of latencies kept for the final percentile. Go's version holds the same data; it is just that a `[]float32` of 40,000 entries costs 160 KB in Go and a Python `list` of 40,000 `float` objects costs about 1.3 MB. Switching Python to `array('f')` cut peak RSS to 600 MB at no speed cost, which is the kind of fix that is cheaper than a rewrite.

## The Polars detour

Before anyone rewrites a Python job, the fair comparison is against Python done properly. A third version using Polars - `pl.scan_ndjson(...).group_by(...).agg(...)` with a streaming collect - ran in 14.3 s and 480 MB. That is 30 lines of Python, it uses every core, and it is within 1.5x of the hand-written Go.

| | Python + orjson | Python + Polars | Go |
|---|---|---|---|
| Wall time | 148.2 s | 14.3 s | 9.8 s |
| Peak RSS | 1.9 GB | 480 MB | 210 MB |
| Lines of code | 212 | 31 | 338 |
| Dependencies to vet | 1 | 1 (plus a 60 MB wheel) | 1 |

The lesson from the [Python vs Rust hot-loop post]({% post_url Performance/2026-10-07-python-vs-rust-hot-loop-performance %}) applies again: Python is slow in the loop *you* write and fast in the loop a library wrote in Rust or C. If the job is a group-by over flat records, that library already exists.

## Day-two costs

The benchmark table does not show the parts that decided the question on the teams I have watched make it.

- **Deployment.** The Go binary copies onto the batch host with `scp` and runs. The Python job needs a matching interpreter, a virtualenv and the `orjson` or `polars` wheel for that CPU, which in practice means a 320 MB container image and a registry. If the host is a locked-down VM in a customer's network, that difference is the whole decision.
- **Who maintains it.** The Python job was written by the data team and they could read every line of it. The Go version needed a channel fan-out, a `sync.WaitGroup` and a merge step, and the first review comment was "what happens if a worker panics?" (answer in the first draft: the program hangs). Goroutines make the job fast and also make it a program the data team will not touch.
- **Schema drift.** When a new field appeared in the logs, Python ignored it. Go's struct-based decoding also ignored it - but when `latency_ms` changed from an integer to a float string on one tenant, Python kept going with a wrong number and Go failed the whole run with a type error on line 11,204,312. Both behaviours are wrong; Go's was found the same day.
- **Testing.** The Python job's tests ran in 0.4 s. The Go tests ran in 1.9 s including the build, and `go test -race` found a map write from two goroutines in the merge step that the plain run had never tripped.

## Which would I pick?

If the job is "read records, group, aggregate" and it lives where Python already lives - a data platform, Airflow, a notebook team - stay in Python and move the loop into Polars (or DuckDB). Fifteen minutes of work gets you ten of the fifteen-fold speed-up and nobody has to learn goroutines.

If the job has to ship as one file to machines you do not control, has to start in milliseconds, or does per-record work that no dataframe library expresses - calling out to a service per line, stateful sessionisation, custom parsing - Go. It costs about 50% more code and a concurrency review, and it buys a 7 MB artifact that runs anywhere and a type system that fails loudly when the input changes.

What I would not do is rewrite the Python job into Go *for speed alone* without trying the library first. In this experiment that rewrite would have bought 4.5 s per run over Polars at the cost of 300 more lines and a second language in a team that had one.

## Related

- [Rust vs Go for a CLI Tool: Startup, Binary Size, Build Time and the Day-Two Costs]({% post_url Languages/2026-10-16-rust-vs-go-cli-tool %}) - Go measured against a language faster than it, with the same method.
- [Zig vs C for a Systems Tool]({% post_url Languages/2026-10-18-zig-vs-c-systems-tool %}) - the comparison one layer further down the stack.
- [Python vs Rust in a Hot Loop: What 10 Million Iterations Cost, Measured with hyperfine]({% post_url Performance/2026-10-07-python-vs-rust-hot-loop-performance %}) - the compute-bound case behind the Polars result here.
