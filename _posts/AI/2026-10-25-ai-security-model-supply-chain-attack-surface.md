---
layout: post
title: "AI Security: the model supply chain is the attack surface you already deployed"
description: "Model weights, datasets and eval harnesses are unsigned dependencies most teams never audit. Map the attack surface and the checks that catch poisoned artifacts"
date: 2026-10-25 14:05:00 +0000
categories: ai
tags: ai security model supply-chain machine-learning enterprise ai
image:
  path: /assets/img/headers/ai/ai-supply-chain-attack-surface.webp
  alt: "The ML supply chain from dataset and training code to the deployed model, with three checkpoints: integrity, evaluation and policy gates"
pin: false
math: false
mermaid: false
---

[Prompt injection defences for coding agents]({% post_url AI/2026-10-11-ai-sdlc-prompt-injection-defences-for-coding-agents %}) cover what happens when an attacker talks *to* your model. This post is about the quieter problem: what happens when the attacker ships *inside* it. Every model weight file, dataset and eval harness you consume is a build artifact from somebody else's machine, and most teams pull them with less scrutiny than they would give a random npm package.

We hit this ourselves building the eval loops behind Pulse, our internal automation. A fine-tune we were testing pulled a "community-cleaned" dataset from a hub repository, and the only reason the run was reproducible was that we had pinned the revision hash. The repository was force-updated two days later with no changelog. Nothing malicious happened - but nothing would have told us if it had.

## Three artifact classes, three failure modes

The ML supply chain has more moving parts than the software one because a model is code *and* data *and* process, and each is poisoned differently.

**Model weights are executable.** The classic vector is pickle: `torch.load()` on a `.pt` or `.pth` file calls the Python unpickler, which runs arbitrary code on your GPU host before you ever see a tensor. The pickle file is not "a model that might be malicious"; it is a program that might also contain a model. Safetensors exists precisely to close this - the format is a pure data container with no code path - but hubs are still full of pickle-format uploads, and `trust_remote_code=True` re-opens the same door with a friendlier label: it downloads and executes a modeling file from the repository author on every load.

**Datasets are instruction sources.** A poisoned dataset does not need to crash anything. Research on data poisoning has shown that a tiny fraction of crafted examples - backdoor triggers in sentiment data, look-alike package names inserted into code corpora - survives deduplication and shows up in the trained model's behaviour. The supply-chain version is nastier than the research version: you did not collect the data, you cannot eyeball a million rows, and the poisoning can be upstream of the person you downloaded it from.

**Eval harnesses are privileged code.** Your evaluation script reads the secret test set, runs with your credentials, and its number decides whether a model ships. A "helpful" eval utility pulled from a hub or a copied repository is code execution with access to your most sensitive assets, and it runs before any of your inference-time defences exist. The blast radius of a compromised eval is not a wrong answer; it is a leaked test set and a green checkmark on a poisoned model.

![The ML supply chain with the attack surface at each hop](/assets/img/posts/ai/ai-supply-chain-attack-surface.webp)

The diagram is the argument: your inference-time controls (the red team, the output filters, the guardrails) all sit *after* the point where weights, data and eval code were already loaded and executed on your hardware. Defending the last hop while the first three are unauthenticated is locking the front door of a house you built from untraceable parts.

## The checks that actually catch things

None of this requires a vendor platform. It requires treating ML artifacts like the dependencies they are:

1. **Pin by hash, not by name.** `revision=` on every hub download, commit hashes on datasets, lockfiles for the eval environment. "Latest" is not a version; it is a permission slip for silent change. When the upstream moves, the diff between hashes is a reviewable event instead of a surprise.
2. **Refuse code paths in model artifacts.** Load safetensors where they exist; treat `trust_remote_code=True` and pickle formats as a Tier-2 decision that needs a human sign-off, a sandbox and a network-denied loader. A weight file that needs to execute code to be read is not a weight file.
3. **Sign and verify, even internally.** Sigstore-style signing for models is young, but nothing stops you from signing your *own* fine-tuned artifacts and datasets at training time and verifying at deploy time. The threat model "someone swapped the file in the bucket" is common and cheap to close with a checksum in a second system.
4. **Provenance over provenance theatre.** Record for every deployed model: which base weights (hash), which dataset snapshot (hash), which training and eval code (commit), on which runner. If you cannot answer those four questions for the model in production right now, that is the gap - not the exotic backdoor.
5. **Keep the eval clean.** Pin the harness, hash the test set, run evals in the same locked-down environment as training, and treat a changed eval result the way you would treat a changed checksum: investigate before celebrating.

## Where this connects to the rest of the SDLC

The pattern is the one from our [playbook for AI-generated code review]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %}): every class of defect gets exactly one deterministic gate, added when the failure mode is understood. "Verify model hashes" is the AI equivalent of dependency lockfiles - boring, scriptable, and the precondition for trusting anything downstream. And as with prompt injection, the point is not a model that behaves; it is a system that does not depend on the model behaving.

## Related posts

- [AI SDLC: prompt injection defences for coding agents, in layers]({% post_url AI/2026-10-11-ai-sdlc-prompt-injection-defences-for-coding-agents %})
- [AI SDLC: gating AI coding agent pull requests before merge]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %})
- [AI SDLC: gating AI coding agent pull requests before merge]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %})
- [AI SDLC for .NET Teams: a phase-by-phase guide]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %})
