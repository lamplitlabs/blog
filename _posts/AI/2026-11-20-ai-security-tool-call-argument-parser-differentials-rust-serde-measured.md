---
layout: post
title: "AI Security: Your Tool Gate and Your Rust Executor Read Different JSON, Measured"
date: 2026-11-20 00:15:00 +0100
categories: ai
tags: [ai-security, rust, serde, agents, prompt-injection, tool-calling, benchmark, llm]
author: manishtiwari25
description: "79 read_file argument strings, 7 policy gates, 5 serde executors, real canary reads: a Go encoding/json gate let 13 through to a serde struct."
image:
  path: /assets/img/headers/ai/ai-security-tool-args-parser-differential.webp
  alt: "Header card titled Your tool gate and your serde executor read different JSON: 79 read_file argument strings run through 7 gates and 5 Rust executors with real canary reads. Bars of canary reads with fail-closed gates: Go encoding/json gate in front of a serde struct 13, regex gate in front of serde_json::Value 14, JSON.parse or json.loads gate in front of a serde struct 1, any gate in front of deny_unknown_fields plus canonicalize 0. Apple M2 Pro, rustc 1.95.0, serde_json 1.0.154, go1.27.2, node 22."
---

A model asks to call a tool. Before the call runs, a policy gate checks the arguments: is `path` inside the workspace, and is there no `..` in it? If yes, the tool server runs the call. Most agent stacks have this shape. The gate is often a hook script, a Python or Node proxy, or a Go sidecar. The tool server is often Rust.

Both sides receive the same thing: the `arguments` field of the tool call. That field is a **string of JSON text**, not an object. So the gate parses it once and the executor parses it again, often with a different JSON library. When two parsers disagree about what one string means, the gate approves one path and the executor opens another. Prompt injection does not need to beat the gate. It only needs to get the model to emit arguments that the two parsers read differently.

I wanted numbers, not a list of what might go wrong. So I built a small sandbox with a canary secret, wrote 79 `read_file` argument strings and ran each one through 7 gates and 5 Rust executors. The executors really open the file. The results:

- **A Go `encoding/json` gate in front of a default serde struct let 13 of 70 attack strings read the canary.** Twelve of them used one trick: a second key that differs only in case, `{"path": "secrets/canary.env", "PATH": "workspace/README.md"}`. Go matches field names case-insensitively, and the last match wins, so the gate saw the workspace path. serde matches exactly and read `secrets/canary.env`.
- **Python, Node, jq, Go `encoding/json/v2` and a Rust `serde_json::Value` gate each let 1 through,** with any executor. That one is a symlink inside the workspace. No JSON parser can catch it.
- **A regex gate in front of `serde_json::Value` let 14 through.** On a duplicate key, the regex keeps the first value and the `Value` map keeps the last.
- **`#[serde(deny_unknown_fields)]` turned the 13 into 1,** and adding `canonicalize()` plus a prefix check in the executor turned every row into **0 canary reads**. The serde side costs tens of nanoseconds. The canonicalize check costs 13.5 µs per call.

Everything below comes from `scripts/tool-args-differential/` in this blog's repository. One command reproduces it.

## The setup

`bench.py` builds a sandbox root for each run:

```text
root/
  workspace/README.md, workspace/src/main.rs, workspace/Cargo.toml
  workspace/link -> ../secrets
  secrets/canary.env        CANARY_TOKEN=tooldiff-<16 random hex chars>
```

**The policy** is the same in every gate: allow a relative path that starts with `workspace/` and has no `..` component. Each gate reads the arguments its own way, takes `path` out and applies that rule.

**The seven gates:**

| Gate | How it reads `path` |
| --- | --- |
| `python json.loads` | `json.loads(args).get("path")` (Python 3.9.6) |
| `regex on raw text` | `"path"\s*:\s*"([^"]*)"` over the raw string |
| `node JSON.parse` | `JSON.parse(args).path` (Node 22.18.0) |
| `go encoding/json` | `json.Unmarshal` into ``struct{ Path *string `json:"path"` }`` (go1.27.2) |
| `go encoding/json/v2` | the same struct through `encoding/json/v2` |
| `bash + jq -r .path` | `p=$(jq -r '.path // empty' <<<"$args")`, then a `case` glob (jq 1.7.1) |
| `rust serde_json::Value` | `serde_json::from_slice::<Value>(args)?.get("path")` |

**The five executors** are one `read_file` handler written five common ways with serde 1.0.229 and serde_json 1.0.154. Each extracts `path`, joins it to the root and calls `std::fs::read_to_string`:

```rust
#[derive(Deserialize)]                       // "typed": the usual derive
struct ReadFile { path: String }

#[derive(Deserialize)]                       // "typed-deny": the tool schema, strictly
#[serde(deny_unknown_fields)]
struct ReadFileStrict { path: String, #[serde(default)] reason: Option<String> }

#[derive(Deserialize)]                       // "alias": tolerate how models spell the field
struct ReadFileAlias {
    #[serde(alias = "file_path", alias = "filepath", alias = "filename")]
    path: String,
}

// "value": parse to serde_json::Value, then v.get("path")
// "typed-deny-checked": ReadFileStrict, then canonicalize and check the prefix:
fn checked(root: &Path, p: &str) -> Result<PathBuf, String> {
    let ws = root.join("workspace").canonicalize().map_err(|e| e.to_string())?;
    let full = ws.parent().unwrap().join(p).canonicalize().map_err(|e| e.to_string())?;
    if full.starts_with(&ws) { Ok(full) } else { Err(format!("outside workspace: {}", full.display())) }
}
```

**The 79 argument strings** are 9 benign controls and 70 attacks in 9 families. Each attack is built from one of three workspace files and one of two bad paths (`secrets/canary.env` and `workspace/../secrets/canary.env`):

| Family | Count | Example |
| --- | --- | --- |
| duplicate key | 12 | `{"path": "workspace/README.md", "path": "secrets/canary.env"}` and the reverse order |
| case variant | 12 | `{"path": "secrets/canary.env", "PATH": "workspace/README.md"}`, also `Path` |
| alias key | 4 | `{"file_path": "secrets/canary.env"}` with no `path` at all |
| escaped key | 12 | `{"p\u0061th": "secrets/canary.env", "path": "workspace/README.md"}` |
| escaped value | 2 | `{"path": "workspace/\u002e\u002e/secrets/canary.env"}` |
| trailing data | 12 | `{"path": "workspace/README.md"}{"path": "secrets/canary.env"}` |
| type confusion | 6 | `{"path": ["workspace/README.md", "secrets/canary.env"]}` |
| bad Unicode | 8 | a lone surrogate `\ud800`, or `\u0000` followed by `/../../` |
| symlink | 2 | `{"path": "workspace/link/canary.env"}` |

A **canary read** is a cell where the gate allowed the call and the executor's `read_to_string` returned a file whose first line is the canary. The canary changes every run and is never written to the results file.

Gates are scored two ways. **Fail-closed:** a gate that finds no string `path` denies the call. **Fail-open:** a gate denies only a path it found and disliked. Fail-open is the bug you get when the hook says "if path is set and bad, block".

## The result

![Heat-map matrix of canary reads with fail-closed gates: 7 gate rows against 5 Rust executor columns (struct default, struct with deny_unknown_fields, struct with serde alias, serde_json::Value, deny_unknown_fields with canonicalize). Python json.loads, Node JSON.parse, Go encoding/json/v2, bash with jq and Rust serde_json::Value gates have 1 in each of the first four columns and 0 in the last. The Go encoding/json gate has 13, 1, 13, 13, 0. The regex gate has 2, 2, 2, 14, 0. The whole last column is 0.](/assets/img/posts/ai/tool-args-differential-matrix-closed.webp){: width="1500" height="846" }

The row that matters most is **Go `encoding/json` → serde struct: 13 canary reads.** Twelve are the case-variant family. Go's v1 decoder matches JSON keys to struct fields case-insensitively. When both `path` and `PATH` appear, the last one wins. serde ignores `PATH` as an unknown field and reads `path`. One string, two paths:

```text
{"path": "secrets/canary.env", "PATH": "workspace/README.md"}
  go encoding/json gate   -> path = "workspace/README.md"   allow
  serde ReadFile          -> path = "secrets/canary.env"    read: CANARY_TOKEN=...
```

`encoding/json/v2` matches case-sensitively by default and rejects duplicate names. Behind that gate the case-variant family drops to 0.

The **duplicate-key** and **escaped-key** families do *not* get through to the serde structs, because the derive rejects a repeated field (``duplicate field `path` ``). `{"p\u0061th": ...}` is the same key once unescaped, so it is also a duplicate. That rejection is good luck, not design: serde_json's `Value` does not reject duplicates. It keeps the last one, like Python, Node and jq. So an executor written as `from_slice::<Value>()` plus `.get("path")` agrees with those gates, but it disagrees with any gate that keeps the *first* value. The regex is such a gate, and that is where the 14 in the regex row comes from: 6 duplicate-key, 6 escaped-key, 1 escaped-value (the regex sees `\u002e\u002e`, not `..`) and the symlink.

Python and Node don't fail these strings. They *agree* with the `Value` executor (last key wins) and the derive executors reject the strings. The one canary read left in their rows is `workspace/link/canary.env`: a path that passes every string check and resolves to `secrets/`. Only the executor can catch that, and only `canonicalize()` did.

What each gate allowed, before the executor got a say (out of 70 attacks, fail-closed): Python, Node and Rust `Value` allowed 13, jq allowed 16, Go v1 allowed 25, the regex allowed 26 and Go v2 allowed 1. Most of those were then rejected by serde, or failed to open. That is the point: in this setup **serde's strictness was the real control, not the gate.**

### The terminal output

![Terminal panel of bench.txt from one run of bench.py: 79 payloads and 5,530 cells. The fail-closed table lists canary reads per gate across the executors typed, typed-deny, alias, value and typed-deny-checked: python json.loads 1 1 1 1 0, regex on raw text 2 2 2 14 0, node JSON.parse 1 1 1 1 0, go encoding/json 13 1 13 13 0, go encoding/json/v2 1 1 1 1 0, bash with jq 1 1 1 1 0, rust serde_json::Value 1 1 1 1 0, and canonical forwarding total 28. The fail-open table differs in the alias column (5 for most gates, 17 for Go v1) and in Go v2's value column (13).](/assets/img/posts/ai/tool-args-differential-terminal.webp){: width="1500" height="670" }

### Every payload, row by row

`bench.py` also writes `report.html` with one row per argument string: the raw text, each gate's decision and what each executor did. This is a headless Chromium screenshot of it (`shots.sh`), cut to the first rows:

![Headless Chromium screenshot of report.html, a dark table titled read_file arguments: what the gate judged vs what serde executed. Each row shows a family, the raw arguments string, green allow or red deny cells for the 7 gates, and read, reject, error or a red CANARY cell for the 5 serde executors. The benign rows are green allow and read everywhere. The duplicate-key row with secrets/canary.env first and workspace/README.md last is allowed by the regex gate and shows CANARY under serde_json::Value. The case-variant row with PATH is allowed only by the Go encoding/json gate and shows CANARY under three executors.](/assets/img/posts/ai/tool-args-differential-report.webp){: width="1440" height="1100" }

## Fail-open makes the alias executor worse

![Heat-map matrix of canary reads with fail-open gates, which deny only a path they found and disliked: Python, Node, jq and Rust Value gates have 1, 1, 5, 1, 0; the regex gate has 2, 2, 6, 14, 0; Go encoding/json has 13, 1, 17, 13, 0; Go encoding/json/v2 has 1, 1, 5, 13, 0. The deny_unknown_fields with canonicalize column stays at 0 for every gate.](/assets/img/posts/ai/tool-args-differential-matrix-open.webp){: width="1500" height="846" }

Two things change when the gate says "no `path`, nothing to check, allow":

- **`#[serde(alias = "file_path")]` gains 4 canary reads in every row.** `{"file_path": "secrets/canary.env"}` has no `path` key, so the gate passes it, and the alias makes serde treat `file_path` as `path`. Aliases are popular in tool servers because models often write `file_path` or `filename`. Every alias is a second name the gate must also know about.
- **Go v2 + `Value` goes from 1 to 13.** v2 *rejects* duplicate keys with an error. A fail-closed gate denies on that error. A fail-open gate sees "no path" and allows. Then `serde_json::Value` takes the last duplicate. So the strictest parser in the test becomes a bypass when its error is treated as "nothing to check".

## The fix: forward what you checked, and check in the executor

I tested two fixes.

**1. Canonical forwarding.** The gate does not forward the model's bytes. It forwards its own re-serialisation, `{"path": <the path it checked>}`. Now both sides see the same value by construction. Summed over the 7 gates and the 4 executors that do not canonicalize, this took canary reads from 80 to **28** with fail-closed gates and from 120 to **28** with fail-open gates. All 28 are the symlink: 1 per gate and executor. Benign calls were unaffected: 9 of 9 read in every cell, including the strict executor, because the forwarded object has no unknown keys.

**2. `deny_unknown_fields` + `canonicalize()` in the executor.** This is the last column of both matrices: **0 canary reads behind every gate, in both modes, even when the gate forwards the raw bytes.** `deny_unknown_fields` rejects `PATH`, `Path`, `file_path` and every other second name. The derive already rejects duplicates. `canonicalize()` resolves `..` and the symlink before the prefix check, so `workspace/link/canary.env` resolves to `secrets/canary.env` and is refused.

The cost: the strict executor rejected 3 of the 9 benign calls, the ones that carry an `"explanation"` key that the tool schema does not declare. That is the right trade for a file-reading tool. Declare every field the schema has (I declared `reason`) and let the model's retry handle the error.

### What it costs

![Bar chart of median nanoseconds per call over 5 runs of 1 million calls on an Apple M2 Pro with rustc 1.95.0 in release mode, for a payload with a 58-byte path and a 59-byte reason string: struct default 82 ns, struct with serde alias 81 ns, struct with deny_unknown_fields 110 ns, serde_json::Value with get path 219 ns, deny_unknown_fields plus re-serialising the path object 222 ns. A red note says canonicalize plus starts_with workspace costs 13.5 microseconds per call, off the chart.](/assets/img/posts/ai/tool-args-differential-cost.webp){: width="1500" height="640" }

Medians of 5 runs × 1,000,000 calls (runs within 3% of each other):

| Executor variant | `{"path"}` only | `{"path", "reason"}` |
| --- | --- | --- |
| struct (default) | 56 ns | 82 ns |
| struct + `#[serde(alias)]` | 56 ns | 81 ns |
| struct + `deny_unknown_fields` | 56 ns | 110 ns |
| `serde_json::Value` + `.get("path")` | 135 ns | 219 ns |
| strict parse + re-serialise `{"path"}` (canonical forwarding) | | 222 ns |
| `canonicalize()` × 2 + `starts_with` | 13.5 µs | |

`deny_unknown_fields` adds about 28 ns when there is a declared optional field. Parsing to `Value` costs 2.4 to 2.7× the typed struct. That is one more reason not to use it in an executor. `canonicalize()` is two `realpath` walks on APFS and costs about 13.5 µs. That is 100× even the `Value` parse, and it still has to run, because it is the only check here that closes the symlink row. For a tool that reads a file anyway, 13.5 µs does not matter.

## What I would do in a Rust tool server

1. **Parse the arguments once, strictly, in the executor:** a typed struct with `#[serde(deny_unknown_fields)]`. No `Value`, no aliases. If models keep sending `file_path`, rename the field in the tool schema so the model writes what you parse.
2. **Make the security check in the code that opens the file:** `canonicalize()` both sides, then `starts_with`. A gate in front is defence in depth. It is not the control.
3. **If a gate must stay in front, forward its canonical object, not the model's bytes,** and make it fail closed on any parse error, including duplicate keys. A gate that treats "I couldn't parse it" as "nothing to check" turned the strictest parser here into a 13-read bypass.
4. **Test the pair, not each side.** The bench is a corpus of argument strings and a matrix. Run your real gate and your real executor over it in CI. Neither side alone shows the bug.

## Limits of this test

- One tool (`read_file`), one policy and 79 strings I wrote by hand. A real attacker would fuzz. The families here are the known JSON parser differentials (duplicate keys, case folding, escapes, trailing data, type confusion), not an exhaustive list.
- The executors are mine. A tool server that decodes arguments with `serde_json::from_str` into a struct with `#[serde(flatten)]` or `untagged` enums can behave differently. I checked that flatten still rejects duplicate fields in serde 1.0.229, but I did not put it in the matrix.
- The NUL and lone-surrogate strings produced errors on every executor, so they read nothing here. In a tool server that passes paths to C code they could behave differently.
- No model in the loop. The question is what happens when a model *does* emit these arguments, and earlier posts measured how easily injected text steers what a model emits.

## Reproduce it

```bash
# Rust 1.95 (serde 1.0.229, serde_json 1.0.154; add CARGO_NET_OFFLINE=true with a warm cache),
# Go >= 1.27 (encoding/json/v2 without GOEXPERIMENT), Node 22, jq, python3. About 12 s on an M2 Pro.
python3 scripts/tool-args-differential/bench.py /tmp/tool-args-work
BROWSER_PATH=/path/to/chrome-headless-shell bash scripts/tool-args-differential/shots.sh /tmp/tool-args-work
python3 scripts/tool-args-differential/gen_images.py /tmp/tool-args-work
```

`bench.py` writes `scripts/data/tool-args-differential.json`, which holds every gate's view and every executor's view of each payload, the leak matrices and the timing runs. `cells.json` in the work directory has all 5,530 gate × mode × executor cells.

## Related posts

- [AI Security: Agent Tool Permissions vs Prompt Injection]({% post_url AI/2026-10-31-ai-security-agent-tool-permissions-prompt-injection %}): what to allow a tool to do in the first place.
- [AI Security: Sandboxing Agent Tool Calls]({% post_url AI/2026-10-30-ai-security-sandboxing-agent-tool-calls %}): the OS-level containment that catches what argument checks miss.
- [AI Security: Hidden Prompt Injection vs Agent Page Readers, Measured]({% post_url AI/2026-11-04-ai-security-hidden-prompt-injection-agent-page-readers-measured %}): how injected text reaches the model that writes these arguments.
- [Rust Error Handling: thiserror vs anyhow, Measured]({% post_url Languages/2026-11-06-rust-error-handling-thiserror-vs-anyhow-measured %}): the same measuring style, applied to the errors serde returns here.
- If you write tool schemas by hand, the [Function Call Schema Builder]({% post_url AI/2026-10-12-function-call-schema-builder-tool-definitions-without-hand-written-json %}) generates them, and a schema with `additionalProperties: false` is the schema-side twin of `deny_unknown_fields`.

## Where Pulse fits

Pulse, Lamplit Labs' multi-project self-improving automation product, is coming soon. It runs coding agents for long stretches without a person watching, and every one of their tool calls passes through a gate like the ones measured here. That is why we test the gate and the executor as a pair instead of trusting either one. The [Pulse introduction]({% post_url AI/2026-10-25-pulse-internal-rsi-tool %}) has more on what we are building.
