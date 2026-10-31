---
title: "GGUF vs AWQ vs GPTQ: what 4-bit quantization really costs in quality and latency"
date: 2026-10-28 09:00:00 +0000
categories: [ai]
tags: [quantization, gguf, awq, gptq, llama.cpp, vllm, inference, model-compression, fine-tuning]
description: "GGUF Q4_K_M, AWQ and GPTQ 4-bit variants of one 8B model benchmarked for perplexity and serving throughput - when each wins and when 4-bit breaks."
image:
  path: /assets/img/headers/ai/quantization-gguf-vs-awq-vs-gptq-quality-latency.webp
  alt: "Scatter chart of 4-bit quantization variants plotting quality kept against tokens per second, with AWQ W4-g128 marked as the best server tradeoff and GGUF Q3_K_M and ungrouped GPTQ trailing in quality."
---

You fine-tuned a model, it passes the eval gates, and now finance asks why a 16&nbsp;GB checkpoint needs a 40&nbsp;GB GPU to serve. The answer is 4-bit quantization - and the follow-up question, *which* 4-bit format, has three incompatible answers depending on where the model runs. This post compares GGUF, AWQ and GPTQ on the two numbers that matter - quality kept and tokens per second - and gives you a decision rule that survives contact with production.

## The three formats in one paragraph each

**GGUF** (llama.cpp) is a *file format*: a single `.gguf` blob with the tokenizer, metadata and quantized tensors, built for CPU/Metal/CUDA inference on a laptop or a small box. Quantization levels like `Q4_K_M` are hand-tuned mixes - important tensors get 5-6 bits, the rest 4.

**GPTQ** is an *algorithm*: it quantizes weights one layer at a time, using a calibration set to adjust the remaining weights so the layer's output changes as little as possible. Grouped variants (`g128`) re-fit the scale every 128 weights, which is where most of the quality win lives.

**AWQ** (Activation-aware Weight Quantization) protects the ~1% of weights that see the largest activations instead of treating all weights equally. It quantizes *for* the GPU: its output is a safetensors checkpoint that vLLM and TensorRT-LLM load directly with a fused Marlin kernel.

## Setup

- Base model: Llama-3-8B-Instruct, fp16 baseline (16.1&nbsp;GB)
- Quality: perplexity on wikitext-2 via `llama-perplexity`, plus our internal 200-prompt regression eval
- Latency: vLLM `benchmark_serving.py`, 1000 prompts at 16 req/s, A100 40&nbsp;GB; GGUF measured with llama.cpp server on the same box
- Quantization: AWQ and GPTQ produced with AutoAWQ / AutoGPTQ, 1024 calibration samples, group size 128

## Quality: 4-bit is nearly free, 3-bit is not

![Terminal output of llama-perplexity runs showing wikitext-2 perplexity: fp16 6.142, AWQ 6.287 (+2.4%), GGUF Q4_K_M 6.302 (+2.6%), grouped GPTQ 6.389 (+4.0%), while GGUF Q3_K_M degrades +13.0% and ungrouped GPTQ +15.9%](/assets/img/posts/ai/quantization-gguf-awq-gptq-perplexity.webp)

Three things to take from the run:

1. **Grouped 4-bit variants cluster within 2-4% of fp16.** On the internal regression eval, AWQ lost 0.4 points of accuracy - well inside the gate tolerance we set in the fine-tuning pipeline post.
2. **The group size matters more than the algorithm.** Ungrouped GPTQ collapses (+15.9% perplexity); the same GPTQ at g128 is competitive with AWQ.
3. **Q3 is a cliff.** `Q3_K_M` saves 1&nbsp;GB over `Q4_K_M` and pays for it with a 13% perplexity jump. Unless the model physically does not fit otherwise, stay at Q4 or above.

## Latency: the runtime matters more than the format

![Terminal output of vLLM benchmark_serving results showing AWQ at 4218 tokens per second with up to 64 concurrent requests, GPTQ at 3984, fp16 limited to about 34 concurrent requests by KV cache memory, and GGUF via llama.cpp serving far fewer concurrent requests but 58 tokens per second for a single user](/assets/img/posts/ai/quantization-gguf-awq-gptq-vllm-throughput.webp)

The headline: **AWQ and GPTQ under vLLM beat fp16 on throughput at high concurrency** - not because 4-bit arithmetic is magically faster, but because the weights take 11&nbsp;GB less VRAM, and that memory becomes KV cache. FP16 hits its context budget around 34 concurrent requests; the 4-bit checkpoints still have headroom at 64.

GGUF tells a different story. llama.cpp does continuous batching now, but it is not vLLM: aggregate throughput at 8 concurrent users is a fraction of what AWQ/vLLM sustains. Where GGUF wins is the *other* end of the spectrum - a single user at 58 tok/s on a box with no datacenter GPU at all, including an M-series laptop over Metal.

## Continuous batching: the other half of serving throughput

Quantization shrinks the bytes each decode step reads. Batching decides how many users share each read. A decode step is memory-bound: the GPU streams the whole weight file to produce one token per sequence, so a step that carries 8 sequences costs only a little more than a step that carries 1. *Continuous* (in-flight) batching is the scheduler that keeps those slots full. It admits a new request at the next decode step instead of waiting for the slowest member of the current batch to finish.

We measured it on hardware anyone can reproduce: a 3.1B-parameter SmolLM3-architecture model as GGUF `Q4_K_M` (1.9&nbsp;GB), llama.cpp build 11669 on an Apple M2 Pro over Metal, flash attention on, one unified KV cache (`-kvu`), 16k context.

![Two charts from a llama.cpp benchmark on an Apple M2 Pro with a Q4_K_M GGUF model. Top: aggregate decode throughput grows from 72 tokens per second at batch 1 to 273 at batch 8 and 403 at batch 32, while the speed each sequence sees falls from 72 to 34 to 13 tokens per second. Bottom: under the same 48-request load, time to first token at p95 is 98 seconds serial, 40 seconds with static batching, 8.5 seconds with continuous batching over 8 slots and 1.3 seconds over 16 slots, while throughput rises from 67 to 112 to 163 tokens per second](/assets/img/posts/ai/continuous-batching-llama-cpp-throughput-latency.webp)

**Batch size is a throughput-for-latency trade.** `llama-batched-bench` ran each sweep three times (256-token prompt, 128 new tokens per sequence), and the table shows the medians:

| Batch | Q4_K_M total tok/s | Per sequence | Q8_0 total tok/s |
|---:|---:|---:|---:|
| 1 | 72 | 72 | 49 |
| 2 | 91 | 46 | 91 |
| 4 | 155 | 39 | 174 |
| 8 | 273 | 34 | 298 |
| 16 | 298 | 19 | 304 |
| 32 | 403 | 13 | 446 |

Going from 1 to 8 sequences buys 3.8x the throughput for a 2.1x slower stream per user. That is the cheap part of the curve. Past 8, the kernel stops being bandwidth-bound and becomes compute-bound: 16 sequences add only 9% throughput while each user's stream halves. The last column is the quantization twist. At batch 1, `Q4_K_M` is 1.46x faster than `Q8_0` because it reads half the bytes. From batch 2 onward the advantage disappears, and at 32 sequences `Q8_0` is 10% *faster*. That is consistent with the step having turned compute-bound: the K-quant dequantization work now costs more than the bandwidth it saves. A 4-bit format buys single-user speed and memory headroom, not batched throughput.

**Continuous beats static batching on both axes.** The microbenchmark runs batches in lockstep, which real traffic never does. So we put `llama-server` under open-loop load: 48 requests arriving over 36 seconds, 64-256 token prompts, and output lengths from 32 to 512 tokens (9,600 generated tokens in all). We kept the model and the box, and changed only the scheduler:

| Server config | Tok/s | TTFT p50 | TTFT p95 | E2E p95 |
|---|---:|---:|---:|---:|
| serial, `-np 1` | 67 | 53.7 s | 98.3 s | 101.9 s |
| static, `-np 8 -nocb` | 112 | 17.7 s | 40.3 s | 47.3 s |
| continuous, `-np 8` | 163 | 4.0 s | 8.5 s | 26.0 s |
| continuous, `-np 16` | 162 | 0.3 s | 1.3 s | 36.2 s |

With `-nocb`, the server admitted no request while another was still decoding: 0 of 48. A 32-token answer waited behind a 512-token one, and the first-token log shows arrivals queued up and released in waves. With continuous batching on, 47 of 48 requests joined a batch that was already running. The same 8 slots served 46% more tokens per second and cut p95 time to first token from 40 seconds to 8.5.

**More slots trade inter-token latency for queueing.** Doubling to 16 slots kept throughput flat (162 vs 163 tok/s, because the GPU was already compute-bound, as the sweep predicted). It nearly eliminated queueing: TTFT p95 fell from 8.5 to 1.3 seconds. The cost lands on each token after the first. Median time per output token rose from 39 to 70 ms, so long answers finish later (end-to-end p95 rose from 26 to 36 seconds). Pick the slot count from the SLO you actually sell. A chat UI that must show the first token fast wants more slots. A batch summarization job that is billed by completion wants fewer.

What carries over to vLLM on an A100: the same curve, shifted right. vLLM's paged KV cache is what lets AWQ hold 64 concurrent sequences where fp16 tops out near 34 (the chart above), and continuous batching is what keeps those 64 slots full. Two settings to tune before buying another GPU:

- **Slot count**: `--max-num-seqs` in vLLM, `-np` in llama.cpp. Raise it until throughput stops growing. Every slot past that point only moves latency from the queue into the token stream.
- **Per-step token budget**: `--max-num-batched-tokens` in vLLM, `-b`/`-ub` in llama.cpp. It caps how much prefill a single step can carry. Long prompts admitted mid-stream stall the decoders already running, which shows up as inter-token latency spikes on the users who were already streaming.

To reproduce the batch sweep on your own model: `llama-batched-bench -m model.gguf -c 16384 -kvu -fa on -npp 256 -ntg 128 -npl 1,2,4,8,16,32`.

## Decision rule

| If you are... | Ship | Why |
|---|---|---|
| Serving production traffic on GPUs | **AWQ** (or grouped GPTQ) | Fused kernel + KV-cache headroom; smallest quality hit under vLLM |
| Running on a laptop, edge box, or CPU | **GGUF Q4_K_M** | Only format llama.cpp/ollama run everywhere; Q4_K_M is the quality sweet spot |
| Squeezing a 70B into one 24&nbsp;GB card | GGUF Q4_K_M with partial offload | ExLlama/GPTQ exists, but llama.cpp offload is the boring, working path |
| Below 4 bits to fit at all | Reconsider the model size | A Q8 3B beats a Q2 13B on quality in every comparison we ran |

Two operational notes:

- **Quantize *after* merging.** If you fine-tuned with LoRA, merge the adapter into the base weights first, then quantize - quantizing the base and adding the adapter back reintroduces fp16 memory and breaks the calibration assumptions.
- **Re-run the eval gates on the quantized artifact**, not on the fp16 checkpoint. The quantization step is a model change; the same regression gates that guard fine-tuning should guard it.

## Related posts

- [vLLM vs TGI vs TensorRT-LLM: self-hosted LLM serving latency](/posts/vllm-vs-tgi-vs-tensorrt-llm-serving-latency/) - the serving layer where AWQ and GPTQ checkpoints actually run.
- [LoRA vs QLoRA vs full fine-tuning: the GPU memory, cost, and eval-score tradeoffs](/posts/lora-vs-full-fine-tuning-cost-quality-enterprise/) - the upstream decision; quantization happens after the merge.
- [Fine-tuning pipelines need regression gates before the first run](/posts/fine-tuning-pipeline-regression-gates/) - where the quantized artifact's eval delta belongs.
- [Fine-tuning data curation: eval set construction](/posts/fine-tuning-data-curation-eval-set-construction/) - build the eval set *before* you need it to catch a quantization regression.
- [Enterprise AI: Self-Hosted Llama 3.1 70B on vLLM vs Azure OpenAI - Cost and Latency at 1.4 B Tokens a Month](/posts/enterprise-ai-self-hosted-llm-vs-azure-openai-cost-latency/) - the fleet-level cost model that quantization changes.
