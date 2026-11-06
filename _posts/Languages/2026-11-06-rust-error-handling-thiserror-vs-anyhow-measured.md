---
layout: post
title: "Rust Error Handling: thiserror vs anyhow, Measured on One Parser"
date: 2026-11-06 00:30:00 +0100
categories: languages rust
tags: [rust, error-handling, thiserror, anyhow, backtrace, performance, benchmark]
author: manishtiwari25
description: "thiserror vs anyhow on one Rust log parser: ns per line, allocations per error, and why RUST_BACKTRACE=1 cost 2.6x at 5% bad lines."
image:
  path: /assets/img/headers/languages/rust-error-handling-thiserror-vs-anyhow.webp
  alt: "Header graphic for the Rust error handling post: median nanoseconds per log line at 5 percent bad lines on an Apple M2 Pro with rustc 1.95.0. thiserror 346 ns, anyhow 347 ns, anyhow with .context(format!()) 389 ns, anyhow with RUST_BACKTRACE=1 895 ns. Same parser, same error text, 200,000 lines per pass."
---

The usual advice for Rust errors fits in one line: **thiserror for libraries, anyhow for applications**. It is good advice, but it is about API design. It says nothing about cost, and the cost question comes up in every code review: "anyhow boxes every error, isn't that slow?" or "should this hot loop return a typed error instead?"

So I wrote one log-record parser four ways and measured them. The only difference between the versions is error handling. All four produce the same error text, byte for byte. The results:

- On the happy path, thiserror and anyhow cost the same: **347 vs 343 ns per line**.
- `.context(format!(...))` instead of `.with_context(|| ...)` costs **43 ns and one heap allocation on every line**, including lines that parse fine.
- When every line fails, anyhow costs **4 allocations (223 bytes) per error** and thiserror costs **0.5 allocations (4 bytes)**.
- None of that matters next to one environment variable. With `RUST_BACKTRACE=1` set, anyhow captures a stack backtrace for every error, about **10 µs each**. At 5% bad lines that made the parser **2.6x slower** (895 vs 347 ns per line).

Everything below comes from code in this blog's repository (`scripts/rust-error-handling/`). One command reproduces it.

## The program under test

`errbench` parses LLM gateway log records like this one:

```text
ts=17 route=/v1/chat model=qwen2.5-7b tokens=1173 latency_ms=205 status=200
```

A record can be wrong in four ways, each injected at a seeded rate: the `latency_ms` field is missing, `tokens` is not a number (`12x`), the model is unknown, or the status is out of range (`999`). The parser returns `Record` or an error, and the caller adds the line number.

### Version 1: thiserror end to end

```rust
#[derive(Debug, thiserror::Error)]
pub enum ParseError {
    #[error("missing field `{0}`")]
    Missing(&'static str),
    #[error("field `{field}` is not a number: {value:?}")]
    BadNumber { field: &'static str, value: String, #[source] source: ParseIntError },
    #[error("unknown model {0:?}")]
    UnknownModel(String),
    #[error("status {0} out of range 100..=599")]
    BadStatus(u16),
}

#[derive(Debug, thiserror::Error)]
#[error("line {line}")]
pub struct AtLine { line: usize, #[source] source: ParseError }

fn call_typed(n: usize, l: &str) -> Result<Record, AtLine> {
    parse_typed(l).map_err(|source| AtLine { line: n, source })
}
```

### Version 2: anyhow end to end

```rust
fn num_anyhow<T: FromStr<Err = ParseIntError>>(line: &str, key: &'static str) -> anyhow::Result<T> {
    let v = field(line, key).with_context(|| format!("missing field `{key}`"))?;
    v.parse().with_context(|| format!("field `{key}` is not a number: {v:?}"))
}

fn call_anyhow(n: usize, l: &str) -> anyhow::Result<Record> {
    parse_anyhow(l).with_context(|| format!("line {n}"))
}
```

### Version 3: anyhow with eager context

This is the same as version 2, except for one call site. It is a mistake I see in real code review, because it reads almost the same:

```rust
fn call_eager(n: usize, l: &str) -> anyhow::Result<Record> {
    parse_anyhow(l).context(format!("line {n}"))   // format! runs on Ok too
}
```

### Version 4: the hybrid

The parser returns the thiserror enum, and the application boundary wraps it with anyhow. This is what the "thiserror for libraries, anyhow for applications" advice gives you once both sides live in one workspace:

```rust
fn call_hybrid(n: usize, l: &str) -> anyhow::Result<Record> {
    parse_typed(l).with_context(|| format!("line {n}"))
}
```

The harness renders every error the way a log line would show it: anyhow with `{:#}`, and the typed error by walking `source()`. It hashes the text, and all four versions print the same checksum at every fault rate (`78501099a914bba9` at 5%). `summarise.py` asserts that, so no version wins by doing less work.

**Test machine:** Apple M2 Pro, macOS 27.0.1, rustc 1.95.0, anyhow 1.0.104, thiserror 2.0.21, `cargo build --release`. Each run times five passes over 200,000 lines and keeps the median. Five runs are interleaved across all versions, so host load hits them alike, and I report the median of those five. In 30 of the 32 cells, the median absolute deviation across the five runs was under 1% of the median. The noisiest cell was anyhow at 1% bad lines, at 3.9%. Single runs did jump by up to 10% when the host was busy.

## What the reader of the error sees

Before the numbers, here is what each version gives you for one bad line:

![Terminal output of errbench show for the input line ts=17 with tokens=12x. thiserror Display prints only "line 17"; walking source() gives "line 17: field tokens is not a number: 12x: invalid digit found in string"; its Debug output is the nested struct AtLine { line: 17, source: BadNumber { field: tokens, value: 12x, ... } }. anyhow {:#} prints the same one-line chain, and {:?} prints "line 17" with a numbered "Caused by" list. The hybrid prints the same chain and downcast_ref::<ParseError>() returns BadNumber { field: tokens }, while the pure anyhow error's downcast_ref returns None.](/assets/img/posts/languages/rust-error-handling-show.webp)

Three things are worth noticing:

1. **`{}` on either type prints only the outer layer** (`line 17`). With anyhow you want `{:#}` in logs. With a thiserror type, you need a helper that walks `source()`. A one-line `tracing::error!("{e}")` loses the cause either way.
2. **The anyhow-only version cannot be matched on.** `downcast_ref::<ParseError>()` returns `None` because the parser never built a `ParseError`; the cause is a string. In the hybrid, the same call returns `BadNumber { field: "tokens" }`, so a caller can decide to retry or skip a line without parsing message text.
3. **thiserror's `Debug` output is the struct**, not a report. That is fine in a test failure and noisy in a log.

## Cost per line, with and without backtraces

![Line chart of median nanoseconds per log line against the share of lines that fail to parse (0, 1, 5, 25 and 100 percent), 200,000 lines, median of 5 runs. Left panel, backtrace capture off: thiserror end to end goes from 347 to 313 ns, the hybrid from 346 to 385, anyhow with .with_context from 343 to 413, and anyhow with .context(format!()) stays highest at 386 to 416. Right panel, RUST_LIB_BACKTRACE=1: the hybrid, anyhow and eager anyhow rise from 343 to 386 ns at 0 percent to 441 to 496 ns at 1 percent, 825 to 939 ns at 5 percent, and 2,778 to 3,174 ns at 25 percent.](/assets/img/posts/languages/rust-error-handling-cost-per-line.webp)

Read the left panel first, because that is how most services run:

- **At 0-5% bad lines, thiserror, anyhow and the hybrid are within a few nanoseconds of each other** (343-351 ns, apart from one noisy 359 ns cell for anyhow at 1%). The work of parsing the line dominates. Neither boxing nor the enum shows up.
- **thiserror gets *faster* as more lines fail** (347 → 313 ns at 100%). A failed parse returns early and skips the remaining fields, and building the error costs almost nothing. Two of the four fault kinds allocate nothing at all.
- **anyhow gets slower as more lines fail** (343 → 413 ns at 100%). Each error is a heap-allocated object plus one more `format!` for every context layer. When every line fails, that is 70 ns more per line than when none do, and 32% slower than thiserror on the same input.
- **Eager `.context(format!(...))` is the one version that costs on the happy path**: 386 ns with no errors at all, 11-13% slower than the others. `format!` runs and allocates a `String` before `.context` knows whether there is an error. Clippy 0.1.95 does not flag it, even with `-W clippy::or_fun_call -W clippy::pedantic` (I ran both on this crate), so code review has to catch it. Use `with_context(|| ...)` whenever the message is formatted.

Now the right panel. anyhow captures a `std::backtrace::Backtrace` when an error is created, **if** `RUST_LIB_BACKTRACE=1` or `RUST_BACKTRACE=1` is set. Capture means unwinding the stack. On this machine that cost **9-11 µs per error**, regardless of how the error was built. Compared with the same version with capture off, per-line cost rose 26-28% at 1% bad lines, 2.4-2.6x at 5%, and 7.7-8.6x at 25%. (I left the 100% cell out of the backtrace runs.) The thiserror version has no line here: on stable Rust, a thiserror type captures a backtrace only if you add a `Backtrace` field yourself.

The hybrid is a little cheaper than pure anyhow with backtraces on (825 vs 895 ns at 5%). Both capture exactly one backtrace per error: switching capture on adds 3 allocations per error to each, in the table below. I did not profile where the remaining 70 ns goes. Either way, the capture dominates.

## Which environment variable turns it on

`RUST_BACKTRACE=1` is the variable people set to get a useful panic message. It is in a lot of Dockerfiles, CI configs and systemd units. anyhow reads it too:

| Environment (anyhow version, 5% bad lines) | ns per line |
|---|---:|
| neither variable set | 348 |
| `RUST_BACKTRACE=1` | 896 |
| `RUST_LIB_BACKTRACE=1` | 895 |
| `RUST_BACKTRACE=1 RUST_LIB_BACKTRACE=0` | 348 |

The last row is the fix. `RUST_LIB_BACKTRACE=0` turns capture off for library errors (anyhow, and `std::backtrace::Backtrace::capture` in general) and leaves `RUST_BACKTRACE=1` working for panics. If a service turns malformed input into anyhow errors in a loop, check its environment before you check its code.

## What one error costs in memory

![Table of heap allocations and bytes per error, measured with a counting global allocator over 20,000 lines that all fail. Backtrace off: thiserror 0.5 allocations and 4 bytes, the hybrid 2.5 and 142, anyhow with .with_context 4 and 223, anyhow with .context(format!()) 3 and 213 but also 1 allocation on every successful line. Backtrace on: the hybrid 5.5 allocations and 1,710 bytes, anyhow 7 and 1,791, eager anyhow 6 and 1,781. anyhow at 5 percent bad lines by environment: unset 348 ns, RUST_BACKTRACE=1 896 ns, RUST_LIB_BACKTRACE=1 895 ns, both with LIB set to 0 348 ns. Formatting one anyhow error with {:?} takes 0.3 microseconds without a backtrace and 30 microseconds with one, 2.8 ms the first time because of symbolication. Clean release build of a one-file crate: no dependencies 0.2 s, anyhow 0.7 s, thiserror 2.0 s, both 1.9 s; stripped binary 34 KiB larger with anyhow and 0.4 KiB larger with thiserror.](/assets/img/posts/languages/rust-error-handling-allocs-table.webp)

The allocation counts explain the timings:

- **thiserror: 0.5 allocations per error.** Only `BadNumber` and `UnknownModel` own a `String`, and they are half of the injected faults. A `Result<Record, AtLine>` is 56 bytes on the stack, which is the price of carrying the error inline. `anyhow::Result<Record>` is 16 bytes, because `anyhow::Error` is one pointer.
- **anyhow: 4 allocations per error.** There are two layers (the parser's message and the caller's `line 17`), and each layer is one formatted `String` plus one boxed error object.
- **With a backtrace, about 1,570 more bytes per error.** That is the captured frames. They are kept unresolved until something prints them. Printing is a cost of its own. `format!("{e:?}")` on one error took 0.3 µs without a backtrace and **30 µs** with one. The first print in a process took **2.8 ms** while the symbol tables loaded. It also produced 3,705 bytes of text instead of 101.

That text is what your log pipeline receives every time someone writes `error!("{e:?}")`:

![Terminal output of the same anyhow error printed with {:?} and RUST_LIB_BACKTRACE=1: "line 17", a Caused by list with field tokens is not a number 12x and invalid digit found in string, then a Stack backtrace whose frames walk from std backtrace_rs and anyhow's ext_context and with_context through errbench num_anyhow, parse_anyhow and call_anyhow with file and line numbers, followed by a note that 25 more lines were cut: 23 frames and 3,705 bytes for one error.](/assets/img/posts/languages/rust-error-handling-backtrace.webp)

A backtrace is the right thing to have when an error should never happen: a failed migration, a corrupt state file, a bug. It is the wrong thing to pay for 50,000 times an hour because users send malformed input. That is the practical reason to keep **expected** failures in a typed error, which never captures one, and to keep anyhow for the unexpected ones.

## What a typed error buys the caller

Speed does not decide this choice. Two things do: who reads the error, and whether code has to branch on it. Here is the strongest argument for thiserror in a library. A caller matches on the enum to decide whether to page someone. Then the library adds a variant:

![Terminal output of cargo build after a Truncated(usize) variant was added to the thiserror ParseError enum: rustc error E0004, non-exhaustive patterns, &ParseError::Truncated(_) not covered, pointing at the match in should_page at src/main.rs line 16 and at the new variant on line 11, with a help line suggesting a new match arm.](/assets/img/posts/languages/rust-error-handling-e0004.webp)

Every caller that branches on the error gets a compile error that names the new case. With anyhow, the equivalent caller is `if msg.contains("unknown model")`. When the message changes, that code keeps compiling and quietly takes the wrong branch. If your library is public and you want to be able to add variants without breaking callers, mark the enum `#[non_exhaustive]`. Callers then need a `_` arm, so you trade this check for semver room on purpose.

## Build time and binary size

The other cost people quote is compile time. Here it is for a one-file crate, clean release build, median of 3:

| Dependencies | Clean release build | Stripped binary |
|---|---:|---:|
| none | 0.2 s | 342,000 bytes |
| anyhow | 0.7 s | 376,688 bytes |
| thiserror | 2.0 s | 342,400 bytes |
| both | 1.9 s | 376,720 bytes |

thiserror is a proc macro, so the first build compiles `syn`, `quote` and `proc-macro2`. That takes about 1.8 s here. A real project very likely pulls `syn` in already through serde, clap or tokio, and then thiserror adds almost nothing. Incremental builds do not pay it again. Its runtime footprint is close to zero: the derive expands to plain `Display` and `Error` impls. anyhow adds about 34 KiB to a stripped binary, mostly its backtrace and formatting support.

## What I would do

- **Library crates, or any module whose callers branch on failure:** use a thiserror enum. Keep the variants about what the caller can do, not about which function failed. Add `#[non_exhaustive]` when the crate is public.
- **Binaries, CLIs and request handlers:** use `anyhow::Result` at the top, and use `.with_context(|| ...)` to add what the code was doing ("line 17", "loading config.toml"). This is the hybrid, and it measured as cheap as either pure version on the happy path.
- **Never write `.context(format!(...))`.** It is the only variant that costs on every line.
- **Log with `{:#}`** for one line, or `{:?}` only where you want the backtrace.
- **Set `RUST_LIB_BACKTRACE=0` next to `RUST_BACKTRACE=1`** in any service where an error is an expected outcome rather than a bug.
- **Do not move an expected, high-rate failure into anyhow** because it is shorter to write. Parse errors, validation failures and "not found" belong in a typed error that never captures a stack. In this benchmark the crate choice only mattered once errors were common: 6% at 25% bad lines, 32% when every line failed, and 2.6x at 5% the moment a backtrace was captured.

*We follow this split (typed errors inside, anyhow at the edges) in the Rust services behind Lamplit Labs' products. Measuring a change against a baseline before accepting it is also at the core of **Pulse**, Lamplit Labs' self-improving automation product, coming soon.*

## Reproduce it

```bash
# needs a Rust toolchain and python3 (Pillow only for the images)
bash scripts/rust-error-handling/measure.sh /tmp/errbench-work      # about 3 minutes
python3 scripts/rust-error-handling/summarise.py /tmp/errbench-work  # -> scripts/data/rust-error-handling-m2pro.json
python3 scripts/gen_rust_error_handling_images.py /tmp/errbench-work
```

`measure.sh` writes the raw per-run TSVs, the `show` and backtrace output, the E0004 compiler output and the build-time probes. `summarise.py` refuses to write the JSON if any two versions render different error text at the same fault rate. Absolute numbers will differ on your machine. Expect the same pattern: no difference on the happy path, a fixed cost per eager `format!`, and microseconds per error once a backtrace is captured.

## Related

- [Rust vs Go Error Handling in AI Agent Tool Calls](/posts/rust-vs-go-error-handling-ai-agent-tool-calls/): the same question about taxonomy, measured as bugs caught instead of nanoseconds.
- [Rust Profiling Practical Guide: sample, Flame Graphs and a Counting Allocator](/posts/rust-profiling-practical-guide-sample-flamegraph/): the counting allocator used for the allocation table above.
- [Rust Ownership for .NET Developers](/posts/rust-ownership-for-dotnet-developers/): why `String` vs `&str` fields in an error type change what it costs to build.
- [Rust vs Go for a CLI Tool](/posts/rust-vs-go-cli-tool/): where anyhow-style error handling usually ends up.
- [Pulse: Lamplit Labs' self-improving automation product, coming soon](/posts/pulse-internal-rsi-tool/): the product mentioned above.
