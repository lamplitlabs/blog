---
layout: post
title: "Rust vs Go for a CLI Tool: Startup, Binary Size, Build Time and the Day-Two Costs"
date: 2026-10-16 00:00:00 +0200
categories: languages rust go
tags: rust go cli performance benchmark hyperfine tooling
author: manishtiwari25
description: "Rust 1.81 vs Go 1.23 for the same log-grep CLI: cold start, binary size, build time, memory, cross-compiling and the maintenance costs that decide it."
image:
  path: /assets/img/headers/languages/rust-vs-go-cli-tool.webp
  alt: "Bar chart comparing Rust and Go for the same CLI tool: cold start 1.1 ms vs 2.4 ms, binary size 3.2 MB vs 8.9 MB, clean build 41 s vs 2.8 s, peak RSS 14 MB vs 31 MB"
---

The [Python vs Rust hot loop]({% post_url Performance/2026-10-07-python-vs-rust-hot-loop-performance %}) and [Go vs .NET concurrency]({% post_url Performance/2026-10-11-go-vs-dotnet-goroutines-vs-tasks-concurrency-throughput %}) posts looked at raw runtime speed. A command-line tool asks a different question. Nobody notices whether a CLI finishes a 200 ms job in 180 ms or 250 ms; they notice whether it starts instantly, whether the binary they `curl` from a release page just runs, and whether the team can still add a flag a year later without an afternoon of fighting the compiler.

So I built the same small tool twice - `loggrep`, which scans a log file for a pattern, parses the timestamp on each matching line and prints a per-minute histogram - in Rust 1.81 and Go 1.23, and compared them on the axes that matter for a CLI: startup, binary size, build loop, memory, distribution and maintainability.

## The tool under test

- Positional args: a pattern and one or more file paths; flags for `--since`, `--json` and `--color`.
- Streams the file line by line; regex match, timestamp parse, bucket count.
- Input for the benchmark: a 1.2 GB, 9.4 million line application log.

Idiomatic stacks only: Rust with `clap`, `regex`, `memchr` and `anyhow`; Go with the standard `flag` package, `regexp` and `bufio`. Release builds (`cargo build --release` with `lto = "thin"`, `go build -ldflags='-s -w'`) on an Apple M2 laptop, re-checked on a Linux x86-64 box.

## Runtime: both are fast, Rust is faster

![Terminal screenshot of hyperfine comparing loggrep-rs at 184.3 ms mean against loggrep-go at 246.9 ms mean, 1.34 times faster, followed by ls -lh showing 3.2M and 8.9M binaries and clean build times of 41.02 s for cargo and 2.8 s for go build](/assets/img/headers/languages/rust-vs-go-cli-hyperfine-terminal.webp){: width="1200" height="700" }

| | Rust 1.81 | Go 1.23 |
|---|---|---|
| Scan 1.2 GB log (mean) | 184 ms | 247 ms |
| Cold start, `--help` | 1.1 ms | 2.4 ms |
| Peak RSS | 14 MB | 31 MB |
| Stripped binary | 3.2 MB | 8.9 MB |

Rust's edge comes from two places: `regex` with `memchr` prefilters is about 30% faster than Go's `regexp` on this literal-heavy pattern (the [regex engine comparison]({% post_url Performance/2026-10-15-regex-engine-performance-rust-go-dotnet-node %}) has the detail), and there is no garbage collector to warm up or runtime to initialise. The Go cold start includes spawning the scheduler and GC worker goroutines; 2.4 ms is still invisible to a human, and in shell-completion scripts or `git` hooks that call the tool hundreds of times it is the difference between 0.1 s and 0.25 s. Noticeable, not decisive.

## Build loop: Go wins by an order of magnitude

This is the number that surprised people on the team. A clean release build of the Rust version takes 41 seconds; the Go version takes under 3. Incremental debug builds narrow the gap (1.8 s Rust vs 0.6 s Go for a one-line change), but every CI run, every `cargo update` and every fresh clone pays the full price, mostly compiling `regex`, `clap` and their dependency tree.

Go's build is fast because the compiler does less: no monomorphisation of generics per call site, no LLVM optimisation passes to speak of, and a dependency tree that is a quarter the size because the standard library already covers flags, regex and buffered I/O.

| | Rust | Go |
|---|---|---|
| Clean release build | 41.0 s | 2.8 s |
| Incremental debug build | 1.8 s | 0.6 s |
| Direct dependencies | 5 | 0 |
| Transitive crates/modules | 38 | 0 |
| Lines of code | 412 | 356 |

## Distribution: static binaries both ways, with one catch

Both produce a single self-contained executable, which is the whole reason to pick either over Python or Node for a CLI. Cross-compiling is where they differ.

Go cross-compiles with two environment variables: `GOOS=linux GOARCH=arm64 go build` works from any host and produces a fully static binary by default when `cgo` is off. Six targets in one 20-second CI job.

Rust needs a target installed (`rustup target add x86_64-unknown-linux-musl`) and, for anything that links C, a cross linker. `cargo-zigbuild` or `cross` makes this painless, but it is a second tool to install and keep updated. For this tool, with no C dependencies, the `musl` target gave a 3.4 MB static binary that ran on every distro we tried.

## Error handling and maintainability

The code that changes most in a CLI is argument parsing and error reporting, so this is where day-two cost lives.

Rust with `clap`'s derive macros turns a struct into a parser with help text, validation, env-var fallbacks and shell completions, and the compiler rejects a flag that is read but never declared. Error paths use `?` with `anyhow` context, so the user sees `failed to open app.log: No such file or directory` with no extra code.

Go's `flag` package is smaller and shows it: subcommands, repeated flags and completions are hand-rolled or need `cobra`. Every I/O call is followed by `if err != nil { return fmt.Errorf("open %s: %w", path, err) }`, which is explicit and greppable but roughly doubled the line count of the file-handling code. On the other hand, a new contributor read the Go version end to end in ten minutes; the Rust version's lifetimes in the streaming iterator took longer to explain.

| | Rust | Go |
|---|---|---|
| Arg parsing | `clap` derive, completions included | `flag` stdlib; `cobra` for subcommands |
| Error ergonomics | `?` + `anyhow`/`thiserror` | explicit `if err != nil` |
| Compiler catches | lifetimes, exhaustiveness, unused results | unused imports and variables |
| Time to first contribution | hours (borrow checker) | minutes |

## Which would I pick?

For a tool that runs in a hot path - pre-commit hooks, shell prompts, build steps invoked thousands of times a day - or that processes gigabytes per invocation: Rust. The startup, memory and throughput wins are real, `clap` gives a better user-facing CLI for free, and a 41-second CI build is a fixed cost you pay once per change.

For an internal tool that a mixed team will own, that needs to ship for six platforms from one CI job, and where the workload is seconds rather than minutes: Go. The build loop and cross-compilation story are simply better, and the performance gap is one nobody will measure.

Either way, ship a static binary, strip it, and benchmark with `hyperfine` before arguing about the language. Most CLI slowness is unbuffered output or a regex compiled inside a loop, and both languages let you fix that in five minutes.

## Related

- [Python vs Rust in a Hot Loop: What 10 Million Iterations Cost, Measured with hyperfine]({% post_url Performance/2026-10-07-python-vs-rust-hot-loop-performance %}) - the raw compute side of the Rust numbers above.
- [Go Goroutines vs .NET Tasks: HTTP Concurrency Throughput, Measured with wrk]({% post_url Performance/2026-10-11-go-vs-dotnet-goroutines-vs-tasks-concurrency-throughput %}) - Go's runtime where it shines: servers, not short-lived processes.
- [Regex Engine Performance: Rust regex vs Go regexp vs .NET 8 Regex vs Node 22, Measured with hyperfine]({% post_url Performance/2026-10-15-regex-engine-performance-rust-go-dotnet-node %}) - why the Rust scan is 30% faster on a literal-heavy pattern.
- [TypeScript vs Kotlin for Backend Services]({% post_url Languages/2026-10-14-typescript-vs-kotlin-backend-services %}) - the other language comparison in this category.
