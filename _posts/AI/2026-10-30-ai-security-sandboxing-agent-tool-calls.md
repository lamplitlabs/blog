---
layout: post
title: "Sandboxing Agent Tool Calls: Keep the Secrets Out of the Blast Radius"
date: 2026-10-30 04:30:00 +0100
categories: ai
description: "Sandbox every AI agent tool call: per-call sandbox schemas, isolated execution, environments with no secrets, and output scanning before results come back."
image:
  path: /assets/img/posts/ai/ai-security-sandboxing-agent-tool-calls.webp
  alt: "Poster-style blueprint titled Tool-Call Sandbox: five isolated vault chambers hold the tool calls fs.read, net.fetch, shell.exec and browser.open behind green outlines, while a fifth chamber labelled secrets.get glows red as a tamper claw fails to breach it, with keyhole vaults above each chamber and isolated network bubbles below."
tags: [ai-security, sandboxing, agents, secrets, llm, isolation, egress, policy, least-privilege]
---

Your coding agent decides to "debug" a failing test by printing `os.environ`. Your support agent, asked to summarize a ticket, helpfully includes the API key the customer pasted into it. Nobody wrote an attack; the model just reached for whatever was in reach. In the [previous post on prompt injection defenses]({% post_url AI/2026-10-29-ai-security-prompt-injection-defenses-agents %}) we covered how to stop an attacker from *talking* your agent into misbehaving. This post is about the layer underneath: when the agent - tricked, confused, or simply wrong - does try to call a tool, what stops that call from touching your secrets? The answer is sandboxing, and it works even when every defense above it has failed.

![Poster-style blueprint titled Tool-Call Sandbox: five isolated vault chambers hold the tool calls fs.read, net.fetch, shell.exec and browser.open behind green outlines, while a fifth chamber labelled secrets.get glows red as a tamper claw fails to breach it, with keyhole vaults above each chamber and isolated network bubbles below.](/assets/img/posts/ai/ai-security-sandboxing-agent-tool-calls.webp)

## Why least privilege is not enough

The standard advice is "give the agent only the tools it needs." That is necessary and wildly insufficient, for three reasons:

- **Tools are ambient.** If the agent process can read `~/.aws/credentials`, then *every* tool it has - even an innocent `fs.read` - is one path traversal away from your AWS keys. The permission you granted is on the tool; the exposure lives in the environment.
- **Capabilities compose.** `net.fetch` alone is fine. `fs.read` alone is fine. `fs.read` plus `net.fetch` is an exfiltration channel: read a file, POST it somewhere. No single tool policy sees the composition.
- **The decider is probabilistic.** The model decides *which* tool to call and with *what* arguments, and it can be steered by the content it reads (the injection post) or simply by a bad day in the weights. Static permission lists assume a rational operator. You do not have one.

The fix is to stop treating tool calls as function invocations and start treating them as **untrusted processes**: each call gets its own sandbox, its own filesystem view, its own network policy, and - critically - an environment that contains *no secrets at all*.

## A per-call sandbox decision flow

Every tool call should pass through the same pipeline, regardless of which tool it is:

![Flow diagram of the six-step sandbox decision pipeline: the agent proposes a call with arguments and a reason, the call is risk-classified into read, write or egress, a sandbox schema is built from filesystem, network and environment rules, the call runs in an isolated sandbox, its result is scanned for leaks, and the gate decides commit or discard, with a dashed red arrow showing schema requests for the secrets vault denied by default and every decision landing in a signed audit log.](/assets/img/posts/ai/ai-security-sandbox-decision-flow.webp)

1. **Propose.** The model emits a tool call: name, arguments, and (in a disciplined runtime) a reason. Treat all of it as untrusted input.
2. **Classify.** Map the call to a risk band - read, write, or egress - based on the tool *and the arguments*. `fs.read` of `./src/main.rs` is a read; `fs.read` of `~/.ssh/id_rsa` is an egress attempt, because its only plausible use is to move that data somewhere.
3. **Build the sandbox schema.** From the band, derive the three boundary policies: which filesystem paths are visible, which network destinations are reachable, and what the environment contains (almost always: nothing).
4. **Run isolated.** Execute in a fresh sandbox - a namespace jail, a microVM, a container with a read-only root - that lives for exactly this call. No shared state with other calls, no writable persistence unless the schema grants it.
5. **Scan the result.** Before the tool output goes back to the model, scan it for secrets and exfil-shaped payloads. A `git diff` that accidentally includes `.env` gets redacted here, not after the model has memorized it.
6. **Decide and log.** Commit the result to the conversation or discard it, and record the whole decision - tool, arguments, classification, policy, outcome - in a signed audit log.

The important property is that steps 2 through 6 are **deterministic code**, not model judgment. The model proposes; the sandbox disposes. A prompt injection can make the model *ask* for `secrets.get`; it cannot make the sandbox's environment contain a secret that was never put there.

## The three layers that keep secrets out

![Diagram of the three-layer secrets shield around a running tool: the inner chamber holds the tool with a read-only filesystem and no environment tokens; ring one is environment stripping, ring two is a syscall filter denying open and connect outside the jail, ring three is output scanning that redacts exfil payloads; three red attacker arrows labelled read ~/.aws, POST pastebin and cat /etc/secrets bounce off the outer ring.](/assets/img/posts/ai/ai-security-sandbox-secrets-shield.webp)

### Layer 1: Environment stripping

The single highest-yield control. Most secret leaks in agent systems are not exotic: the agent runs `env`, or reads a file that `source`s a profile, or the tool SDK helpfully passes `os.environ` into a subprocess. The sandbox starts with an *empty* environment and adds back only the variables the schema names - `PATH`, `HOME` pointing at a scratch directory, maybe `LANG`. API keys, cloud credentials, and session tokens never enter. If the task genuinely needs a credential, the sandbox calls a broker outside the jail that holds it, uses it, and returns a result - the key itself never crosses the boundary.

### Layer 2: Syscall and network filtering

Environment stripping removes the *data*; this layer removes the *moves*. A seccomp-style syscall filter denies `open` outside the mounted paths and `connect` to anything not on the egress allowlist. This is what stops the composition attack from the [tool egress post]({% post_url AI/2026-10-27-ai-security-llm-data-exfiltration-agent-tool-egress %}): `fs.read` inside the jail can read only what was mounted in, and `net.fetch` can reach only the allowlisted hosts, so the read-then-POST channel has no second leg.

### Layer 3: Output scanning

Defense in depth for the failure mode where the first two layers are misconfigured. Scan tool output for secret patterns, tokens, and suspiciously large base64 blobs before it reaches the model context. This layer is a scanner, not a boundary - it will have false positives - but it turns a silent leak into a logged event, and a logged event into a policy fix.

No single layer is trusted to hold. That is the point of calling it a shield: you assume each ring has holes and you overlap them.

## A sandbox schema in practice

The schema is where policy becomes concrete. Keep it data, not code, so it can be reviewed, versioned, and diffed:

```yaml
tool: shell.exec
risk: write
sandbox:
  image: ghcr.io/example/agent-exec:1.4
  fs:
    mount_ro: ["/repo"]
    mount_rw: ["/tmp/work"]
  net:
    allow: ["github.com:443"]
    deny_all_others: true
  env:
    allow: ["PATH", "HOME", "LANG"]
  limits:
    cpu_seconds: 30
    memory_mb: 512
    max_output_kb: 64
  secrets: deny          # no broker access from this sandbox
```

Two things to notice. First, `deny_all_others: true` - egress is opt-in per destination, which is the same posture the egress post recommends at the gateway, pushed down into the sandbox itself. Second, `secrets: deny` is explicit. Every schema should answer the question "can this call reach a secret?" with a word you can grep for, not with an absence you have to infer.

## Failure modes worth planning for

- **Sandbox escape through the tool itself.** If your `shell.exec` sandbox runs a container with a shared kernel, a kernel exploit is a sandbox escape. For high-risk tools, use a microVM (Firecracker-style) so the blast radius stops at a VM boundary, not a cgroup.
- **Legitimate work that looks like exfiltration.** A test suite that reads fixtures from `$HOME` will break under environment stripping, and the team's first instinct will be to loosen the sandbox globally. Resist this: mount the fixtures into `/tmp/work` in the schema for that tool, and keep the global posture.
- **Secret-shaped non-secrets.** Output scanning will flag UUIDs, hashes, and minified blobs. Tune the scanner on your own corpus before you let it block results, or people will route around it.
- **The audit log nobody reads.** A signed log of every decision is only useful if someone - or something - replays it. Alert on the *crossing* of budgets and deny counts, not on the breach.

## A starting sequence

1. **Inventory the tools** your agents can call today, and classify each as read, write, or egress *by arguments*, not by name.
2. **Strip the environment** for every execution path. This is usually one afternoon and removes the most common leak vector outright.
3. **Jail the high-risk tools first** - `shell.exec` and anything with network access - with read-only roots and per-destination egress.
4. **Add output scanning** for the two or three secret classes you actually hold.
5. **Log every decision** and verify you can answer "which sandbox saw which file at 03:12 on Tuesday?" before you need to.

## Where Pulse fits

We are building Pulse, Lamplit Labs' multi-project self-improving automation product, and its agents run under exactly this discipline: every tool call is classified, sandboxed, and scanned before the result re-enters the conversation, and every decision lands in a signed audit log. Autonomous agents that can reach your secrets are not automation; they are an incident report with a scheduler. Pulse is coming soon - if agent governance is on your 2027 roadmap, that is the problem we are building it to solve. We wrote about [how Pulse improves this very blog]({% post_url AI/2026-10-25-pulse-internal-rsi-tool %}) last week.

## Related posts

- [AI Security: Prompt Injection Defenses That Actually Work for Coding Agents]({% post_url AI/2026-10-29-ai-security-prompt-injection-defenses-agents %})
- [AI Security: LLM Data Exfiltration via Agent Tool Egress]({% post_url AI/2026-10-27-ai-security-llm-data-exfiltration-agent-tool-egress %})
- [AI Security: Map Your Model Supply Chain Attack Surface Before Someone Else Does]({% post_url AI/2026-10-25-ai-security-model-supply-chain-attack-surface %})
- [Inside Pulse: The Self-Improving RSI Tool We Use to Improve This Blog]({% post_url AI/2026-10-25-pulse-internal-rsi-tool %})
