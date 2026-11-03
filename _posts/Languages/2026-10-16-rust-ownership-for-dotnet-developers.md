---
layout: post
title: "Rust Ownership for .NET Developers: C# vs Rust Memory Behaviour on the Same Pipeline"
description: "One 2M-record pipeline in C# 13 on .NET 9 and Rust 1.91: each ownership concept mapped from C#, with measured peak RSS, allocations, GC pauses and wall time."
date: 2026-10-16 00:00:00 +0200
categories: languages rust csharp
tags: rust csharp dotnet memory ownership gc performance benchmark
author: manishtiwari25
image:
  path: /assets/img/headers/languages/rust-ownership-for-dotnet-developers.webp
  alt: "Grouped bar chart comparing C# 13 on .NET 9 and Rust 1.91 on the same 2 million record transform pipeline: peak RSS 412 vs 96 MB, allocations 6,100 vs 410 thousand, p99 pause 18.4 vs 0 ms, wall time 2.9 vs 1.7 s"
---

Every Rust post in this series so far ([Rust vs Go]({% post_url Languages/2026-10-03-rust-vs-go-cli-tool %}), [Rust vs Python]({% post_url Languages/2026-10-11-rust-vs-python-ai-inference-microservice %}), [Swift vs Rust]({% post_url Languages/2026-10-08-swift-vs-rust-data-cli %})) got the same reader question: *"I write C# all day. What does ownership actually change for me, and is the memory win real or folklore?"* This post answers that directly. I took one workload a .NET team would recognise, wrote it in both languages, mapped each C# memory habit to its Rust equivalent, and measured what the runtime does underneath.

## The workload

A batch transform you would find in any back office: read a 1.2 GB NDJSON export of 2 million order records, normalise currency and address fields, group by customer, and write one summary line per customer. No database, no network, single process. The interesting part for memory is that every record is parsed into an object graph (order, lines, address), touched once, and then discarded, while a per-customer aggregate survives to the end.

Two implementations with matching structure:

- **C# 13 on .NET 9**, `System.Text.Json` with source-generated serialisers, `record` types for the model, `Dictionary<long, CustomerSummary>` for the aggregate, Server GC off (it is a batch job, workstation concurrent GC is the default most teams ship with).
- **Rust 1.91**, `serde_json` with derived `Deserialize`, plain structs for the model, `HashMap<u64, CustomerSummary>`, release build, default system allocator.

Both read the file line by line, so neither holds the input in memory. Same machine as the rest of the series: Apple M3 Pro, 36 GB, macOS 15, `hyperfine` with five warm-up runs, memory via `/usr/bin/time -l`, .NET pauses from `dotnet-counters`.

## Ownership, translated from C#

The thing that trips .NET developers up is not syntax, it is that a Rust value has exactly one owner at a time and the compiler tracks it. In C# every class instance is a reference, references are freely copied, and the GC later works out which objects are still reachable. Here is the same record flowing through both programs.

```csharp
// C#: 'order' is a reference. Passing it copies the reference; three
// methods can hold it at once; the GC frees it when none of them do.
var order = JsonSerializer.Deserialize(line, OrderContext.Default.Order)!;
Normalise(order);                 // mutates in place through the shared reference
summaries[order.CustomerId].Add(order);   // keeps a reference alive past this loop iteration
```

```rust
// Rust: 'order' is owned by this loop body. Normalise borrows it mutably
// (&mut), Add takes it by value (a move), and after that line 'order' is gone.
let mut order: Order = serde_json::from_str(&line)?;
normalise(&mut order);            // temporary exclusive borrow, returned at the ';'
summaries.entry(order.customer_id).or_default().add(order);  // move: ownership transfers
// order.id  <- compile error E0382: borrow of moved value
```

Three habits to translate:

1. **"Pass the object" becomes a choice.** `&T` when the callee only reads, `&mut T` when it writes, `T` when the callee keeps it. In C# all three are the same call. The borrow checker enforces that an `&mut` is exclusive, which is the rule your team already follows by convention when it says "don't mutate a DTO after you've handed it to the cache".
2. **`IDisposable` becomes `Drop`, and it is no longer optional.** Anything that owns a resource runs its cleanup at scope end, every time, with no `using` to forget. `File`, `MutexGuard` and your own types all behave the same way.
3. **Shared ownership is opt-in, not the default.** When two aggregates genuinely need the same object, you say so with `Rc<T>` (single-threaded) or `Arc<T>` (shared across threads). It cost me exactly one `Arc` in this program, for the currency table.

The first Rust build failed 14 times, every one a borrow-checker error, and every one pointed at a line where the C# version was quietly keeping a reference alive longer than I thought. That was the moment the memory numbers below stopped being surprising.

## Results

![Table mapping each C# memory concept to its Rust equivalent and who frees the memory: heap lifetime GC vs owner's scope end, pass to a method copies a reference vs move or borrow, mutable shared state allowed by convention vs one &mut or many & enforced, shared ownership default vs opt-in Rc/Arc, deterministic cleanup IDisposable plus using vs Drop always runs, use after free impossible vs compile error; measured rows peak RSS 412 vs 96 MB, allocations 6.1 M vs 410 k, longest pause 18.4 ms gen2 vs 0 ms, wall time 2.9 vs 1.7 s, compile errors before green 0 vs 14 all borrow checker](/assets/img/posts/languages/rust-ownership-for-dotnet-developers-table.webp){: width="1200" height="560" }

The headline numbers, median of ten runs:

| Measure | C# 13 / .NET 9 | Rust 1.91 |
|---|---|---|
| Peak RSS | 412 MB | 96 MB |
| Allocations | 6.1 M | 410 k |
| Longest GC pause | 18.4 ms (gen2) | none |
| Wall time | 2.9 s | 1.7 s |
| Lines of code | 310 | 390 |
| Build | 6 s | 48 s release |

What is behind each row:

- **Peak RSS, 4.3x.** Not because Rust objects are smaller (the `Order` struct is within 10% of the C# record's size). It is because the C# process lets 2 million short-lived order graphs pile up in gen0 until a collection, and the GC budget on a 36 GB machine is generous. Rust frees each order the instant `add()` is done with it, so live memory is the aggregate plus one record. Setting `GCgen0size` or switching to `DOTNET_GCConserveMemory=5` brought C# down to 190 MB at a 0.4 s wall-time cost; the default is what most teams run, so the default is what I report.
- **Allocations, 15x.** `serde` deserialises straight into the struct, borrowing string slices from the input line where it can (`&str` fields with a lifetime). `System.Text.Json` allocates a string per JSON string even with source generation; `Utf8JsonReader` with manual parsing closes most of this gap, at roughly double the code.
- **Pauses.** 18 ms is invisible in a batch job. It is not invisible in the request path, which is why the [.NET vs Node gateway post]({% post_url Performance/2026-10-14-dotnet-vs-node-llm-gateway-throughput %}) spends so long on gen2. Rust has no collector to pause; the cost moved to compile time (48 s) and to the 14 compile errors.
- **Wall time, 1.7x.** Mostly allocation and parsing; the aggregation itself is within 5%.

## What ownership does not buy you

Ownership prevents use-after-free, double-free and data races at compile time. It does not prevent leaks (`Rc` cycles and `mem::forget` are safe code), it does not prevent logic bugs, and it does not make a `HashMap` faster than a `Dictionary`. The RSS win above is a consequence of deterministic drop and of a serialiser that borrows; a Rust program that clones every string and collects everything into a `Vec` first will look a lot like the .NET one.

It also costs time up front. A C# developer on the team wrote the Rust version's first draft in a day and a half against 2 hours for the C# one, with most of the gap spent learning why a `&str` cannot outlive the line it came from. Second program, same person, the gap was under 2x.

## When to pick which

Keep C# for the pipeline above if it runs nightly and 400 MB is nobody's problem; the GC knobs get you most of the memory back if it ever becomes one. Reach for Rust when the same transform runs per request, in a container with a 128 MB limit, or in a sidecar that must not pause, and when the team can absorb a week of borrow-checker tuition. The one-owner rule is the whole language; once it stops feeling like a fight, the memory graph in the header is what you get for free.

## Related

- [Rust vs Go for a CLI tool]({% post_url Languages/2026-10-03-rust-vs-go-cli-tool %}): the same build-time and binary-size trade-off against a different GC language.
- [Rust vs Python for an AI inference microservice]({% post_url Languages/2026-10-11-rust-vs-python-ai-inference-microservice %}): where the model, not the allocator, dominates.
- [Swift vs Rust for a data CLI]({% post_url Languages/2026-10-08-swift-vs-rust-data-cli %}): ARC reference counting against ownership on a similar record workload.
- [.NET vs Node.js LLM gateway throughput]({% post_url Performance/2026-10-14-dotnet-vs-node-llm-gateway-throughput %}): the gen2 pause story on the request path.
