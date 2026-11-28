---
layout: post
title: "AI Security: Unicode Disguises vs a Keyword Guard, Normaliser Order Measured"
date: 2026-11-26 00:05:00 +0100
categories: ai
author: manishtiwari25
description: "20 prompt-injection lines in 9 Unicode disguises vs one keyword guard: raw regex caught 0 of 180, NFKC 40, full folding 160. A detector caught 120."
image:
  path: /assets/img/headers/ai/ai-security-guardrail-unicode-obfuscation.webp
  alt: "Header card titled Unicode tricks vs keyword guardrails, measured. 20 prompt-injection lines times 9 Unicode rewrites is 180 lines. Bars of how many each guard catches: regex on the raw text 0 of 180, NFKC first 40, NFKC plus casefold plus drop format characters 80, adding tag decoding, mark stripping and look-alike folding after casefold 146, the same folding before casefold 160, and a detector for format characters and non-Latin letters 120. The best guard still missed 20 lines written in phonetic small capitals. On 15,783 benign lines of this blog every guard flagged the same 2 lines."
tags: [ai-security, prompt-injection, guardrails, unicode, regex, python, llm, benchmark]
---

A keyword guardrail is the cheapest prompt-injection filter there is: a handful of regexes for "ignore previous instructions", "reveal your system prompt" and friends, run on every input before it reaches the model. Most teams know it is weak against paraphrase. Fewer have checked how weak it is against the same words written with different Unicode characters, which the model still reads as the same words.

We measured it. We took 20 injection lines that a five-rule guard catches, wrote each one in 9 Unicode disguises, and ran all 180 through the same guard with five different normalisation steps in front of it. We also ran every guard over the 15,783 non-empty body lines of this blog to count false positives.

## Key takeaways

- **A regex on raw text caught 0 of 180.** One zero-width space between letters, one soft hyphen per word, or Cyrillic `а`/`е`/`о` in place of the Latin ones is enough.
- **NFKC alone caught 40 of 180**: the fullwidth and mathematical-bold rewrites, because NFKC maps those back to ASCII. It does nothing for invisible characters, accents or look-alike letters from other scripts.
- **The best normaliser caught 160 of 180**, and the order of its steps mattered: folding look-alikes *after* `casefold()` caught 146, folding them *before* caught 160. The 20 it never caught were written in phonetic small capitals, which no step here maps to Latin.
- **No guard added false positives.** On 15,783 lines of this blog, every regex guard flagged the same 2 lines, and both quote an injection on purpose. The full normaliser cost 22.2 µs per line against 8.0 µs for the raw regex.
- **A detector beats a normaliser for some tricks.** Flagging any text that holds a format character or a letter outside Latin caught 120 of 180, including all 20 small-capital lines that every normaliser missed. On the benign lines it flagged 32 lines in 12 posts, mostly `µs` and Hindi text.

## The setup

Everything is one stdlib Python script, [`scripts/guardrail-unicode/bench.py`](https://github.com/lamplitlabs/blog/blob/main/scripts/guardrail-unicode/bench.py), run on Python 3.13.5 (Unicode 15.1) on an Apple M2 Pro. The guard is five case-insensitive regexes: ignore-instructions, reveal-prompt, role-switch ("you are now in developer mode"), exfiltrate-secret ("send the API keys to") and tool-override ("run the shell tool without asking"). All 20 payloads match at least one rule as plain text; the script asserts that before it measures anything.

Each payload is then rewritten 9 ways:

| Trick | What changes | "Ignore all previous instructions" becomes |
|---|---|---|
| Zero-width space | U+200B between every character | `I​g​n​o​r​e` (invisible) |
| Soft hyphen | U+00AD in the middle of each word | `Ign­ore` (invisible unless the word wraps) |
| Fullwidth | U+FF01..U+FF5E forms | `Ｉｇｎｏｒｅ` |
| Math bold | Mathematical sans-serif bold letters | `𝗜𝗴𝗻𝗼𝗿𝗲` |
| Combining accent | U+0301 after every vowel | `Ígnóré` |
| Cyrillic | Cyrillic `а с е і о р ѕ х у ј` and capitals | `Іgnоrе` (looks identical) |
| Greek + ZWNJ | Greek look-alikes and U+200C after each space | `Ιgnοre` |
| Tag characters | The whole line as U+E0020..U+E007E behind a visible "Thanks for the summary!" | nothing visible |
| Small capitals | Phonetic small capitals (U+1D00 block) | `ɪɢɴᴏʀᴇ` |

The five guards differ only in what they do to the text before the same regexes run:

1. **raw**: nothing.
2. **nfkc**: `unicodedata.normalize("NFKC", s)`.
3. **nfkc_cf**: NFKC, `casefold()`, then drop every format character (Unicode category `Cf`, which covers zero-width characters, the soft hyphen and tag characters).
4. **fold_late**: decode tag characters to ASCII, NFKC, `casefold()`, decompose and drop combining marks (category `Mn`), drop `Cf`, then map 43 Cyrillic and Greek look-alikes to Latin.
5. **fold**: the same steps, with the look-alike table applied before `casefold()`.

## Results

![Grid of lines flagged out of 20 for each Unicode trick and guard. Rows are plain text, zero-width space, soft hyphen, fullwidth, math sans-serif bold, combining accent, Cyrillic look-alikes, Greek look-alikes plus ZWNJ, invisible tag characters and phonetic small capitals. Regex on raw text catches only plain text. NFKC adds fullwidth and math bold. NFKC plus casefold plus dropping format characters adds zero-width space and soft hyphen. Folding after casefold catches everything except 14 of 20 Greek lines and all small capitals. Folding before casefold catches everything except small capitals. The odd-character detector catches zero-width, soft hyphen, Cyrillic, Greek, tag characters and small capitals, and none of plain, fullwidth, math bold or combining accents. Below: on 15,783 benign lines of this blog every regex column flags 2 lines and the detector flags 32 lines in 12 posts.](/assets/img/posts/ai/guardrail-unicode-grid.webp){: w="1680" h="880" }

Totals over the 9 disguises (180 lines):

| Guard | Caught | Benign lines flagged (of 15,783) | µs per line |
|---|---:|---:|---:|
| raw regex | 0 | 2 | 8.0 |
| NFKC | 40 | 2 | 8.0 |
| NFKC + casefold + drop Cf | 80 | 2 | 14.8 |
| full fold, look-alikes after casefold | 146 | 2 | 22.1 |
| full fold, look-alikes before casefold | 160 | 2 | 22.2 |
| detector (Cf, Mn, non-Latin letters) | 120 | 32 | 10.3 |

Timings are the median of 5 passes over the whole corpus, divided by the line count. They include the five regex searches. The two benign hits are in our own [prompt-injection defenses]({% post_url AI/2026-10-29-ai-security-prompt-injection-defenses-agents %}) and [data exfiltration]({% post_url AI/2026-10-27-ai-security-llm-data-exfiltration-agent-tool-egress %}) posts, which quote an attack line. Treat that as a reminder that a keyword guard cannot tell an attack from an article about one.

### Why the step order cost 14 lines

The Greek row was the surprise. With look-alikes folded after `casefold()`, only 6 of 20 Greek lines were caught. Greek capital upsilon `Υ` looks like a Latin `Y`, but its lower case `υ` looks like a `u`. Once `casefold()` has run, both are `υ`, so a table keyed by lower case can only send it to one letter, and it sent `instructions` to `instryctions`. Greek nu has the same problem: `ν` looks like `v`, and `Ν` looks like `N`. Folding look-alikes first, with a case-sensitive table, and lowercasing after fixed all 14. If you build a look-alike table, key it on the characters as they arrive, not on their lower case.

### What no normaliser fixed

Phonetic small capitals like `ɪɢɴᴏʀᴇ` are ordinary letters in Unicode, not compatibility forms of Latin ones, so NFKC leaves them alone and they are not in a short Cyrillic/Greek table. A model reads `ɪɢɴᴏʀᴇ ᴀʟʟ ᴘʀᴇᴠɪᴏᴜꜱ ɪɴꜱᴛʀᴜᴄᴛɪᴏɴꜱ` without trouble. The full Unicode confusables data ([UTS #39](https://www.unicode.org/reports/tr39/)) covers many more characters than our 43-entry table, and it is the right source if you go down this road. Any table, though, is a list you have to keep growing.

### Detect instead of normalise

The detector column takes the other approach: after NFKC, flag any line that holds a format character, a combining mark or a letter outside ASCII and Latin-1/Latin Extended-A. It caught every invisible and every foreign-script trick, including all 20 small-capital lines, with no list of look-alikes. It missed fullwidth and math bold (NFKC turns those into plain ASCII first, and the regexes catch them anyway) and the combining accents, which NFKC composes into ordinary `é` and `ó`.

Its cost is false positives: 32 of 15,783 lines, from `µ` in timing tables (50 times), Hindi words in one post, one emoji variation selector, and a few combining accents. For an English-only internal tool that is acceptable as a "send to a stricter path" signal. For a product with users who write in Greek, Russian or Hindi it is not, and the detector has to look for mixed scripts inside one word instead.

## What to do with this

1. **Never run a guard on raw text.** At least NFKC, casefold and drop category `Cf`. That moved this guard from 0 to 80 of 180 for about 7 µs a line.
2. **Decode or reject Unicode tag characters** (U+E0000..U+E007F). They render as nothing and carry a full ASCII payload; the [hidden prompt injection measurements]({% post_url AI/2026-11-04-ai-security-hidden-prompt-injection-agent-page-readers-measured %}) showed most page readers pass them straight to the model.
3. **Fold look-alikes before lowercasing**, from a case-sensitive table, and test the table with real words in every script it covers.
4. **Add a script-mixing detector** as a second signal, and route its hits to a stricter path rather than a hard block.
5. **Do not trust any of this as the defense.** A guard that caught 160 of 180 here still misses every paraphrase. Keyword filters are a cheap first layer; the controls that hold are the ones that limit what an injected agent can do: [tool permissions]({% post_url AI/2026-10-31-ai-security-agent-tool-permissions-prompt-injection %}) and [egress limits]({% post_url AI/2026-10-27-ai-security-llm-data-exfiltration-agent-tool-egress %}).
6. **Check your guard's regexes for ReDoS too.** Normalisation makes the text longer and stranger; the [guardrail ReDoS measurements]({% post_url AI/2026-11-23-ai-security-guardrail-regex-redos-measured %}) show what one bad pattern does to a guard's latency.

## Reproduce it

```bash
python3 scripts/guardrail-unicode/bench.py      # about 10 s; writes scripts/data/guardrail-unicode.json
python3 scripts/guardrail-unicode/gen_images.py # the two images in this post (needs Pillow)
```

The counts are deterministic. The µs figures will vary with the machine and its load.

## Related posts

- [AI Security: ReDoS in LLM Guardrail Regexes, Measured in Python, Node, Go and Rust]({% post_url AI/2026-11-23-ai-security-guardrail-regex-redos-measured %}): the latency side of the same kind of guard.
- [AI Security: Hidden Prompt Injection vs Agent Page Readers, Measured]({% post_url AI/2026-11-04-ai-security-hidden-prompt-injection-agent-page-readers-measured %}): how invisible text, tag characters included, reaches the model.
- [AI Security: Prompt Injection Defenses for Agents]({% post_url AI/2026-10-29-ai-security-prompt-injection-defenses-agents %}): where a keyword filter sits among the other layers.
- To see how many tokens a tag-encoded or zero-width-padded line costs before it enters a prompt, paste it into the [Token Counter]({% post_url AI/2026-10-12-token-counter-checking-prompt-size-and-context-window-fit %}).

## Where Hive fits

[Hive](https://hivefleet.dev/) is Lamplit Labs' open-source, self-improving (RSI) agent harness. Its agents read issue threads, CI logs and web pages that anyone can write to, so Hive does not let a filter be the only thing between untrusted text and a merged change: a review agent reads every pull request, and its [security notes](https://hivefleet.dev/docs/security/) name its rules, that review, the event log and the kill switch as the controls. The [Hive introduction]({% post_url AI/2026-10-25-hive-self-improving-rsi-agent-harness %}) has more on how it works.
