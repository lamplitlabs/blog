---
layout: post
title: "vLLM vs TGI vs TensorRT-LLM: LLM Serving Latency and Throughput on One H100, Measured at p99"
date: 2026-11-10 00:00:00 +0200
categories: performance ai
tags: vllm tgi tensorrt-llm llm-inference gpu h100 llama performance benchmark enterprise-ai
author: manishtiwari25
description: "Same Llama 3.1 8B, same H100, 128 concurrent chat users. TTFT p99: TensorRT-LLM 286 ms, vLLM 412 ms, TGI 538 ms; throughput and setup cost decide it."
image:
  path: /assets/img/headers/performance/vllm-vs-tgi-vs-tensorrt-llm-serving-latency.webp
  alt: "Bar chart comparing LLM serving frameworks on one H100 at 128 concurrent users: TTFT p99 vLLM 412 ms, TGI 538 ms, TensorRT-LLM 286 ms, with output throughput 2,910, 2,340 and 3,870 tokens per second"
---

Once a team decides to self-host an open-weights model instead of paying per token, the next design review question is always "which server?" The three names on the whiteboard are [vLLM](https://github.com/vllm-project/vllm), Hugging Face [Text Generation Inference](https://github.com/huggingface/text-generation-inference) (TGI) and NVIDIA [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM) behind Triton. Each project publishes numbers that make itself look best, usually at a batch size nobody runs in production. This post is one model, one GPU, one realistic chat workload, and the latency numbers a copilot team actually puts in an SLO: time to first token (TTFT) and time per output token (TPOT) at p99, plus the aggregate throughput that sets the bill.

The SLO targets come from the [cost and latency SLO post]({% post_url AI/2026-10-06-enterprise-ai-llm-cost-latency-slos-production %}): TTFT p99 under 500 ms and TPOT p99 under 60 ms, so that a streamed answer starts before the user notices and types faster than they read.

## The setup

- Model: `meta-llama/Llama-3.1-8B-Instruct`, BF16 weights for all three servers, no quantization, 8k context limit. Quantization changes the ranking and deserves its own post.
- Hardware: one H100 80GB SXM on a Lambda on-demand instance (26 vCPU, 225 GB RAM), CUDA 12.4, driver 550. One container at a time, GPU clocks left at default.
- Servers: vLLM 0.6.3 (`--max-num-seqs 256 --gpu-memory-utilization 0.92`), TGI 2.4 (`--max-concurrent-requests 256 --max-batch-prefill-tokens 8192`), TensorRT-LLM 0.14 engine built with `--max_batch_size 256 --use_paged_context_fmha enable` and served through Triton 24.10 with in-flight batching on. Prefix caching was enabled on all three since every chat request shares a 400-token system prompt.
- Workload: 2,048 prompts sampled from ShareGPT, mean input 612 tokens, mean output 231 tokens, system prompt prepended. Load generator is vLLM's `benchmark_serving.py` pointed at the OpenAI-compatible endpoint of each server, `--max-concurrency 128`, streaming on, warm-up of 200 requests discarded. Three runs each; the middle run is reported. Latencies are measured client side over loopback.
- Fairness rule: each server was tuned until the error rate was 0 and no request was rejected. The first TGI run with defaults queued and failed 1.4% of requests at this concurrency, so `--max-concurrent-requests` was raised before measuring.

Startup cost is real operational time and belongs in the table:

| Server | Install to first token | Engine/compile step | Container image |
|---|---|---|---|
| vLLM 0.6.3 | 4 min 20 s | none (CUDA graphs captured at start, 48 s) | 9.8 GB |
| TGI 2.4 | 3 min 55 s | none (warm-up 31 s) | 11.2 GB |
| TensorRT-LLM 0.14 | 41 min | checkpoint convert 6 min + engine build 27 min, per GPU type and per max shape | 22.4 GB |

## The headline: 128 concurrent chat users

![Terminal output of benchmark_serving.py for the three servers on one H100: vLLM 15.53 req/s, 2,910 output tok/s, TTFT p99 412 ms, TPOT p99 58.3 ms; TGI 12.49 req/s, 2,340 tok/s, TTFT p99 538 ms, TPOT p99 71.2 ms; TensorRT-LLM 20.66 req/s, 3,870 tok/s, TTFT p99 286 ms, TPOT p99 41.9 ms](/assets/img/posts/performance/vllm-tgi-trtllm-benchmark-serving-output.webp)

| Server | Req/s | Output tok/s | TTFT p50 | TTFT p99 | TPOT p50 | TPOT p99 | ITL p99 |
|---|---|---|---|---|---|---|---|
| vLLM 0.6.3 | 15.53 | 2,910 | 171 ms | 412 ms | 30.4 ms | 58.3 ms | 94.7 ms |
| TGI 2.4 | 12.49 | 2,340 | 219 ms | 538 ms | 37.9 ms | 71.2 ms | 118.5 ms |
| TensorRT-LLM 0.14 | 20.66 | 3,870 | 122 ms | 286 ms | 23.1 ms | 41.9 ms | 66.3 ms |

Against the SLO: TensorRT-LLM clears both targets with headroom, vLLM clears both narrowly (412 ms and 58.3 ms against 500 and 60), and TGI misses both at this load. TensorRT-LLM delivers 33% more output tokens per second than vLLM and 65% more than TGI on the same card, which, if the GPU is the cost unit, is the cost difference.

The inter-token latency (ITL) p99 column is the one users feel as stutter. All three show a p99 well above their TPOT p99 because of the same cause: a new request's prefill landing in the batch and delaying everyone's next decode step. TensorRT-LLM's chunked context and vLLM's `--enable-chunked-prefill` (on by default in 0.6) soften this; TGI's prefill is less finely chunked and shows the largest gap.

## Latency as load changes

The 128-user point is where the differences are largest. The same benchmark at lower and higher concurrency:

| Concurrency | vLLM TTFT p99 / tok/s | TGI TTFT p99 / tok/s | TensorRT-LLM TTFT p99 / tok/s |
|---|---|---|---|
| 8 | 94 ms / 486 | 101 ms / 452 | 71 ms / 571 |
| 32 | 168 ms / 1,420 | 214 ms / 1,255 | 118 ms / 1,790 |
| 128 | 412 ms / 2,910 | 538 ms / 2,340 | 286 ms / 3,870 |
| 256 | 1,180 ms / 3,140 | 1,960 ms / 2,410 | 690 ms / 4,210 |

Two things to read off this. First, at 8 users the three are within 30 ms of each other and all comfortably in SLO; if a team's internal tool has a dozen concurrent users, the choice of server is an operations decision, not a performance one. Second, past 128 users every server runs out of KV cache and queues; throughput plateaus while TTFT explodes. The right response is a second GPU, not more tuning, and the point where that happens is 128 users for TGI, around 160 for vLLM and around 200 for TensorRT-LLM in this configuration.

## Where the time goes

`nsys` traces of 30 s windows at 128 concurrency, kernel time as a share of GPU wall time:

| Server | Attention kernels | GEMM | Sampling + glue | GPU idle |
|---|---|---|---|---|
| vLLM | 31% | 49% | 8% | 12% |
| TGI | 30% | 46% | 9% | 15% |
| TensorRT-LLM | 27% | 58% | 6% | 9% |

TensorRT-LLM's advantage is not a smarter scheduler; it is fused kernels. Its GEMMs are compiled for the exact shapes and the attention runs in fused FP8-capable kernels even with BF16 weights, so more of the wall time is spent doing useful matrix work and less in launching small kernels. vLLM's 12% idle is mostly Python scheduler overhead between steps, which the 0.6 series has already cut substantially from 0.4 (measured 21% on the same box). TGI's extra idle comes from the Rust router to Python shard hop on every batch.

## What I would actually recommend

- **Default to vLLM.** It clears the SLO at 128 users, starts in minutes, tracks new model architectures within days of release, and the OpenAI-compatible endpoint means the [model routing layer]({% post_url AI/2026-10-15-enterprise-ai-model-routing-azure-openai-apim %}) does not change. Most teams should stop here.
- **Move to TensorRT-LLM when GPU count is the bill.** A third more tokens per H100 pays for the 41-minute engine build quickly on a fleet of ten cards. It does not pay for it on one card, and every model update or max-length change means a rebuild per GPU type, so budget the pipeline work.
- **TGI if you are already deep in the Hugging Face stack** and run below about 64 concurrent users per GPU, where it is within SLO and its model loading and tokenizer handling are the smoothest of the three. At higher load it needs more GPUs than the others for the same traffic.
- Whatever you pick, put TTFT and TPOT p99 on the dashboard per model, not just request latency; a 231-token answer at 60 ms/token is 14 s of request latency that is perfectly healthy, and a 2 s request latency can be a stalled stream.

Benchmark scripts, server configs and the raw CSVs for all runs are in the repository linked from the benchmark, so the table can be rerun when the next version of each server lands; all three move fast enough that these numbers have a shelf life of months.

## Related

- [Enterprise AI: Cost and Latency SLOs for LLM Workloads](/posts/enterprise-ai-llm-cost-latency-slos-production/) - where the 500 ms TTFT and 60 ms TPOT targets come from.
- [Enterprise AI: Azure OpenAI PTU vs Pay-as-you-go Under Sustained Load](/posts/enterprise-ai-azure-openai-ptu-vs-pay-as-you-go-sustained-load/) - the managed alternative to self-hosting, measured the same way.
- [Enterprise AI: Model Routing with Azure OpenAI and APIM](/posts/enterprise-ai-model-routing-azure-openai-apim/) - the layer that lets you swap one of these servers in behind an existing endpoint.
