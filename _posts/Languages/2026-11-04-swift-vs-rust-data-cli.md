---
layout: post
title: "Swift vs Rust for a Data-Crunching CLI: Where Idiomatic Swift Loses 5x and How Much You Get Back"
description: "Swift 6.1 vs Rust 1.90 aggregating a 5M-row, 247 MB CSV: wall time, peak RSS, build time and binary size measured, plus the one Swift habit that costs 5x."
date: 2026-11-04 00:00:00 +0200
categories: languages swift rust
tags: swift rust performance benchmark cli csv memory build-time
author: manishtiwari25
image:
  path: /assets/img/headers/languages/swift-vs-rust-data-cli.webp
  alt: "Bar chart comparing Swift idiomatic, Swift byte-level and Rust for the same 5M-row CSV aggregation: wall time 8.40 vs 2.47 vs 1.57 s, peak RSS 355 vs 309 vs 290 MB, clean build 1.6 vs 1.6 vs 3.0 s, binary 80 vs 78 vs 487 KB"
---

The earlier posts in this series put [Rust against Go]({% post_url Languages/2026-10-16-rust-vs-go-cli-tool %}) for a CLI and [Zig against C]({% post_url Languages/2026-10-18-zig-vs-c-systems-tool %}) for a proxy. This one looks at a pairing that comes up on Apple-heavy teams: a tool that already exists as a Swift script, and the question of whether rewriting it in Rust is worth the trouble. Swift has had a server and command-line story for years, ships with every Mac, and compiles to native code with ARC instead of a garbage collector. On paper it should sit close to Rust.

So, same method as before: one small program written twice (then a third time), one input, numbers from `/usr/bin/time -l`, no frameworks.

## The tool

`agg` reads a CSV of service calls - `ts,region,service,status,latency_ms,amount` - groups rows by `region|service`, and prints the row count, the p50 latency and the summed amount per group. The input is 5,000,000 generated rows, 247 MB, 48 groups. That is the shape of a lot of internal tooling: a log export or a billing dump that is too big for a spreadsheet and too small to justify a Spark job.

Three versions, all single-threaded and all producing byte-identical output (checked with `md5`):

- **Swift, idiomatic** - read the file into `Data`, walk the bytes to find line ends, build a `String` per line, `split(separator: ",")`, `Int(...)`/`Double(...)` on the fields, a `[String: Acc]` dictionary. The code you would write first.
- **Swift, byte-level** - same loop, but no `String` per line: find comma offsets in the raw `UInt8` buffer, parse the integer and decimal by hand, key the dictionary on `[UInt8]`.
- **Rust** - `std::fs::read`, `split(|&b| b == b'\n')`, `str::split(',')`, `parse()`, a `HashMap<String, Acc>`. Also the code you would write first; nothing from crates.io.

Toolchain: Swift 6.1 (`swiftc -O`) and Rust 1.90 (`cargo build --release`, thin LTO, one codegen unit), Apple M2 Pro, macOS. Each timing is the median of five runs on a warm file cache.

## The numbers

![Table comparing Swift idiomatic, Swift byte-level and Rust for aggregating a 5,000,000-row CSV: wall time 8.40 s vs 2.47 s vs 1.57 s, min/max 7.93-8.55 vs 2.35-3.73 vs 1.35-1.64 s, peak RSS 355 vs 309 vs 290 MB, clean build 1.6 vs 1.6 vs 3.0 s, stripped binary 80 vs 78 vs 487 KB, 40 vs 55 vs 42 lines of code, identical output](/assets/img/posts/languages/swift-vs-rust-csv-aggregation-table.webp){: width="1200" height="520" }
_Rust's first draft is 5.3x faster than Swift's first draft. Swift gets within 1.6x once you stop allocating a String per line - at the cost of code nobody enjoys reading._

Three things stand out.

**The idiomatic Swift version is slow for one reason, and it is not ARC in general.** Profiling with `sample` shows most of the 8.4 s inside `String` construction and `Substring` splitting: each of the 5 million lines becomes a heap-allocated, UTF-8-validated `String`, then six `Substring` views, then `Int(Substring)` and `Double(Substring)` which go through generic text parsing. Rust does the same UTF-8 validation (`from_utf8`) but `&str` slices borrow the buffer, so the per-line cost is a bounds check, not an allocation. Swift *can* express that - the byte-level version proves it - but the language steers you toward the `String` API first.

**Memory is a wash.** All three hold the 247 MB input plus 5 million `Int32`/`Int` latencies for the p50, so the floor is around 270 MB. Swift idiomatic peaks 65 MB higher because of transient `String` garbage between ARC releases; the byte-level Swift version is within 20 MB of Rust. If you were expecting a GC-vs-ownership gap, there isn't one here - Swift's ARC frees eagerly.

**Build time and binary size go the other way.** `swiftc -O` finishes in 1.6 s against 3.0 s for a clean `cargo build --release` with LTO, and the Swift binary is 80 KB because the Swift runtime is a shared library on macOS. The Rust binary is 487 KB with its statically linked std. On Linux the picture flips: a Swift binary either needs the toolchain's runtime libraries alongside it or `-static-stdlib`, which pushes it past 5 MB, while the Rust binary stays a single self-contained file.

Run-to-run variance is also worth a note: the byte-level Swift build ranged 2.35-3.73 s across five runs, while Rust stayed within 1.35-1.64 s. The slow Swift runs line up with dictionary growth - `[[UInt8]: Acc]` rehashes copy the array keys - whereas Rust's `HashMap<String, _>` moves pointers.

## What this means for the choice

- **Existing Swift tool, Mac-only users, runs occasionally:** keep it in Swift, and fix the hot loop. Dropping per-line `String` construction gave 3.4x here with a 15-line change. That is a smaller diff than a rewrite.
- **Tool runs on Linux CI or in a container:** Rust. Distribution is one static binary, the standard library's string handling is zero-copy by default, and you don't have to fight the idioms to get there.
- **Team already fluent in Swift, no Rust experience:** the 1.6x residual gap between tuned Swift and first-draft Rust is real but rarely decisive for a batch tool. The 5.3x gap between *first drafts* is what bites, and it is a code-review item, not a language verdict.
- **Latency-sensitive or memory-constrained:** Rust's predictability (narrow min/max spread) matters more than the median. Swift's ARC and copy-on-write collections produce occasional outliers that are hard to see in a single run.

The honest summary: Swift is not slow, but idiomatic Swift string code is, and the language does not warn you. Rust's defaults put you on the fast path before you know you need it.

## Related

- [Rust vs Go for a CLI Tool: Startup, Binary Size, Build Time and the Day-Two Costs]({% post_url Languages/2026-10-16-rust-vs-go-cli-tool %}) - same method, with Rust on the other side of the comparison.
- [Zig vs C for a Systems Tool]({% post_url Languages/2026-10-18-zig-vs-c-systems-tool %}) - the systems-level comparison in this category, where binary size and cross-compiling dominate.
- [Python vs Go for a Batch Log Job]({% post_url Languages/2026-10-20-python-vs-go-batch-log-job %}) - the same kind of workload one tier up, where the interpreter rather than string allocation is the cost.
