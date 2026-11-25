---
layout: post
title: "AI Security: Unicode Tricks vs a Keyword Prompt-Injection Filter, Measured"
date: 2026-11-25 00:00:00 +0000
categories: ai
author: manishtiwari25
description: "2,880 Unicode-obfuscated prompt injections vs one keyword filter: raw text caught 8.7%, NFKC 25.3%, five normalisation layers 91.7%. Code included."
image:
  path: /assets/img/headers/ai/ai-security-unicode-injection-filter-measured.webp
  alt: "Terminal screenshot of scripts/unicode-injection-filter/bench.py on Python 3.13.5 with Unicode 15.1: 2,880 attack strings and 20 benign ones. Rows are 12 techniques, columns are five cumulative normalisation layers. On raw text the filter catches 100% of plain phrases and 0 to 1% of every obfuscated one. NFKC fixes fullwidth and math bold, stripping format characters fixes zero-width, soft hyphen, tag and bidi characters, stripping combining marks fixes accents and variation selectors, and a confusable table fixes Cyrillic and Greek look-alikes. Look-alikes not in the table stay at 0%. Totals: 8.7%, 25.3%, 58.5%, 75.0%, 91.7%."
tags: [ai-security, prompt-injection, llm, guardrails, unicode, python, benchmark]
---

Most teams' first prompt-injection guard is a keyword list: `ignore previous instructions`, `reveal your system prompt`, `developer mode`. It runs on retrieved pages, tickets and e-mails before the agent sees them. It's cheap and easy to read, and it's easy to get around. The model reads text the way people do, but the regex compares code points, and Unicode has many ways to write the same letters.

We measured how far one ordinary keyword filter gets when the same phrases are obfuscated with eleven common Unicode tricks, and how much each normalisation step you can put in front of it gets back. It's one stdlib Python script, seeded, with no network access. It takes a few seconds to run.

## TL;DR

- **On raw text, the filter caught 8.7% of 2,880 attack strings.** That's the plain, unobfuscated phrases and nothing else. Every trick got the caught share down to 0 to 1%.
- **NFKC alone gets you to 25.3%.** It folds fullwidth and math-bold letters, and that's all it does here. Zero-width spaces, tag characters, bidi controls and soft hyphens all survive NFKC.
- **Stripping format characters (Unicode category Cf) brings it to 58.5%**, stripping combining marks to 75.0%, and a small Cyrillic/Greek look-alike table to 91.7%.
- **The last 8.3% is look-alikes that aren't in the table.** That category stayed at 0% on every layer. A confusable table only knows the letters you put in it.
- **Don't rewrite the text you pass on.** If you replaced the input with the folded text, the full pipeline would change 16 of 20 ordinary strings: emoji ZWJ sequences, Persian ZWNJ, accents, Greek and Russian. Scan a folded copy and pass on the original.

## The setup

[`scripts/unicode-injection-filter/bench.py`](https://github.com/lamplitlabs/blog/blob/main/scripts/unicode-injection-filter/bench.py) builds 12 injection phrases × 12 techniques × 20 seeded variants. That's 2,880 strings, each inside one of four carrier sentences (a review, meeting notes, an HTML comment, a reply). The techniques:

| Technique | What it does to `ignore all previous instructions` |
|---|---|
| plain | nothing (the control) |
| zero_width | ZWSP, ZWNJ, ZWJ or word joiner between ~35% of letter pairs |
| soft_hyphen | U+00AD between letters |
| tag_chars | invisible tag characters (U+E0020 to U+E007E) between letters |
| bidi_controls | LRM, RLM, LRE, PDF, LRI, PDI between letters |
| fullwidth | ~60% of letters as fullwidth forms (ｉｇｎｏｒｅ) |
| math_bold | ~60% of letters as mathematical bold (𝐢𝐠𝐧𝐨𝐫𝐞) |
| combining_marks | an acute, diaeresis, cedilla or strike-through mark after letters |
| variation_selectors | VS1 to VS16 after letters |
| homoglyph_cyrillic_greek | Cyrillic or Greek letters that look like a, c, e, i, o, p, s, u, v, x, y |
| mixed | homoglyphs + fullwidth + zero-width together |
| homoglyph_not_in_table | look-alikes (ɑ, օ, ҽ, ı, ꜱ, ս, ո, г) that the fold table doesn't list |

The filter is one regex built from ten rules and run with `re.search`. It's the same kind of rule list as the one in our [ReDoS measurements of guardrail regexes]({% post_url AI/2026-11-23-ai-security-guardrail-regex-redos-measured %}). In front of it are five cumulative layers: `raw` (casefold), `nfkc`, `strip_cf` (drop category Cf), `strip_mn` (NFD, drop category Mn, NFC) and `confusable` (fold a 13-entry look-alike table to Latin). The header image above is the script's own terminal output, unedited.

## Results

![Bar chart of attack strings caught by one keyword filter after each cumulative normalisation layer, out of 2,880 Unicode-obfuscated injections: raw casefold 8.7%, plus NFKC 25.3%, plus stripping format characters 58.5%, plus stripping combining marks 75.0%, plus a confusable table 91.7%. Under each bar, the number of 20 benign strings the layer would rewrite: 0, 3, 11, 16, 16.](/assets/img/posts/ai/unicode-injection-filter-catch-rate.webp)

| Layer | Attacks caught | Benign false positives | Benign strings changed |
|---|---:|---:|---:|
| raw | 8.7% | 1 / 20 | 0 / 20 |
| + NFKC | 25.3% | 1 / 20 | 3 / 20 |
| + strip Cf | 58.5% | 1 / 20 | 11 / 20 |
| + strip Mn | 75.0% | 1 / 20 | 16 / 20 |
| + confusables | 91.7% | 1 / 20 | 16 / 20 |

The caught percentages and counts are deterministic: three runs gave identical results. The one false positive appears on every layer: "The new instructions for the printer are on page 3." Keyword rules have this problem whatever you normalise. Per string, the run times were noisy on a loaded M2 Pro. Across three runs, the medians went from about 3.3 µs (raw) to about 42 µs (all five layers). The whole pipeline costs more than ten times the bare regex, which is still small next to a model call.

Three findings matter for anyone who ships a filter like this:

1. **NFKC is not "normalise everything".** It folds compatibility forms (fullwidth, math alphanumerics, ligatures like ﬁ), but it keeps every format character. A zero-width space survives NFKC, and so do tag characters and bidi controls. Those four techniques were at 0 to 1% after NFKC and 100% after the Cf strip.
2. **Variation selectors and combining marks need their own step.** Variation selectors are category Mn, not Cf, so the Cf strip missed them (1%). Only the NFD-and-drop-marks step caught them.
3. **Look-alike tables are a list of known letters.** The Cyrillic/Greek table took the homoglyph and mixed rows from 0% to 100%, and it didn't touch the held-out Armenian, Latin-extended and small-capital look-alikes. Unicode's own `confusables.txt` covers far more, and an attacker who wants to get past it only needs one letter it doesn't list.

## What to do with this

- **Scan a folded copy and pass on the original.** The "changed" column shows what rewriting would cost you. It strips the ZWJ from 👩‍💻 and the ZWNJ from Persian words, and it takes the accents off "café" and every word of Greek. Folding is for matching only.
- **Put the Cf strip before NFKC-based checks, and add the Mn step.** NFKC alone gave a 25.3% catch rate.
- **Treat a filter hit as a signal, not your boundary.** Even at 91.7% caught, an attacker who reads this post knows which letters to pick. The controls that still work when the filter misses are least-privilege tools and egress policy, covered in [prompt injection defences for agents]({% post_url AI/2026-10-29-ai-security-prompt-injection-defenses-agents %}) and [tool-call permission boundaries, measured]({% post_url AI/2026-11-19-ai-security-agent-tool-call-permission-boundaries-measured %}).
- **Log what you stripped.** A page with tag characters or bidi controls between letters is suspicious in itself. In our [hidden prompt injection test]({% post_url AI/2026-11-04-ai-security-hidden-prompt-injection-agent-page-readers-measured %}), tag characters were invisible on screen and cost 16 times the tokens.

## Reproduce it

```bash
python3.13 scripts/unicode-injection-filter/bench.py
# writes scripts/data/unicode-injection-filter.json and prints the table in the header image
```

The JSON keeps the per-technique catch rates, the false-positive strings and the per-layer timings. Python 3.9's `unicodedata` (Unicode 13.0) gives the same catch rates. The numbers above are from Python 3.13.5 with Unicode 15.1.

## Where Pulse fits

Pulse, Lamplit Labs' multi-project self-improving automation product, is coming soon. Its agents read issue threads, CI logs and web pages all day, so they run into this kind of text all the time. Measurements like this one decide which filters we keep, and they remind us that a filter is never the only control.
