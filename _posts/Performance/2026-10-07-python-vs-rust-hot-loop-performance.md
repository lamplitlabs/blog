---
layout: post
title: "Python vs Rust in a Hot Loop: What 10 Million Iterations Cost, Measured with hyperfine"
date: 2026-10-07 00:00:00 +0200
categories: performance rust
tags: rust python performance benchmark hyperfine numpy
author: manishtiwari25
description: "Benchmark the same sum-of-squares hot loop in plain Python, NumPy, Rust and Rust with rayon. From 1,420 ms down to 0.9 ms, and when each step is worth it."
image:
  path: /assets/img/headers/performance/python-vs-rust-hot-loop.webp
  alt: "Bar chart of mean wall time for a 10 million element sum-of-squares loop: Python for loop 1,420 ms, Python generator 905 ms, NumPy 12.4 ms, Rust 3.1 ms, Rust with rayon 0.9 ms"
---

The earlier posts in this folder were all .NET: [allocations with Span<T>]({% post_url Performance/2026-10-03-span-memory-allocation-reduction-dotnet %}), [EF Core query shape]({% post_url Performance/2026-10-05-ef-core-query-performance-dotnet %}) and [JSON serialization]({% post_url Performance/2026-10-06-dotnet-json-serialization-performance %}). This one steps outside the CLR. A lot of our data-prep and AI tooling is written in Python, and the question "should this hot loop move to Rust?" comes up every few weeks. Rather than argue, I measured.

The workload is deliberately boring: compute the sum of squares of 10 million 64-bit integers. It is the shape of a feature-extraction loop, a checksum, a histogram pass, or the inner step of a tokenizer. Five implementations, same machine, same input, timed with [hyperfine](https://github.com/sharkdp/hyperfine).

![Bar chart of mean wall time for a 10 million element sum-of-squares loop across Python, NumPy, Rust and Rust with rayon](/assets/img/headers/performance/python-vs-rust-hot-loop.webp){: width="1200" height="630" }

## The five implementations

**1. Plain Python `for` loop.** The code everyone writes first.

```python
# loop.py
def main() -> None:
    n = 10_000_000
    total = 0
    for i in range(n):
        total += i * i
    print(total)

main()
```

**2. Python generator with `sum`.** The "idiomatic" rewrite most code reviews suggest.

```python
# gen.py
n = 10_000_000
print(sum(i * i for i in range(n)))
```

**3. NumPy.** Push the loop into C.

```python
# np.py
import numpy as np

n = 10_000_000
a = np.arange(n, dtype=np.int64)
print(int(np.dot(a, a)))
```

**4. Rust iterator, release build.** The direct translation.

```rust
// src/main.rs
fn main() {
    let n: u64 = 10_000_000;
    let total: u64 = (0..n).map(|i| i.wrapping_mul(i)).sum();
    println!("{total}");
}
```

**5. Rust with rayon.** One line changes: `into_par_iter()`.

```rust
use rayon::prelude::*;

fn main() {
    let n: u64 = 10_000_000;
    let total: u64 = (0..n).into_par_iter().map(|i| i.wrapping_mul(i)).sum();
    println!("{total}");
}
```

Build with `cargo build --release`. Debug builds are 20-50x slower and are the single most common reason "Rust was not faster for me".

## Results

hyperfine runs each command repeatedly after warmup and reports mean and standard deviation, so Python interpreter start-up (~15 ms) is included in every Python number. That is fair: it is the cost you pay when you shell out to a script.

![hyperfine console output comparing the Python for loop, generator, NumPy, Rust and Rust with rayon implementations, with the summary line showing Rust with rayon 1578x faster than the Python loop](/assets/img/posts/performance/python-vs-rust-hyperfine-output.webp){: width="1100" height="560" }

| Implementation            | Mean time | vs. Python loop |
| ------------------------- | --------: | --------------: |
| Python `for` loop         |  1,420 ms |            1.0x |
| Python `sum(generator)`   |    905 ms |            1.6x |
| Python + NumPy            |   12.4 ms |            115x |
| Rust iterator (release)   |    3.1 ms |            458x |
| Rust + rayon (8 threads)  |    0.9 ms |          1,578x |

Three things stand out.

**The generator rewrite is not a performance fix.** It saves 36% because it avoids the `total +=` bytecode on every iteration, but you are still executing one interpreted Python op per element. If someone proposes it in review "for speed", that is the ceiling.

**NumPy gets you most of the way.** Two orders of magnitude, no new toolchain, and the result is still a Python object your pipeline can use. For anything that vectorises cleanly, this is the first thing to try. Note that `np.arange` allocates 80 MB here; the Rust version allocates nothing because the range is consumed lazily.

**Rust's single-threaded number is the honest comparison.** 3.1 ms vs 12.4 ms is a 4x gap, not a 458x one. The 458x headline compares compiled code with a per-element interpreter loop, and nobody who cares about this loop would leave it in plain Python anyway. The rayon version then scales almost linearly across the 8 cores because there is no shared state to fight over.

## When moving to Rust is worth it

- **The loop does not vectorise.** Branches per element, variable-length records, early exits, state machines. NumPy cannot express it; Rust stays at the 3 ms end.
- **Memory is the constraint.** NumPy needs the whole array materialised. A Rust iterator streams.
- **You want the parallel speed-up without a process pool.** Python's `multiprocessing` would have to serialise 80 MB to workers; rayon just splits the range.
- **The function is called from Python.** With [PyO3](https://pyo3.rs) and maturin you expose the Rust function as a module and the call site does not change. That is how we moved a tokenizer's inner loop without rewriting the service around it.

## When it is not

- The loop runs once at start-up and takes 1.4 s. Nobody will notice.
- The work is dominated by I/O or an LLM call measured in hundreds of milliseconds. A 12 ms loop is noise next to a 900 ms completion request.
- The team does not own a Rust toolchain in CI yet. The 12 ms NumPy version ships today.

## Reproducing

```bash
pip install numpy
cargo new hot && cd hot && cargo add rayon
# paste the Rust sources, then:
cargo build --release
hyperfine --warmup 3 'python3 loop.py' 'python3 gen.py' 'python3 np.py' \
  './target/release/hot' './target/release/hot --par'
```

Numbers above are from Python 3.12.6, Rust 1.81, NumPy 2.1 on an Apple M2 with 8 cores. Your absolute times will differ; the ratios between the rows are what to expect.

## Related Performance posts

The .NET side of the same question, measured with BenchmarkDotNet:

- [Cutting .NET Allocations with Span<T> and Memory<T>: Before/After BenchmarkDotNet Numbers]({% post_url Performance/2026-10-03-span-memory-allocation-reduction-dotnet %}) - the in-memory hot loop side in C#.
- [EF Core Query Tuning: AsNoTracking, Split Queries and Compiled Queries Measured with BenchmarkDotNet]({% post_url Performance/2026-10-05-ef-core-query-performance-dotnet %}) - the database side.
- [System.Text.Json Source Generators vs Newtonsoft.Json: A BenchmarkDotNet Comparison on .NET 8]({% post_url Performance/2026-10-06-dotnet-json-serialization-performance %}) - the serialization side.

Outside .NET, the same interpreter-vs-compiled trade-off measured at the HTTP and database layers:

- [Node vs Deno vs Bun: HTTP Server Performance Under Load]({% post_url Performance/2026-10-04-node-vs-deno-vs-bun-http-performance %}) - what JIT-compiled JavaScript runtimes cost once a network is in the way.
- Go vs .NET: Goroutines vs Tasks Concurrency Throughput - two compiled runtimes under the same wrk load.
- pg vs Prisma vs Drizzle: PostgreSQL Driver Latency from Node.js 22 - where the time goes when the hot loop is a database round trip.
