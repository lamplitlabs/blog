---
layout: post
title: "Rust Profiling Practical Guide: sample, Flame Graphs and a Counting Allocator, Measured"
date: 2026-11-03 12:00:00 +0000
categories: performance rust
tags: [rust, profiling, flamegraph, performance, allocation, benchmark, macos]
author: manishtiwari25
description: "A measured Rust profiling guide: macOS sample, flame graphs and a counting allocator took a Rust log analyser from 3,256 ms to 233 ms in three fixes."
image:
  path: /assets/img/headers/performance/rust-profiling-practical-guide.webp
  alt: "Header graphic for the Rust profiling guide: bars of median wall time for five versions of a log analyser, v0 naive 3,256 ms, v1 HashSet blocklist 1,080 ms, v2 borrowed fields 266 ms, v3 FxHash 281 ms and v4 byte scan 233 ms, above the result 14.0x faster and 21.5 to 0 allocations per line"
---

Rust gives you fast code by default, and that makes profiling it easy to put off. When a release build is slow anyway, guessing goes badly: the obvious suspect (it parses strings, so parsing must be slow) is often wrong, and the usual fix (swap in a faster hash) can make things worse. This guide uses one small, reproducible program and a loop you can run on any Mac without `sudo`. Profile, read the widest frame, change one thing, then measure again with the profiler detached.

Every number below comes from the scripts in this blog's repository and was measured on one machine. The program went from **3,256 ms to 233 ms (14.0x)** in four steps. One of those steps was a "fix" the measurements rejected.

## The program under test

`logstat` reads an LLM gateway access log and reports request count, token total, p50 and p99 latency per `(route, model)`. It skips users on a 1,000-entry blocklist and requests that did not return 200. The log has one million seeded, synthetic lines (119 MB), one per request:

```text
ts=2026-11-03T00:00:00Z level=INFO route=/v1/tokenize model=mistral-7b user=u08617 tokens=1173 latency_ms=205 status=200
```

The first version is the code most of us write on a first pass. It is correct, idiomatic and has no `unsafe`:

```rust
fn parse_fields_v0(line: &str) -> HashMap<String, String> {
    line.split(' ')
        .filter_map(|kv| kv.split_once('='))
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
}

fn is_blocked_v0(blocked: &[String], user: &str) -> bool {
    blocked.iter().any(|b| b == user)
}

fn run_v0(text: &str, blocked: &[String]) -> Report {
    let mut groups: HashMap<String, Agg> = HashMap::new();
    for line in text.lines() {
        let f = parse_fields_v0(line);
        if is_blocked_v0(blocked, &f["user"]) { /* count, skip */ continue; }
        if f["status"] != "200" { /* count, skip */ continue; }
        let key = format!("{} {}", f["route"], f["model"]);
        let a = groups.entry(key).or_default();
        a.lat.push(f["latency_ms"].parse().unwrap());
        a.tokens += f["tokens"].parse::<u64>().unwrap();
    }
    finish(groups.into_iter(), nblocked, errors)
}
```

The repository holds five versions in one binary (`logstat run v0..v4 <file>`), and each version changes one thing. All five print the same report and the same checksum (`d654a56473e13295`) on every run, so no speed-up below comes from doing less work.

**Test machine:** Apple M2 Pro (12 cores), macOS 27.0.1, rustc 1.95.0, `cargo build --release`. Timings are medians of five interleaved runs with no profiler attached.

## Step 0: build so the profiler can read it

A release build without debug info gives a profiler function names but no line numbers. One line in `Cargo.toml` fixes that without changing the generated code:

```toml
[profile.release]
debug = "line-tables-only"
```

On Apple silicon, frame pointers are always on, so stack walking just works. On Linux x86-64, add `RUSTFLAGS="-C force-frame-pointers=yes"` or use `perf record --call-graph dwarf`, or the stacks come back truncated.

## Step 1: sample the process, no sudo needed

macOS ships `/usr/bin/sample`. It attaches to a running process you own, takes a stack every millisecond and writes a call tree as text:

```bash
./target/release/logstat run v0 access.log 2 &
sample $! 4 1 -file v0.sample.txt     # 4 seconds, 1 ms interval
```

`cargo flamegraph` uses DTrace on macOS (which needs `sudo`) and `perf` on Linux. `samply record ./target/release/logstat ...` opens the Firefox Profiler instead. I did not run either for this post. Both give the same kind of data, and the reading steps below apply unchanged. `sample` won here because it needs no install and no root, which also makes it usable on a shared CI runner or a colleague's laptop.

![Terminal panel of the macOS sample report for logstat v0. The call graph shows logstat::main with 2,552 samples, run_v0 with 1,665 at main.rs line 141, and below it is_blocked_v0 with 1,407 samples, of which 1,178 are in _platform_memcmp and 229 in the memcmp stub. The top-of-stack summary lists _platform_memcmp 1,198, is_blocked_v0 258 and the memcmp stub 234 as the three heaviest frames.](/assets/img/posts/performance/rust-profiling-guide-sample-report.webp)

The text report already gives the answer, but call trees get hard to read past a few levels. The two small scripts next to the program turn the report into a flame graph. `fold_sample.py` converts `sample`'s indented tree into the `frame;frame;frame count` "folded" format that every flame graph tool reads, and demangles Rust symbols. `flamegraph_svg.py` draws an SVG from the folded lines, using the standard library only:

```bash
python3 scripts/rust-profiling-logstat/fold_sample.py v0.sample.txt > v0.folded
python3 scripts/rust-profiling-logstat/flamegraph_svg.py v0.folded v0.svg "logstat v0"
```

`v0.folded` also feeds `inferno-flamegraph` or `flamegraph.pl` unchanged, if you already use one of them.

## Step 2: read the widest tower, not the hottest leaf

![CPU flame graph of logstat v0 from 2,552 samples. Above logstat::main and run_v0, the widest tower on the left is logstat::is_blocked_v0, about two thirds of the width, and nearly all of it is _platform_memcmp plus a memcmp stub. A narrower tower on the right is logstat::parse_fields_v0, with HashMap insert, RawTable reserve_rehash and SipHash frames above it.](/assets/img/posts/performance/rust-profiling-guide-flame-v0.webp)

Box width is the share of samples. The x axis is alphabetical, not time. Read it bottom-up and stop at the first frame that belongs to your own code. Here that frame is `is_blocked_v0` at **65.2%** of samples, and 56% of all samples sit in `memcmp` directly above it. A self-time ("top of stack") list would put `_platform_memcmp` first at 46.9%. That is true, but you cannot act on it, because nobody calls `memcmp` on purpose. The flame graph shows who calls it: a linear scan through 1,000 blocklisted user ids for every log line.

The fix is one type:

```rust
// v1: build once, O(1) lookup per line
let blocked: HashSet<&str> = list.iter().map(String::as_str).collect();
if blocked.contains(f["user"].as_str()) { /* ... */ }
```

**v0 → v1: 3,256 ms → 1,080 ms (3.0x).** Instructions retired fell from 48.9 G to 16.3 G.

## Step 3: profile again, because the ranking has changed

The second profile is the step people skip, and it is the one that matters. With the scan gone, the old number-two problem is now most of the program:

![CPU flame graph of logstat v1 from 2,664 samples. The wide central tower is logstat::parse_fields_v0 at about two thirds of the width, built from an iterator fold that calls HashMap insert, RawTable reserve_rehash, BuildHasher hash_one and SipHash write, with smaller towers for string formatting, malloc and free on the left.](/assets/img/posts/performance/rust-profiling-guide-flame-v1.webp)

`parse_fields_v0` takes **65.5%** of samples. Above it, `HashMap::insert` takes 31.9%, `reserve_rehash` 21.7% (the per-line map grows as fields arrive), SipHash 13.6% of self time, and `format!` plus allocator frames fill most of the rest. Each line builds a fresh `HashMap<String, String>` to read six fields once.

A flame graph shows CPU time, not allocation counts. To check the allocator theory directly, the program has an optional counting `#[global_allocator]` (`cargo build --release --features count-alloc`):

```rust
unsafe impl GlobalAlloc for Counting {
    unsafe fn alloc(&self, l: Layout) -> *mut u8 {
        ALLOCS.fetch_add(1, Relaxed);
        unsafe { System.alloc(l) }
    }
    // dealloc forwards; realloc counts and forwards
}
```

It reports **21.5 heap allocations per log line** for v0 and v1: two `String`s per field, the map's table and its regrowths, and the group key from `format!`. The fix is to borrow instead of own. A line struct of `&str` slices points into the input, and the group map is keyed on `(&str, &str)`:

```rust
struct Line<'a> { route: &'a str, model: &'a str, user: &'a str,
                  tokens: &'a str, latency: &'a str, status: &'a str }

fn parse_fields_v2(line: &str) -> Line<'_> {
    let mut l = Line { route: "", model: "", user: "", tokens: "", latency: "", status: "" };
    for kv in line.split(' ') {
        if let Some((k, v)) = kv.split_once('=') {
            match k { "route" => l.route = v, "model" => l.model = v, "user" => l.user = v,
                      "tokens" => l.tokens = v, "latency_ms" => l.latency = v,
                      "status" => l.status = v, _ => {} }
        }
    }
    l
}
```

**v1 → v2: 1,080 ms → 266 ms (4.1x), and 21.5 → 0.0 allocations per line.** The only allocations left are the 30 group entries and their latency vectors, which round to zero per line.

## Step 4: the profile names a suspect, and the measurement rejects the fix

![CPU flame graph of logstat v2 from 2,775 samples. logstat::parse_fields_v2 now covers most of the width, and above it CharSearcher next_match and core::slice::memchr::memchr_aligned are the widest frames, with _platform_memcmp beside them. A narrower tower on the far left is the line iterator's own CharSearcher and memchr, and a smaller one in the middle holds hashbrown rustc_entry, BuildHasher hash_one and SipHash write.](/assets/img/posts/performance/rust-profiling-guide-flame-v2.webp)

Two candidates show up in v2. String splitting (`CharSearcher::next_match` at 73.9% inclusive, with `memchr_aligned` at 32.4% self) is the larger. Hashing (`hash_one` with SipHash inside it, 9.5%) is the familiar one. Rust's default SipHash-1-3 resists hash flooding, and "use FxHash" is common advice, so v3 tries exactly that: v2 with a 20-line FxHash `BuildHasher`.

| | v2 (SipHash) | v3 (FxHash) | change |
|---|---|---|---|
| Instructions retired (median) | 4.21 G | 4.09 G | −3% |
| Cycles (median) | 1.03 G | 1.09 G | **+5%** |
| Wall time (median of 5) | 266 ms | 281 ms | **+6%** |

FxHash runs fewer instructions and takes longer. Its profile moves time into `HashMap::contains_key` (7.9% self) rather than removing it. On these short, similar keys (`u01234`), the cheaper hash buys nothing. **v3 is rejected.** A profile tells you where time goes. It does not tell you whether a given replacement helps, and only a run without the profiler can answer that.

The larger suspect was splitting. `split(' ')` followed by `split_once('=')` scans every byte twice through a generic pattern searcher. v4 walks the line's bytes once and matches the key as a byte slice:

```rust
fn parse_fields_v4(line: &str) -> Line<'_> {
    let mut l = Line { route: "", model: "", user: "", tokens: "", latency: "", status: "" };
    let b = line.as_bytes();
    let (mut start, mut eq) = (0, usize::MAX);
    for i in 0..=b.len() {
        let c = if i < b.len() { b[i] } else { b' ' };
        if c == b'=' && eq == usize::MAX {
            eq = i;
        } else if c == b' ' {
            if eq != usize::MAX {
                let v = &line[eq + 1..i];
                match &b[start..eq] {
                    b"route" => l.route = v, b"model" => l.model = v, b"user" => l.user = v,
                    b"tokens" => l.tokens = v, b"latency_ms" => l.latency = v,
                    b"status" => l.status = v, _ => {}
                }
            }
            start = i + 1;
            eq = usize::MAX;
        }
    }
    l
}
```

![CPU flame graph of logstat v4 from 2,942 samples. logstat::parse_fields_v4 is now one wide flat box with almost nothing above it, meaning the time is spent in the byte loop itself. Narrow towers to its left hold the line iterator's CharSearcher and memchr, and the hashbrown entry with BuildHasher hash_one and SipHash.](/assets/img/posts/performance/rust-profiling-guide-flame-v4.webp)

**v2 → v4: 266 ms → 233 ms (12% faster, 17% fewer instructions).** The v4 flame graph has the shape you want to stop at. The widest box, `parse_fields_v4` at 65.3%, is flat with almost nothing above it, so the time goes to the one loop that has to touch every byte. Only the reading of 119 MB of input is left to remove. A further gain would need a different design, such as parallel chunks or `memchr`-based field jumps, not another local fix.

## Results

![Results table for logstat on 1,000,000 log lines, median of 5 interleaved runs with no profiler attached, Apple M2 Pro, rustc 1.95.0. v0 naive: 3,256 ms, 48.86 G instructions, 21.5 allocations per line. v1 HashSet blocklist: 1,080 ms, 16.25 G, 21.5. v2 borrowed str fields: 266 ms, 4.21 G, 0.0. v3 FxHash: 281 ms, 4.09 G, 0.0. v4 byte scan: 233 ms, 3.50 G, 0.0. Footer: v0 to v4 is 14.0x faster with 14.0x fewer instructions; FxHash retires 3% fewer instructions than v2 but spends 5% more cycles.](/assets/img/posts/performance/rust-profiling-guide-results.webp)

| Version | Change | Wall time (median, range) | Instructions | Allocs / line | Widest own frame in its profile |
|---|---|---|---|---|---|
| v0 | naive | 3,256 ms (3,210–3,342) | 48.86 G | 21.5 | `is_blocked_v0` 65.2% |
| v1 | `HashSet` blocklist | 1,080 ms (1,071–1,106) | 16.25 G | 21.5 | `parse_fields_v0` 65.5% |
| v2 | borrowed `&str` fields | 266 ms (259–311) | 4.21 G | 0.0 | `parse_fields_v2` 64.8% |
| v3 | v2 + FxHash (rejected) | 281 ms (274–284) | 4.09 G | 0.0 | `parse_fields_v2` 61.6% |
| v4 | v2 + byte scan | **233 ms** (230–259) | **3.50 G** | 0.0 | `parse_fields_v4` 65.3% (flat) |

Peak RSS stayed at about 121 MB for every version, because the 119 MB input is read into memory whole. Two notes on method:

- **Count instructions as well as time.** The test Mac was shared with other jobs, with a load average between 7 and 20 during the runs, and single wall-time runs moved by up to 3x. Instructions retired from `/usr/bin/time -l` varied by under 0.6% between runs. Use them to check that a change did what you think, then confirm with wall time.
- **Never time with the profiler attached.** Sampling at 1 ms costs CPU, and 2.5% of v3's samples (`???`) were stacks the sampler could not unwind.

## Reproduce it

Everything is in this blog's repository under `scripts/rust-profiling-logstat/`:

```bash
bash scripts/rust-profiling-logstat/measure.sh logstat-work          # ~1 min: build, 1M-line log, 25 timed runs, 5 profiles
python3 scripts/rust-profiling-logstat/summarise.py logstat-work     # -> scripts/data/rust-profiling-logstat-m2pro.json
python3 scripts/gen_rust_profiling_guide_images.py logstat-work      # every image on this page
```

The log generator is seeded, so you get the same one million lines and the same checksum. Your timings will differ, but the profile shapes and the ranking should not.

## Takeaways

- **Read the widest frame of your own code, not the hottest leaf.** `memcmp` topped the self-time list, but `is_blocked_v0` was the line to change.
- **Re-profile after every fix.** The v1 problem (21.5 allocations per line) was a minor cost in v0's profile.
- **Use a counting allocator to answer allocation questions.** A flame graph shows time, so check allocation counts with an allocator that counts them.
- **The profiler finds the suspect, and an unprofiled run convicts it.** FxHash looked like an obvious win and lost 6%.
- **Stop when the flame graph is flat.** When the widest box is your core loop with nothing above it, local tuning is done.

*We use this profile → change one thing → re-measure loop on the Rust services behind Lamplit Labs' products. Measuring a change against a baseline before accepting it is also at the core of **Pulse**, Lamplit Labs' self-improving automation product, coming soon.*

## Related reading

- [Profiling a Rust LLM Token Batcher with cargo flamegraph](/posts/rust-flamegraph-llm-token-batcher-allocation-reduction/): the same loop on a Linux service with `cargo flamegraph` and `SmallVec`.
- [Go pprof Profiling Guide: CPU, Goroutine and Mutex Profiles](/posts/go-pprof-profiling-guide-cpu-goroutine-mutex/): the Go version of this guide.
- [Go pprof alloc_space: 2.87 GB of garbage from one `+=` in a loop](/posts/go-pprof-alloc-space-escape-analysis/): Go's allocation profile, the counterpart of the counting allocator used here.
- [Go pprof vs SLO Burn Rate: Finding the p99 Leak Before the Pager Fires](/posts/go-pprof-slo-burn-rate-llm-streaming/): deciding when to profile a live Go service.
- [Rust mimalloc vs glibc malloc](/posts/rust-mimalloc-vs-glibc-malloc/): for when the allocations cannot be removed.
- [Rust Release Profiles: LTO, codegen-units and target-cpu](/posts/rust-lto-codegen-units-release-profile/): build settings to try once the code is right.
- [Profiling an ASP.NET Core endpoint with dotnet-trace and dotnet-counters](/posts/profiling-aspnet-core-endpoint-dotnet-trace-counters/): the same workflow in .NET.
- [Pulse: Lamplit Labs' self-improving automation product, coming soon](/posts/pulse-internal-rsi-tool/): the product mentioned above.
