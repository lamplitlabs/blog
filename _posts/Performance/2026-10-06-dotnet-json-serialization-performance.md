---
layout: post
title: "System.Text.Json Source Generators vs Newtonsoft.Json: A BenchmarkDotNet Comparison on .NET 8"
date: 2026-10-06 00:00:00 +0200
categories: performance dotnet
tags: dotnet csharp performance benchmarkdotnet json serialization
author: manishtiwari25
description: "Benchmark Newtonsoft.Json against System.Text.Json with reflection and source generators. Serialization drops from 2,140 ns to 588 ns with zero allocations."
image:
  path: /assets/img/headers/performance/json-serialization-source-generators.webp
  alt: "Bar chart of mean serialization time per 1 KB order: Newtonsoft.Json 2,140 ns, System.Text.Json reflection 1,080 ns, System.Text.Json source generator 742 ns, source generator with Utf8JsonWriter 588 ns"
---

Most .NET web services spend a surprising share of their CPU turning objects into JSON and back. After [allocations in hot loops]({% post_url Performance/2026-10-03-span-memory-allocation-reduction-dotnet %}) and [EF Core query shape]({% post_url Performance/2026-10-05-ef-core-query-performance-dotnet %}), serialization is the third place I look when an API is slower than it should be, and it is usually the cheapest to fix: the code change is a `[JsonSerializable]` attribute and a partial class.

This post benchmarks the same 1 KB `Order` payload four ways with [BenchmarkDotNet](https://github.com/dotnet/BenchmarkDotNet) on .NET 8: `Newtonsoft.Json` 13.0.3, `System.Text.Json` with the default reflection-based metadata, `System.Text.Json` with a source-generated `JsonSerializerContext`, and the source generator combined with a pooled `Utf8JsonWriter`. As always, the absolute numbers are from one laptop; the *ratios* are what carry over.

![Bar chart of mean serialization time per 1 KB order across Newtonsoft.Json, System.Text.Json reflection and source generators](/assets/img/headers/performance/json-serialization-source-generators.webp)

{% include feed-ads.html %}

## The payload

A typical order document: a header, a customer and five lines. Nothing exotic, which is the point. This is the shape most enterprise APIs move around all day.

```csharp
public sealed class Order
{
    public int Id { get; set; }
    public DateTime PlacedAt { get; set; }
    public string Currency { get; set; } = "USD";
    public Customer Customer { get; set; } = new();
    public List<OrderLine> Lines { get; set; } = new();
}

public sealed class Customer
{
    public int Id { get; set; }
    public string Name { get; set; } = "";
    public string Email { get; set; } = "";
}

public sealed class OrderLine
{
    public string Sku { get; set; } = "";
    public int Quantity { get; set; }
    public decimal UnitPrice { get; set; }
}
```

Serialized with indentation off, one order is about 1,000 bytes of UTF-8.

## Step 0: Newtonsoft.Json (the baseline)

```csharp
private static readonly JsonSerializerSettings NewtonsoftSettings = new()
{
    ContractResolver = new CamelCasePropertyNamesContractResolver()
};

[Benchmark(Baseline = true)]
public string Serialize_Newtonsoft() =>
    JsonConvert.SerializeObject(_order, NewtonsoftSettings);

[Benchmark]
public Order Deserialize_Newtonsoft() =>
    JsonConvert.DeserializeObject<Order>(_json, NewtonsoftSettings)!;
```

Newtonsoft is a `string`-first library: it writes to a `StringWriter`, so every call allocates the intermediate `StringBuilder`, the final `string`, and then the UTF-8 bytes once ASP.NET copies it to the response. That shows up in the `Allocated` column as roughly 6 KB per 1 KB payload.

## Step 1: System.Text.Json with reflection

```csharp
private static readonly JsonSerializerOptions StjOptions = new(JsonSerializerDefaults.Web);

[Benchmark]
public byte[] Serialize_Stj_Reflection() =>
    JsonSerializer.SerializeToUtf8Bytes(_order, StjOptions);

[Benchmark]
public Order Deserialize_Stj_Reflection() =>
    JsonSerializer.Deserialize<Order>(_jsonBytes, StjOptions)!;
```

Two changes buy the 2x: `System.Text.Json` works in UTF-8 end to end, so there is no UTF-16 round trip, and the `JsonSerializerOptions` instance caches per-type metadata after the first call. Note that the options object must be reused; constructing a new `JsonSerializerOptions` per call throws the metadata cache away and is one of the most common ways to make `System.Text.Json` *slower* than Newtonsoft.

## Step 2: Source generator

```csharp
[JsonSourceGenerationOptions(
    PropertyNamingPolicy = JsonKnownNamingPolicy.CamelCase,
    GenerationMode = JsonSourceGenerationMode.Default)]
[JsonSerializable(typeof(Order))]
internal partial class OrderJsonContext : JsonSerializerContext { }

[Benchmark]
public byte[] Serialize_Stj_SourceGen() =>
    JsonSerializer.SerializeToUtf8Bytes(_order, OrderJsonContext.Default.Order);

[Benchmark]
public Order Deserialize_Stj_SourceGen() =>
    JsonSerializer.Deserialize(_jsonBytes, OrderJsonContext.Default.Order)!;
```

The generator emits the property metadata and, in `Serialization` mode, a hand-unrolled `Write` method for each type at compile time. Nothing is discovered through reflection at runtime, which removes the first-call warm-up (important for serverless and scale-to-zero), makes the code trimmable and Native AOT compatible, and shaves another 30% off the steady-state time because the generated writer skips the generic converter dispatch.

In ASP.NET Core minimal APIs you wire it in once:

```csharp
builder.Services.ConfigureHttpJsonOptions(o =>
    o.SerializerOptions.TypeInfoResolverChain.Insert(0, OrderJsonContext.Default));
```

## Step 3: Source generator plus a pooled Utf8JsonWriter

```csharp
private readonly ArrayBufferWriter<byte> _buffer = new(2048);
private readonly Utf8JsonWriter _writer;

public JsonBenchmarks()
{
    _writer = new Utf8JsonWriter(_buffer, new JsonWriterOptions { SkipValidation = true });
}

[Benchmark]
public int Serialize_Stj_SourceGen_Utf8()
{
    _buffer.ResetWrittenCount();
    _writer.Reset(_buffer);
    JsonSerializer.Serialize(_writer, _order, OrderJsonContext.Default.Order);
    return _buffer.WrittenCount;   // bytes are in _buffer, ready for the response stream
}
```

This is what Kestrel effectively does for you when you return an object from an endpoint: it serializes straight into the response `PipeWriter`. Doing it explicitly matters when you own the transport, for example writing to a message bus, a cache, or a file. The `byte[]` result disappears, and with it the last allocation.

## The results

![BenchmarkDotNet console output comparing Newtonsoft.Json, System.Text.Json reflection and System.Text.Json source generators for serialize and deserialize, with source-generated rows highlighted](/assets/img/posts/performance/json-serialization-benchmarkdotnet-output.webp)
_BenchmarkDotNet output on .NET 8.0.8. The source-generated rows are highlighted; `Alloc Ratio` is the column that explains the GC behaviour under load._

| Method                        |       Mean | Ratio |   Gen0 | Allocated | Alloc Ratio |
|-------------------------------|-----------:|------:|-------:|----------:|------------:|
| Serialize_Newtonsoft          | 2,140.3 ns |  1.00 | 0.7324 |    6136 B |        1.00 |
| Serialize_Stj_Reflection      | 1,079.8 ns |  0.50 | 0.1545 |    1296 B |        0.21 |
| Serialize_Stj_SourceGen       |   742.1 ns |  0.35 | 0.1545 |    1296 B |        0.21 |
| Serialize_Stj_SourceGen_Utf8  |   588.4 ns |  0.27 |      - |       0 B |        0.00 |
| Deserialize_Newtonsoft        | 3,412.7 ns |  1.00 | 1.0834 |    9072 B |        1.00 |
| Deserialize_Stj_Reflection    | 1,655.2 ns |  0.49 | 0.1621 |    1360 B |        0.15 |
| Deserialize_Stj_SourceGen     | 1,298.6 ns |  0.38 | 0.1621 |    1360 B |        0.15 |

Three observations:

- **Reflection to source generator is a 30% speed-up, not a 10x one.** The big step is leaving Newtonsoft. If you are already on `System.Text.Json` with a cached options instance, the generator is mostly a startup, trimming and AOT story with a modest steady-state bonus.
- **Deserialization allocations are the object graph itself.** The 1,360 bytes in the `System.Text.Json` deserialize rows are the `Order`, `Customer` and five `OrderLine` instances plus the strings; the serializer adds nothing. Newtonsoft's extra 7.7 KB is the `JToken`-style intermediate buffers and the UTF-16 string.
- **Zero allocation serialization is achievable with no unsafe code.** Pool the writer and buffer per request (or let Kestrel do it) and the GC never hears about your JSON.

## Pitfalls when migrating

- `System.Text.Json` is case-sensitive by default outside of `JsonSerializerDefaults.Web`; Newtonsoft is not. Use the `Web` defaults or set `PropertyNameCaseInsensitive = true`.
- Fields, non-public setters and parameterised constructors need opt-in (`IncludeFields`, `[JsonInclude]`, `[JsonConstructor]`). Newtonsoft handles most of these silently.
- `DateTime` is written as ISO 8601 with no `DateTimeKind` adjustments; `Newtonsoft` also writes ISO 8601 but the two differ on `Unspecified` kinds. Compare payloads in a golden-file test before switching a public contract.
- The source generator cannot see types that are only reachable through `object` or `dynamic`; add them to the context explicitly or they fall back to a runtime `NotSupportedException`.

## Takeaways

- Moving from Newtonsoft.Json to `System.Text.Json` roughly halves serialization time and cuts allocations by 80%; a single shared `JsonSerializerOptions` is mandatory to get there.
- A `JsonSerializerContext` adds another ~30%, removes first-call reflection cost, and makes the service trimmable and Native AOT ready.
- Serialize into a pooled `Utf8JsonWriter` (or let ASP.NET Core do it) to reach zero allocations per payload.
- Measure with BenchmarkDotNet and `dotnet-counters` on your own payload shape before and after; the ratios above are typical, the nanoseconds are not.

## Related Performance posts

The serializer is usually the last of three stops on the same `[MemoryDiagnoser]` tour. The first two posts below use the same BenchmarkDotNet workflow on the layers that feed it; the third steps outside .NET:

- [Cutting .NET Allocations with Span<T> and Memory<T>: Before/After BenchmarkDotNet Numbers]({% post_url Performance/2026-10-03-span-memory-allocation-reduction-dotnet %}) - the in-memory hot loop side.
- [EF Core Query Tuning: AsNoTracking, Split Queries and Compiled Queries Measured with BenchmarkDotNet]({% post_url Performance/2026-10-05-ef-core-query-performance-dotnet %}) - the database side.
- [Python vs Rust in a Hot Loop: What 10 Million Iterations Cost, Measured with hyperfine](/posts/python-vs-rust-hot-loop-performance/) - the same question outside .NET, measured with hyperfine instead of BenchmarkDotNet.
- [OData Query Performance Pitfalls in .NET - $expand, Paging and Payload Size Explained]({% post_url OData/2026-10-05-odata-query-performance-pitfalls-dotnet %}) - how to shrink the OData payload before it ever reaches the serializer.
