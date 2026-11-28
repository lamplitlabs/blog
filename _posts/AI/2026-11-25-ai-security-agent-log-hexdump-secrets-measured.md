---
layout: post
title: "AI Security: Secrets in Agent-Log Hexdumps, Measured - xxd, hexdump and od Against gitleaks and Redaction"
date: 2026-11-25 01:00:00 +0000
categories: ai
author: manishtiwari25
description: "405 fake secrets dumped by 9 real xxd, hexdump and od commands into agent logs: gitleaks caught 0, redaction 9. Parsing the dump back to bytes first caught 405."
image:
  path: /assets/img/headers/ai/ai-security-agent-log-hexdump-secrets-measured.webp
  alt: "Header card titled Secrets in agent-log hexdumps, measured: 405 fake secrets, one .env file each, dumped by 9 real commands (xxd, hexdump, od) into agent logs. Bar chart of how many each defence caught: gitleaks on the stored log 0% (0/405), gitleaks with a tuned config on the decoded view 4% (16/405), encoding-aware redaction 2% (9/405), undump then gitleaks 88% (358/405), undump then known-value redaction 100% (405/405). Footer: gitleaks 8.30.1, Darwin arm64."
tags: [ai-security, agents, secrets, llm, observability, benchmark, gitleaks]
---

In the [secrets in agent logs post]({% post_url AI/2026-11-02-ai-security-secrets-in-agent-logs-measured %}) one leak shape beat every defence we measured: `xxd .env`. All 24 hexdumps got through gitleaks and both redactors, and through the two combined. We left it as a one-paragraph warning. This post measures it properly. We used nine real dump commands that agents run when a config file "looks wrong", and tested one fix: parse the dump back into bytes before the redactor and the scanner see it.

**The short version:**

- **Nine dump formats, 405 fake secrets. gitleaks with default rules flagged 0 of them in the stored log.** The same secrets printed by `cat` were flagged 40 of 45 times, and printed by `base64` also 40 of 45 times. gitleaks decodes base64, but not hexdumps.
- **Encoding-aware known-value redaction removed 9 of 405 (2%).** It already looks for the hex encoding of every secret it knows. It only matched in `xxd -p`, and only for secrets short enough to fit on one 60-character row.
- **Parsing the dump back to bytes ("undump") and then redacting caught all 405.** Undump then the tuned gitleaks scan caught 358 (88%). It missed the same thing as before: passwords with no recognisable prefix.
- **The normaliser is cheap and quiet.** It ran on 5,000 ordinary agent tool outputs and matched none of them. On 360 dumps of random binary files it rebuilt 356 byte for byte, and it parsed the whole 393 KB corpus in 35 ms.

## The setup

Everything comes from `scripts/agent-log-hexdumps/bench.py`. It reuses the secret generator, redactor, oracle and gitleaks wrapper from the earlier bench, so the numbers are comparable. It uses a fixed seed (20261125), gitleaks 8.30.1, and the stock `xxd`, `hexdump` and `od` on macOS (Darwin arm64).

For each event the script writes a small `.env` file holding one fake secret. There are 9 secret kinds: AWS key ID and secret, GitHub PAT, Slack bot token, Stripe live key, OpenAI and Anthropic keys, a JWT, and a database password, 5 of each. Then it **runs the real command** on the file and stores the output as a `tool_result` record in agent-log JSONL. There are 11 commands with 45 events each: `cat` and `base64` as controls, plus nine dump formats (`xxd`, `xxd -p`, `xxd -i`, `xxd -b`, `hexdump`, `hexdump -C`, `od`, `od -c`, `od -A x -t x1`).

A secret counts as caught when one of two things is true. Either the redactor removed it, so an attacker reading the stored log cannot get it back, or gitleaks reported a finding in that event's record. The "attacker" is an oracle that tries the raw string, URL decoding, base64, hex, and the same dump parser. It recovered all 495 planted secrets from the unredacted logs, and `xxd -r` / `xxd -r -p` rebuilt all 90 `xxd` and `xxd -p` files byte for byte. A hexdump is reversible by design.

## What one hexdump looks like to the scanner

![Terminal capture of one agent tool result: xxd .env prints eight rows of hex pairs with an ASCII column. The fake GitHub token starts at row 0x30 with GITHUB_TOKEN=g, continues as hp_epx0 on row 0x40, and the rest of it, masked with asterisks here, wraps over the next two rows. gitleaks dir session.jsonl --redact then reports scanned about 608 bytes, no leaks found. After the dump is parsed back to bytes, gitleaks with the tuned config reports RuleID github-pat on line 3 of session-undumped.txt, leaks found: 1. Last line: the stored record after undump and known-value redaction is [REDACTED: 128-byte dump held a known secret].](/assets/img/posts/ai/agent-log-hexdumps-xxd-gitleaks-terminal.webp){: width="1400" height="833" }
_The token is in the stored log twice: as 2-byte hex groups and as 16-character slices of the ASCII column. Neither form matches a rule. (Token masked after 8 characters in this image only.)_

The scanner has nothing to match. The hex column splits the value into 4-digit groups separated by spaces, and the ASCII column cuts it into 16-character slices with row offsets in between. A GitHub PAT is `ghp_` plus 36 characters, and no single row holds it. The known-value redactor does look for the secret's hex encoding, but in the stored text that encoding is broken by spaces and line breaks.

## Results by command

![Matrix of fake secrets caught, rows are the command that printed the .env file and columns are the defences, 45 events per cell. cat .env: gitleaks stored 40/45, gitleaks tuned decoded view 40/45, encoding-aware redaction 45/45, undump then gitleaks 40/45, undump then redaction 45/45. base64 -i .env: the same 40, 40, 45, 40, 45. Below the separator line, the nine dump formats xxd, xxd -p, xxd -i, xxd -b, hexdump, hexdump -C, od, od -c and od -A x -t x1 all score 0/45 for gitleaks on the stored log and 0/45 for redaction, except xxd -p with 16/45 for the tuned decoded-view scan and 9/45 for redaction. Undump then gitleaks scores 39 or 40 of 45 on every dump format, and undump then redaction scores 45/45 on every row.](/assets/img/posts/ai/agent-log-hexdumps-defence-matrix.webp){: width="1200" height="840" }
_Every cell comes from `scripts/data/agent-log-hexdumps.json`. The two rows above the line are controls._

Totals over the 405 dump events:

| Defence | Caught | Share |
| --- | ---: | ---: |
| gitleaks 8.30.1, default rules, stored JSONL | 0 | 0% |
| gitleaks, tuned config, decoded view | 16 | 4% |
| Encoding-aware known-value redaction | 9 | 2% |
| Undump, then gitleaks (tuned) | 358 | 88% |
| Undump, then known-value redaction | 405 | 100% |

Two cells are worth a closer look:

- **`xxd -p` is the only format that half works.** It prints plain hex with no spaces, 60 digits per row. On the decoded view, gitleaks' own hex decoder caught 16 of 45 (tagged `decoded:hex`), but only when the key name and value landed on the same row. Redaction caught 9: the 5 database passwords and 4 of the 5 AWS key IDs, the only secrets short enough (19-20 bytes, so 38-40 hex digits) to fit inside one row. Longer secrets wrap, and the newline breaks the match.
- **Undump plus gitleaks misses 47, and 45 of them are database passwords.** This is the same gap as in the first post: no default rule matches `DB_PASSWORD=` followed by 19 random characters. Once the dump is back in bytes, the scanner is only as good as its rules. The redactor knows the value, so it catches them.

## The fix: undump before you redact or scan

`undump()` in the bench script is about 240 lines of standard-library Python. It recognises the nine layouts above. A layout only counts if every non-empty line matches it, so a single hex digest or a `git log` line does not trigger it. The function rebuilds the bytes and expands the `*` lines that `hexdump` and `od` print for repeated rows. When the bytes contain a secret the runtime knows, the log writer stores a placeholder for the whole tool result instead of the dump. A gitleaks pass over the decoded bytes covers secrets the runtime does not know.

How it behaved on things that are not hexdumps:

- **5,000 ordinary tool outputs** from the earlier bench's generator: `git log`, `pytest`, lockfile reads with base64 integrity hashes, `docker pull` digests and HTTP JSON. It fired on none of them.
- **360 dumps of random binary files** (256-2,048 bytes, 40 per format): it rebuilt 356 exactly. The 4 misses are `od -c` rows where a multibyte character starts in the last column and macOS `od` prints its trailing byte oddly. gitleaks reported 0 findings on the decoded binary, and the redactor dropped none of the benign dumps.
- **Cost:** 35 ms for 393 KB of dump output, about 11 MB/s in pure Python. That is noise next to the 63 ms gitleaks needed to scan the same records.

One caveat. This only works if the dump is the whole tool result. If an agent pipes `xxd` through `grep` or `head`, you get a fragment of a dump, and it can still hold enough rows to rebuild a short key. The cheaper policy is the one from the first post: an agent that needs to inspect a config file should not hold its secrets in the first place.

## A starting sequence

1. **Don't let the runtime hand agents real secrets in files they can read.** Every event here started with a `.env` holding a live-looking key. Inject short-lived credentials at the tool boundary instead, as described in the [tool-call permission boundaries post]({% post_url AI/2026-11-19-ai-security-agent-tool-call-permission-boundaries-measured %}).
2. **Normalise tool output before redaction.** Undump hexdumps the same way you would decode base64 or percent-encoding. A redactor that sees the bytes catches everything it knows about.
3. **Scan the normalised view, not only the stored log.** gitleaks over the stored JSONL caught 0 of 405 here. Over the undumped bytes it caught 358.
4. **Add rules for the secrets your scanner cannot name.** Passwords and other prefix-less values need a known-value redactor or a custom rule. The tuned config in `scripts/data/agent-logs-gitleaks.toml` is a start.

## Reproduce it

```bash
# gitleaks 8.30.1 on PATH; xxd, hexdump and od from the OS. About 5 seconds on an M2 Pro.
python3 scripts/agent-log-hexdumps/bench.py --work /tmp/hexdumps      # -> scripts/data/agent-log-hexdumps.json
python3 scripts/agent-log-hexdumps/gen_images.py --work /tmp/hexdumps # the images in this post
```

The JSON keeps the per-command counts for every defence, the gitleaks rules that fired, and the timings. It holds no secret values.

## Where Hive fits

[Hive](https://hivefleet.dev/) is Lamplit Labs' open-source, self-improving (RSI) agent harness. Its agents debug real projects without a person watching, and `xxd` on a config file is exactly the kind of command they run. Hive keeps each run's transcript on your own machine, for 14 days by default, so what this post measured is worth checking in a Hive transcript too. The [Hive introduction]({% post_url AI/2026-10-25-hive-self-improving-rsi-agent-harness %}) has more on how it works.

## Related

- [AI Security: Secrets in Agent Logs, Measured]({% post_url AI/2026-11-02-ai-security-secrets-in-agent-logs-measured %})
- [AI Security: ReDoS in LLM Guardrail Regexes, Measured]({% post_url AI/2026-11-23-ai-security-guardrail-regex-redos-measured %})
- [AI Security: Tool-Call Permission Boundaries for Coding Agents, Measured]({% post_url AI/2026-11-19-ai-security-agent-tool-call-permission-boundaries-measured %})
