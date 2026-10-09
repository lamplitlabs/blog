---
layout: post
title: "Rust vs Python for an AI Inference Microservice: 1.5x Throughput, 3x Less Memory, 3x Better p99"
description: "Rust 1.91 (axum + ort) vs Python 3.13 (FastAPI + onnxruntime) serving the same MiniLM embedding endpoint: req/s, p50/p99, memory and cold start measured."
date: 2026-11-14 00:00:00 +0200
categories: languages rust python
tags: rust python ai performance benchmark inference onnx latency memory
author: manishtiwari25
image:
  path: /assets/img/headers/languages/rust-vs-python-ai-inference-service.webp
  alt: "Bar chart comparing Rust 1.91 and Python 3.13 serving the same ONNX embedding endpoint with 32 connections: 1,840 vs 1,210 requests per second, p50 latency 11.4 vs 19.8 ms, p99 latency 38 vs 112 ms, resident memory 210 vs 640 MB"
---

The previous post in this series measured [Go against Node.js]({% post_url Languages/2026-11-12-go-vs-nodejs-json-api %}) for a plain JSON API. This one moves to the workload most teams are actually adding this year: a small HTTP service that wraps a model and returns embeddings. Python is the default answer because the model tooling lives there. Rust is the answer people reach for when the Python service starts eating a node. I wrote the same endpoint in both and measured it on one machine, so the trade-off is a number rather than an opinion.

## The workload

`POST /embed` accepts `{"text": "..."}` (one sentence, 20-40 tokens) and returns a 384-float embedding as JSON. The model is `all-MiniLM-L6-v2` exported to ONNX and quantised to int8, about 23 MB on disk. Both services call the **same** ONNX Runtime 1.22 library with 4 intra-op threads and batch size 1, so the comparison isolates the HTTP layer, tokenisation glue, JSON handling and process overhead rather than two different inference engines.

The Python version is FastAPI on uvicorn with `onnxruntime` and the `tokenizers` package, 46 lines, one worker process. The Rust version is `axum` with the `ort` crate and the `tokenizers` crate, 118 lines, a single `tokio` runtime with the session shared behind an `Arc`.

```python
app = FastAPI()
sess = ort.InferenceSession("minilm-int8.onnx", providers=["CPUExecutionProvider"])
tok = Tokenizer.from_file("tokenizer.json")

@app.post("/embed")
def embed(req: EmbedRequest):
    enc = tok.encode(req.text)
    ids = np.array([enc.ids], dtype=np.int64)
    mask = np.array([enc.attention_mask], dtype=np.int64)
    out = sess.run(None, {"input_ids": ids, "attention_mask": mask,
                          "token_type_ids": np.zeros_like(ids)})[0]
    vec = out[0].mean(axis=0)
    return {"embedding": vec.tolist()}
```

```rust
async fn embed(State(st): State<Arc<App>>, Json(req): Json<EmbedRequest>)
    -> Result<Json<EmbedResponse>, StatusCode> {
    let enc = st.tok.encode(req.text, true).map_err(|_| StatusCode::BAD_REQUEST)?;
    let ids: Vec<i64> = enc.get_ids().iter().map(|&x| x as i64).collect();
    let mask: Vec<i64> = enc.get_attention_mask().iter().map(|&x| x as i64).collect();
    let n = ids.len();
    let out = st.session.run(ort::inputs![
        "input_ids" => ([1, n], ids),
        "attention_mask" => ([1, n], mask),
        "token_type_ids" => ([1, n], vec![0i64; n]),
    ]).map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    let (_, data) = out["last_hidden_state"].try_extract_tensor::<f32>().unwrap();
    let mut vec = vec![0f32; 384];
    for t in 0..n { for j in 0..384 { vec[j] += data[t * 384 + j] / n as f32; } }
    Ok(Json(EmbedResponse { embedding: vec }))
}
```

## How it was measured

- Machine: Apple M-series laptop, macOS 26, nothing else in the foreground.
- Versions: Rust 1.91 with `axum` 0.8 and `ort` 2.0; Python 3.13 with FastAPI 0.118, uvicorn 0.37, `onnxruntime` 1.22. Same ONNX Runtime version on both sides.
- Load generator: the same small Go program from the Go vs Node post, 32 keep-alive connections, a rotating pool of 200 sentences, 20 seconds per run, two runs each, both reported.
- Memory: resident set size of the server process read with `ps` during load.
- Cold start: wall time from process launch until the first `200` from `/embed`, median of 5.
- Build: `cargo build --release` from a warm dependency cache; Python has no build step, so the install time of the wheel set is listed instead.

The load generator shares the CPU with the server, and ONNX Runtime uses 4 threads of the same chip, so absolute numbers are capped on both sides. Read the ratios, not the raw figures.

## Results

![Table comparing Rust 1.91 and Python 3.13 serving the same MiniLM ONNX embedding endpoint with 32 keep-alive connections: throughput 1,862 vs 1,174 req/s in run 1 and 1,818 vs 1,246 req/s in run 2, p50 latency 11.1-11.7 vs 19.2-20.4 ms, p99 latency 36-40 vs 104-120 ms, p99.9 latency 61-68 vs 188-215 ms, resident memory 210 vs 640 MB, cold start 0.41 vs 2.9 s, Rust 38 s release build producing a 14 MB binary versus pip install of about 70 s for Python, 118 vs 46 lines of code](/assets/img/posts/languages/rust-vs-python-inference-results-table.webp)

| Metric | Rust 1.91 | Python 3.13 | Ratio |
|---|---|---|---|
| Throughput, run 1 | 1,862 req/s | 1,174 req/s | 1.6x |
| Throughput, run 2 | 1,818 req/s | 1,246 req/s | 1.5x |
| p50 latency | 11.1-11.7 ms | 19.2-20.4 ms | 1.7x |
| p99 latency | 36-40 ms | 104-120 ms | 2.9x |
| p99.9 latency | 61-68 ms | 188-215 ms | 3.1x |
| Resident memory under load | 210 MB | 640 MB | 3.0x |
| Cold start to first 200 | 0.41 s | 2.9 s | 7x |
| Build / install step | 38 s release build, 14 MB binary | ~70 s `pip install`, no build | - |
| Lines of code | 118 | 46 | - |

Three things stand out, and they are different from the Go vs Node result.

**Throughput is only 1.5x apart, because the model dominates.** Roughly 8 ms of every request on both sides is ONNX Runtime doing the same matrix multiplications. Rust shaves the HTTP parsing, JSON serialisation of 384 floats and the mean-pooling loop, but it cannot shave the model. If your model is bigger than MiniLM, the ratio gets closer to 1.0x. This is the main reason "rewrite the inference service in Rust" so often disappoints: the rewrite removes the part that was never the bottleneck.

**Tail latency is where Rust actually wins.** p99 is 2.9x better and p99.9 is 3.1x better. The Python service runs one event loop and the inference call holds the GIL for its duration, so under 32 concurrent connections requests queue behind each other and the queue shows up at the tail. The Rust service hands each request to the tokio runtime and ONNX Runtime's thread pool directly. If your SLO is a p99 and not a mean, this table says Rust, even though the throughput table barely does.

**Memory and cold start are the operational story.** 640 MB resident for Python is mostly the interpreter plus NumPy plus the ONNX Runtime wheel plus FastAPI's dependency tree; 210 MB for Rust is nearly all the model and the runtime's arenas. 2.9 s versus 0.41 s to first response matters when you scale to zero or run on spot nodes. For one service none of this matters. For a RAG platform running an embedding sidecar next to every tenant, it is the difference between one node pool and two.

## What Python still wins

- **The model lifecycle lives here.** Exporting the model, quantising it, checking accuracy against the original, adding a new tokenizer: all of that was done in Python before either service existed. The Rust service consumes artefacts the Python toolchain produced.
- **Less code and faster change.** 46 lines versus 118. Adding a batching endpoint took me ten minutes in FastAPI and most of an hour in Rust, almost entirely spent on tensor shapes and lifetimes.
- **The escape hatch is free.** If MiniLM is not good enough tomorrow, swapping to a `sentence-transformers` model in Python is one line. In Rust it is a new export and possibly a new crate.
- **Multiple workers close part of the gap.** Running uvicorn with 4 workers roughly doubled Python's throughput in a quick follow-up, at the cost of 4x the memory, which turns the 3x memory gap into a 12x one.

## When to pick which

Pick Rust when the service is latency-sensitive at the tail, runs as many small replicas where memory is the bill, or scales to zero and pays for cold start. Pick Python when the model changes more often than the service, when the team that owns the model also owns the endpoint, or when the request rate is low enough that a 640 MB process is simply not a problem.

The honest middle ground that most teams land on: keep the Python service while the model is still moving, and port to Rust only the endpoint whose p99 has a pager attached. Both versions here are small enough to rewrite against your own model in an afternoon, and the numbers on your hardware will be more persuasive than mine.

## Related

- [Go vs Node.js for a small JSON API]({% post_url Languages/2026-11-12-go-vs-nodejs-json-api %}): the same methodology on a workload where the runtime, not the model, is the bottleneck.
- [Rust vs Go for a CLI tool]({% post_url Languages/2026-10-16-rust-vs-go-cli-tool %}): Rust's build and binary-size trade-offs on a different workload.
- [Python vs Go for a batch log job]({% post_url Languages/2026-10-20-python-vs-go-batch-log-job %}): Python against a compiled language on a throughput-bound job.
