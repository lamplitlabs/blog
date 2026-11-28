---
layout: post
title: "Rust PGO vs Go PGO on the Same Log Router: Fewer Instructions, More Cycles, Measured"
date: 2026-11-23 07:00:00 +0000
categories: performance rust go
tags: [rust, go, pgo, compiler, inlining, llvm, profiling, performance, benchmark]
author: manishtiwari25
description: "Rust PGO vs Go PGO on one log router: rustc -Cprofile-use cut 4.3% of instructions but cost 2.8-8.5% more cycles. Go -pgo saved both."
image:
  path: /assets/img/headers/performance/rust-pgo-vs-go-pgo.webp
  alt: "Header graphic for the Rust PGO vs Go PGO post. Change per routed log line against each language's default build, api config, median of 10 runs on an M2 Pro with rustc 1.95.0 and go1.27.4. Go -pgo: instructions -8.7%, cycles -4.0%. Rust -Cprofile-use: instructions -4.3%, cycles +2.8%. Rust fat LTO without PGO: instructions -4.4%, cycles -2.5%. Rust PGO ran fewer instructions but IPC fell from 3.93 to 3.65. All 12 builds print the same checksum per config."
---

Our [Go PGO post](/posts/go-pgo-profile-guided-optimization-measured/) measured `go build -pgo` on a small log router. It cut 8.8-10% of instructions per line, and all of that came from inlining hot call sites. The obvious next question: what does Rust's PGO do with the same program?

Rust PGO is LLVM's instrumentation PGO. You build an instrumented binary, run it, merge the raw profiles, and rebuild with `-Cprofile-use`. It is more work than Go's "pass a pprof file", and it can do more: LLVM uses the profile for inlining, indirect-call promotion, block layout, branch weights and memcpy specialisation. So we expected a bigger win.

We did not get one. On this workload, Rust PGO removed 4.3% of instructions. It also made each line **2.8% slower in cycles on the config it was trained on, and 8.5% slower on the other one**. Go's PGO, with the same profile shape, saved both instructions and cycles. This post shows the measurements, the compiler output that explains them, and the one-line change that removes the slowdown.

Everything here is in this blog's repository under `scripts/rust-pgo/`: the Rust crate, the measurement script, the summariser and the image generator. Every number comes from `scripts/data/rust-pgo-vs-go-m2pro.json`.

## The workload: the same log router, twice

The Go program is `scripts/go-pgo/logroute` from the Go PGO post, unchanged. The Rust program in `scripts/rust-pgo/logroute` is a line-by-line port with no dependencies, built with `cargo build --release --offline`:

- `scan_fields` splits `key=value` lines (some values quoted) and `set_field` stores ten known fields in a `Record` of borrowed byte slices.
- A rule table of `Box<dyn Matcher>` (Go: `Matcher` interfaces) picks a sink. The **api** config has 11 rules, mostly route-prefix matchers. The **batch** config has 8 rules, mostly status and level matchers.
- Sinks are `Box<dyn Sink>`. `HistSink` keeps a per-route latency histogram in a `HashMap<u64, Box<RouteStats>>`, keyed by an FNV hash of the service and the route with digits folded.

The Go generator writes 1,000,000 seeded lines per config (143 MB each). Both programs read the same files and print the same checksum: `11463464160021572079` for api and `124650555801876366` for batch. All 12 builds in this post agree, so no build wins by doing less work.

Rust starts ahead. The default release build runs **15.9% fewer instructions and 7.3% fewer cycles per line than Go** on api (18.4% and 12.6% on batch). That fits our earlier [Rust vs Go CPU-bound microservice](/posts/rust-vs-go-cpu-bound-microservice/) numbers. The question here is only what PGO adds on top of each.

**Test machine:** Apple M2 Pro, macOS 27.0.1, rustc 1.95.0 (LLVM 22.1.2), go1.27.4 darwin/arm64, llvm-profdata from Homebrew llvm@22.

## How we measured

The Mac was shared with other jobs (load average 6 to 11), so wall time is not the main number. We used the hardware counters that `/usr/bin/time -l` prints on macOS, the method from the [Rust profiling guide](/posts/rust-profiling-practical-guide-sample-flamegraph/):

- **Instructions retired** is almost deterministic for one binary and input. Across 10 runs it varied by at most 0.34% in every cell.
- **Cycles elapsed** is the work the core actually did, including stalls. It varied by 1.9-4.6% between the fastest and slowest of 10 runs per cell, so a difference of 1-2% in the medians is noise. The differences we report as real were also present in two earlier full runs of the script.

Each run is 5 passes over 1,000,000 lines. We subtract the counters of a `reps=0` run (load the file, route nothing) and divide by 5,000,000. Each (build, config) cell has 10 runs, interleaved so that host load drifts over all builds alike. Tables show medians.

```bash
bash scripts/rust-pgo/measure.sh /tmp/rust-pgo       # ~5.5 min: profiles, 12 builds, 240 timed runs, remarks
python3 scripts/rust-pgo/summarise.py /tmp/rust-pgo  # -> scripts/data/rust-pgo-vs-go-m2pro.json
python3 scripts/rust-pgo/gen_images.py /tmp/rust-pgo # every image on this page
```

## Step 1: the Rust PGO loop

Go reads a normal CPU profile. Rust needs a separate instrumented build, and the merge tool must come from the same LLVM major version as `rustc` (`rustc -vV | grep LLVM`). The usual way to get one is `rustup component add llvm-tools`. We used Homebrew's `llvm@22` because it was already installed.

```bash
# 1. instrumented build: every function and branch gets a counter
RUSTFLAGS="-Cprofile-generate=/tmp/pgo/api" cargo build --release
./target/release/logroute run api api.log 10       # writes /tmp/pgo/api/*.profraw

# 2. merge the raw profiles into one .profdata (17.9 KB here)
llvm-profdata merge -o /tmp/pgo/api.profdata /tmp/pgo/api

# 3. optimised build that reads the profile
RUSTFLAGS="-Cprofile-use=/tmp/pgo/api.profdata" cargo build --release
```

Two costs that Go does not have:

- **The instrumented binary is slow.** It ran at 303 ns per line on api, against 209 ns for the normal build, so 45% slower (48% on batch). That is fine for a load test. It is usually too slow to run in production, so the profile comes from a synthetic or replayed workload, not from real traffic.
- **It is a two-stage build.** A clean release build took 0.43 s, the instrumented one 0.47 s and the PGO one 0.41 s. That is cheap for this crate, but CI has to run the workload between the two builds. Go's PGO build (2.22 s with `-a`, standard library included) took no longer than its normal build (2.34 s).

There is one warning to know about. The instrumented run printed `LLVM Profile Warning: Unable to track new values: Running out of static counters`. Value profiling (the data behind indirect-call promotion and memcpy specialisation) has a few slots per call site. Our rule loop calls five matcher types from one site, so some targets were not recorded. `-Cllvm-args=-vp-counters-per-site=<n>` raises the limit. We kept the default, because that is what most people will run.

## Step 2: the numbers

![Results table for the api config. Instructions per routed line, change, cycles per line, change, IPC and ns per line for 12 builds, each compared with its own language's default build. Go default 3,321 instructions and 767 cycles. Go -pgo 3,032 (-8.7%) and 737 (-4.0%). Rust release 2,793 and 711. Rust fat LTO 2,670 (-4.4%) and 694 (-2.5%). Rust -Cprofile-use 2,672 (-4.3%) and 731 (+2.8%), IPC 3.65. Rust PGO with fat LTO 2,568 (-8.1%) and 725 (+2.0%). Rust PGO with -disable-icp 2,728 (-2.3%) and 746 (+4.9%). With -disable-memop-opt 2,672 (-4.3%) and 734 (+3.1%). With ext-TSP block layout 2,667 (-4.5%) and 725 (+1.9%). With HistSink::write marked inline(never) 2,790 (-0.1%) and 714 (+0.4%). 1% profile 2,703 (-3.2%) and 734 (+3.2%). Batch-trained profile 2,810 (+0.6%) and 762 (+7.1%).](/assets/img/posts/performance/rust-pgo-vs-go-results.webp)

The same cells as text, with both configs. The profile was always taken on the **api** config, except in the last row.

| Build (vs its own default) | api instr | api cycles | batch instr | batch cycles |
|---|---:|---:|---:|---:|
| Go `-pgo` | **-8.7%** | **-4.0%** | **-10.0%** | **-4.9%** |
| Rust fat LTO + 1 codegen unit, no PGO | -4.4% | -2.5% | -4.8% | -3.6% |
| Rust `-Cprofile-use` | -4.3% | +2.8% | -0.8% | +8.5% |
| Rust PGO + fat LTO | -8.1% | +2.0% | -5.3% | +7.7% |
| Rust PGO, indirect-call promotion off | -2.3% | +4.9% | -2.7% | +7.3% |
| Rust PGO, memop specialisation off | -4.3% | +3.1% | -0.9% | +8.9% |
| Rust PGO, ext-TSP block layout | -4.5% | +1.9% | -0.9% | +9.4% |
| Rust PGO, `HistSink::write` `#[inline(never)]` | -0.1% | +0.4% | -0.2% | +1.0% |
| Rust PGO, profile from 10,000 lines (1%) | -3.2% | +3.2% | -0.2% | +8.7% |
| Rust PGO, profile from the batch config | +0.6% | +7.1% | -2.7% | +3.6% |

Four things stand out:

1. **Go's PGO is a clean win here; Rust's is not.** Both cut instructions, but only Go also cut cycles. Rust's PGO build retired fewer instructions per cycle: IPC fell from 3.93 to 3.65 on api and from 4.19 to 3.83 on batch.
2. **Plain fat LTO beat PGO.** `lto = "fat"` with `codegen-units = 1` (a Cargo profile, no profile data) gave the same 4.4% fewer instructions *and* 2.5-3.6% fewer cycles. It costs a 2.5 s build instead of 0.4 s. Our [release-profile post](/posts/rust-lto-codegen-units-release-profile/) covers those knobs.
3. **A profile from the wrong traffic hurts more in Rust.** The api-trained build was 8.5% slower in cycles on batch traffic. The batch-trained build was 7.1% slower on api. In the Go post, a profile from the other config still gave the full gain.
4. **Turning off single LLVM features did not fix it.** No indirect-call promotion, no memop specialisation, or a different block-layout algorithm all left the cycle loss in place. Only one change removed it, and it is a source change: the `inline(never)` row.

## Step 3: what each compiler did with the profile

Both compilers can report their PGO decisions. For `rustc` it is `-Cremark=pgo-icall-prom -Cremark=inline` (pass the flag once per pass name: `-Cremark=a,b` printed nothing for us). For Go it is `-gcflags=-m` and `-d=pgodebug=1`.

![Compiler decisions with the api profile. rustc -Cremark=pgo-icall-prom: main.rs:312 promote RoutePrefix as Matcher::matches with count 55441660 out of 67714450; main.rs:312 promote SlowerThan as Matcher::matches with count 10000000 out of 12272790; main.rs:313 promote HistSink as Sink::write with count 10000000 out of 10050800. go build -pgo: devirtualize ru.M.Match to (*routePrefix).Match at main.go:276 and rt.sinks[ru.Sink].Write to (*histSink).Write at main.go:277, then hot-budget inlines of Router.Route into main, histSink.Write and scanFields into Router.Route, and setField into scanFields. rustc inlining remarks in the crate went from 57 to 49 inlined and 35 to 59 not inlined.](/assets/img/posts/performance/rust-pgo-vs-go-compiler-decisions.webp)

Both compilers made the same first move. They guarded the two hottest dynamic calls, `RoutePrefix::matches` and `HistSink::write`, with a type check followed by a direct call. LLVM calls this indirect-call promotion; Go calls it devirtualization. In both, the direct call could then be inlined.

The difference is what each did next:

- **Go** inlined the four hottest functions into their callers, the chain `setField → scanFields → Route → main`, and kept `histSink.Write` inside `Route`. In the Go post, disabling devirtualization changed nothing and disabling inlining removed the whole gain. Go's inliner runs on a small budget and PGO raises it only for these hot sites.
- **rustc** already inlines the parser and matchers into `main` without a profile; Rust's default release build is more aggressive than Go's. With the profile, LLVM went further. It inlined the promoted `HistSink::write` (with the FNV route hash, the hashbrown `entry` lookup and the histogram update) into the middle of the rule loop in `main`. Elsewhere it inlined *less*: cold paths in setup and teardown were left as calls (the `inline (missed)` count went from 35 to 59), which is PGO working as designed.

## Step 4: where the cycles went

The flame graphs come from `/usr/bin/sample` (no root needed), folded and drawn with the scripts from the [Rust profiling guide](/posts/rust-profiling-practical-guide-sample-flamegraph/), then screenshotted with headless Chromium:

![Two CPU flame graphs of logroute on the api config, from /usr/bin/sample 4 s at 1 ms. Top, default release build, 2,979 samples: logroute::main with separate frames for HistSink as Sink::write, hashbrown rustc_entry, RoutePrefix as Matcher::matches and _platform_memcmp. Bottom, PGO build, 2,942 samples: a single wide logroute::main frame with only _platform_memcmp beside it, because every hot callee was inlined.](/assets/img/posts/performance/rust-pgo-vs-go-flamegraphs.webp)

In the default build, `main` holds 61.9% of samples as self time. The rest is `HistSink::write` (18.3%), the hash-map entry (5.9%), `RoutePrefix::matches` (3.7%) and `memcmp` (9.9%). In the PGO build, `main` holds 89.2% and only `memcmp` (10.8%) is still a separate function. The profile does not say which instructions got slower. It does show that PGO moved the histogram update, the hash and the map probe into the same function as the parser and the rule loop.

The code size barely moved: `logroute::main` grew from 7,460 to 8,136 bytes, and the whole `__text` section by 0.5%. So this is not instruction-cache pressure. It also is not a block-layout problem, because the ext-TSP layout did not help. The likely cause is that the loop body got harder for the core to overlap. The hash chain, the map probe and the histogram update now sit in the loop that also parses the next line. With a separate `write` call, the out-of-order core seems to have overlapped them better (IPC 3.93 against 3.65). We did not prove the exact stall: macOS gives no per-event PMU counters without root or Instruments, and we did not use either here.

The direct test is to keep only that function out of line and leave everything else to PGO:

```rust
impl Sink for HistSink {
    #[cfg_attr(feature = "outline-write", inline(never))]
    fn write(&mut self, r: &Record) { /* unchanged */ }
}
```

With the same profile, that build is back to the default build's cycles: +0.4% on api and +1.0% on batch, both within noise. Its instructions also return to the default level (-0.1%). So on this workload, almost all of the PGO instruction saving came from that one inline, and so did all of the cycle loss. Fewer instructions is not the same thing as faster.

## Rust PGO vs Go PGO: the practical differences

| | Go `-pgo` | Rust `-Cprofile-use` |
|---|---|---|
| Profile source | any CPU profile, including production `pprof` | an instrumented build (45-48% slower here), run on a representative workload |
| Extra tools | none | `llvm-profdata` of the same LLVM major as `rustc` |
| What uses the profile | inlining budget, devirtualization | inlining, indirect-call promotion, block layout, branch weights, memop size specialisation, and more |
| Default without a profile | conservative inliner, so there is a lot to gain | aggressive inliner already, so there is less to gain and more room to overshoot |
| Wrong-traffic profile, this workload | still the full gain (Go post) | 7.1-8.5% more cycles |
| Result here | -8.7 to -10.0% instructions, -4.0 to -4.9% cycles | -0.8 to -4.3% instructions, +2.8 to +8.5% cycles |

This is one program of about 420 lines with a tight loop. Published Rust PGO wins are often 10% or more (the Rust compiler itself is built with PGO), usually on large programs with many cold paths, where profile-guided layout and inlining have more to work with. Our result does not show that Rust PGO is bad. It shows that **Rust PGO needs the same measurement discipline as any other optimisation**, and that the counter to check is cycles (or wall time with many runs), not instructions.

## A checklist for Rust PGO

1. **Try a release profile first.** `lto = "fat"`, `codegen-units = 1` cost nothing but build time and here beat PGO. If you are not using them yet, they come first.
2. **Use a matching `llvm-profdata`.** `rustup component add llvm-tools` installs the one that matches your `rustc`. A version mismatch is the most common way the merge or build fails.
3. **Train on the traffic you serve.** Merge profiles from every workload mix into one `.profdata` (`llvm-profdata merge` takes many inputs). A profile from the wrong mix cost 7-8.5% here.
4. **Read the remarks.** `-Cremark=pgo-icall-prom -Cremark=inline` shows what the profile changed. Here it pointed to the single inline that mattered.
5. **Measure cycles or wall time, not only instructions.** Instructions fell in almost every PGO build here, and cycles rose in every one that kept the `HistSink::write` inline. If you use counters, compare IPC as well.
6. **If one inline is the problem, pin it.** `#[inline(never)]` on the one function kept PGO's other decisions and removed the slowdown. Re-measure after every compiler upgrade, because LLVM's inliner changes between versions.
7. **Automate the loop.** Profile-generate, run, merge and profile-use is four commands. Put them in CI next to the benchmark that decides whether the PGO build ships. In the Go post, Go needed none of this.

## Takeaways

- Same program, same input, same profile shape. Go `-pgo` cut **8.7-10.0% of instructions and 4.0-4.9% of cycles**. Rust `-Cprofile-use` cut **0.8-4.3% of instructions but added 2.8-8.5% of cycles**, because IPC fell from 3.93 to 3.65.
- The cause was one decision: inlining the indirect-call-promoted `HistSink::write` (hash, map probe and histogram update) into the parsing loop. `#[inline(never)]` on it brought cycles back within noise of the default build.
- Fat LTO without a profile beat Rust PGO here, and a profile from the wrong traffic cost up to 8.5%.
- Rust's default build was already 16-18% fewer instructions per line than Go's. PGO did not change which language was faster. It changed how much measurement you need before you ship it.

*We use this measure → change one thing → re-measure loop on the Rust and Go services behind Lamplit Labs' products. Checking each change against a baseline before accepting it is also how the self-improvement (RSI) loop in [**Hive**](https://hivefleet.dev/), Lamplit Labs' open-source agent harness, decides what to keep.*

## Related reading

- [Go PGO in Practice: What go build -pgo Changed in a Log Router, Measured](/posts/go-pgo-profile-guided-optimization-measured/): the Go half of this comparison, with eight Go builds.
- [Rust Release Profiles: LTO, codegen-units and target-cpu](/posts/rust-lto-codegen-units-release-profile/): the release-profile knobs to try before PGO.
- [Rust Profiling Practical Guide: sample, Flame Graphs and a Counting Allocator, Measured](/posts/rust-profiling-practical-guide-sample-flamegraph/): the `/usr/bin/sample` and counter method used here.
- [Rust vs Go for a CPU-Bound Microservice](/posts/rust-vs-go-cpu-bound-microservice/): the same two languages on throughput, tail latency and memory.
- [Hive: Lamplit Labs' open-source, self-improving (RSI) agent harness](/posts/hive-self-improving-rsi-agent-harness/): the product mentioned above.
