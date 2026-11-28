#!/usr/bin/env python3
"""Build the webp images for the "shared prompt cache leaks across tenants, measured" post.

Usage:
  python3 scripts/prompt-cache-timing/gen_images.py

Reads scripts/data/prompt-cache-timing-leaks.json (written by summarise.py). Every
number and every terminal line in the images comes from that file.

Outputs:
  assets/img/headers/ai/ai-security-prompt-cache-tenant-leaks-measured.webp  (1600x840, 40:21)
  assets/img/posts/ai/prompt-cache-extract-transcript.webp
  assets/img/posts/ai/prompt-cache-hit-miss-latency.webp
  assets/img/posts/ai/prompt-cache-mitigations.webp
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "scripts", "data", "prompt-cache-timing-leaks.json")
OUT_HEAD = os.path.join(ROOT, "assets", "img", "headers", "ai")
OUT_POSTS = os.path.join(ROOT, "assets", "img", "posts", "ai")
F_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
F_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
F_MONO = "/System/Library/Fonts/Menlo.ttc"

BG = (13, 17, 23)
PANEL = (22, 27, 34)
BORDER = (48, 54, 61)
FG = (230, 237, 243)
MUTED = (139, 148, 158)
RED = (248, 81, 73)
ORANGE = (240, 136, 62)
YELLOW = (210, 153, 34)
GREEN = (63, 185, 80)
BLUE = (88, 166, 255)
GREY = (110, 118, 129)


def font(path, size):
    return ImageFont.truetype(path, size)


def save(img, path, quality=88):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    print("wrote", os.path.relpath(path, ROOT), img.size, os.path.getsize(path), "bytes")


def hbars(dr, x, y, w, rows, vmax, bar_h=46, gap=22, label_w=330, fmt="{:.0f}%", size=26, reserve=260):
    """rows: (label, value, colour, note)."""
    f = font(F_REG, size)
    fb = font(F_BOLD, size)
    for label, value, colour, note in rows:
        dr.text((x, y + bar_h / 2), label, font=f, fill=FG, anchor="lm")
        bx = x + label_w
        full = w - label_w - reserve
        bw = full * value / vmax
        dr.rectangle([bx, y, bx + full, y + bar_h], fill=PANEL)
        dr.rectangle([bx, y, bx + max(bw, 3), y + bar_h], fill=colour)
        dr.text((bx + max(bw, 3) + 14, y + bar_h / 2), fmt.format(value), font=fb, fill=FG, anchor="lm")
        if note:
            dr.text((bx + max(bw, 3) + 14 + dr.textlength(fmt.format(value), font=fb) + 14, y + bar_h / 2),
                    note, font=font(F_REG, size - 6), fill=MUTED, anchor="lm")
        y += bar_h + gap
    return y


def header(d):
    W, H = 1600, 840
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    ex = d["extract_summary"]
    m = d["member"]
    dr.text((80, 60), "Your shared prompt cache talks", font=font(F_BOLD, 60), fill=FG)
    dr.text((80, 140), "One llama-server, two tenants. The attacker sends guesses with max_tokens=1.",
            font=font(F_REG, 30), fill=MUTED)
    dr.text((80, 230), "%d of %d" % (ex["field_exact"], ex["secrets"]), font=font(F_BOLD, 88), fill=RED)
    dr.text((80, 340), "6-digit approval codes read out of another", font=font(F_REG, 30), fill=FG)
    dr.text((80, 378), "tenant's system prompt via cached_tokens", font=font(F_REG, 30), fill=FG)
    dr.text((80, 416), "(median %d probes each)" % ex["field_probes_median"], font=font(F_REG, 26), fill=MUTED)
    big = m["2048"]
    dr.text((840, 230), "%.0f%%" % big["pairwise_acc_pct"], font=font(F_BOLD, 88), fill=RED)
    dr.text((840, 340), "\"did they send this 2k-token document?\"", font=font(F_REG, 30), fill=FG)
    dr.text((840, 378), "right from wall time alone: %.0f ms vs %.0f ms" % (big["hit_ms_p50"], big["miss_ms_p50"]),
            font=font(F_REG, 30), fill=FG)
    dr.text((840, 416), "(%d trials, median latency hit vs miss)" % big["n"], font=font(F_REG, 26), fill=MUTED)
    dr.line([80, 500, W - 80, 500], fill=BORDER, width=2)
    mi = d["mitigate"]
    hd = d["hardened"]
    rows = [
        ("Strip cache fields at the gateway", mi["strip"]["pairwise_acc_pct"], RED),
        ("cache_prompt: false per request", mi["cache-off"]["pairwise_acc_pct"], RED),
        ("Per-tenant cache salt", mi["salt"]["pairwise_acc_pct"], GREEN),
    ]
    dr.text((80, 530), "Membership guessed right at 2,048 tokens (50% = coin flip):", font=font(F_REG, 28), fill=MUTED)
    hbars(dr, 80, 584, W - 160, [(a, b, c, "") for a, b, c in rows], 100.0, bar_h=44, gap=18, label_w=520,
          size=28, reserve=140)
    dr.text((80, 780), "SmolLM2-135M on llama.cpp build 12359, Apple M2 Pro. Code and raw data in the repo.",
            font=font(F_REG, 22), fill=MUTED)
    save(img, os.path.join(OUT_HEAD, "ai-security-prompt-cache-tenant-leaks-measured.webp"), quality=90)


def transcript(d):
    e = next(x for x in d["extract"] if x["field_exact"])
    rows = e["field_log_first_digit"]
    head = d["template"].split("{code}")[0].format(org=e["org"])
    lines = ["$ probe --tenant attacker --max-tokens 1   # victim %s keeps calling in between" % e["org"],
             "system prompt guess: \"%s\" + <digit> + \" ##\"" % head[-58:],
             ""]
    for r in rows:
        mark = "   <- longest cached prefix" if r["digit"] == e["code"][0] and r.get("round", 0) == max(
            x.get("round", 0) for x in rows) else ""
        lines.append("round %d  digit %s   prompt_tokens %3d   cached_tokens %3d   %6.1f ms%s" % (
            r.get("round", 0), r["digit"], r["prompt_tokens"], r["cached_tokens"], r["ms"], mark))
    lines.append("")
    lines.append("# digit 1 = %s. Repeat for the next 5 digits with the known prefix extended." % e["code"][0])
    lines.append("# recovered %s   true code %s   probes %d" % (e["field_guess"], e["code"], e["field_probes"]))
    size = 20
    mono = font(F_MONO, size)
    line_h = int(size * 1.6)
    W = 1600
    H = 120 + line_h * len(lines) + 40
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle([20, 20, W - 20, H - 20], radius=12, fill=PANEL, outline=BORDER, width=2)
    for i, c in enumerate((RED, YELLOW, GREEN)):
        dr.ellipse([48 + i * 30, 44, 64 + i * 30, 60], fill=c)
    dr.text((160, 52), "bench.py extract: what the attacker sees per guess (real replies, first digit)",
            font=font(F_BOLD, 22), fill=MUTED, anchor="lm")
    y = 96
    for ln in lines:
        colour = FG
        if "<-" in ln:
            colour = RED
        elif ln.startswith("# recovered"):
            colour = RED
        elif ln.startswith("#") or ln.startswith("$"):
            colour = MUTED
        dr.text((50, y), ln[:124], font=mono, fill=colour)
        y += line_h
    save(img, os.path.join(OUT_POSTS, "prompt-cache-extract-transcript.webp"))


def latency(d):
    W, H = 1600, 900
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    dr.text((60, 40), "Attacker's wall time: a document the victim sent vs one nobody sent", font=font(F_BOLD, 34),
            fill=FG)
    dr.text((60, 92), "Each dot is one probe (max_tokens=1). Same length, same server, order randomised per trial.",
            font=font(F_REG, 24), fill=MUTED)
    lens = sorted(d["member"], key=int)
    x0, x1 = 300, W - 300
    ymax = max(max(d["member"][n]["misses_ms"]) for n in lens)
    ymax = min(ymax, 700)
    import math
    lo, hi = math.log10(5), math.log10(ymax * 1.1)

    def xp(v):
        v = max(5, min(v, ymax * 1.1))
        return x0 + (x1 - x0) * (math.log10(v) - lo) / (hi - lo)
    for t in (10, 20, 50, 100, 200, 500):
        if t <= ymax * 1.1:
            dr.line([xp(t), 150, xp(t), H - 120], fill=BORDER, width=1)
            dr.text((xp(t), H - 110), "%d ms" % t, font=font(F_REG, 20), fill=MUTED, anchor="mt")
    band = (H - 290) / len(lens)
    for i, n in enumerate(lens):
        s = d["member"][n]
        yc = 170 + band * i + band / 2
        dr.text((60, yc - 34), "%d tokens" % s["prompt_tokens_median"], font=font(F_BOLD, 26), fill=FG, anchor="lm")
        dr.text((60, yc + 2), "pair guess %.0f%%" % s["pairwise_acc_pct"], font=font(F_REG, 22), fill=MUTED,
                anchor="lm")
        dr.text((60, yc + 32), "threshold %.0f%%" % s["threshold_test_acc_pct"], font=font(F_REG, 22), fill=MUTED,
                anchor="lm")
        for j, v in enumerate(s["hits_ms"]):
            yy = yc - 26 + (j % 5) * 3
            dr.ellipse([xp(v) - 5, yy - 5, xp(v) + 5, yy + 5], fill=RED)
        for j, v in enumerate(s["misses_ms"]):
            yy = yc + 14 + (j % 5) * 3
            dr.ellipse([xp(v) - 5, yy - 5, xp(v) + 5, yy + 5], fill=BLUE)
        dr.text((x1 + 30, yc - 22), "sent %.0f ms" % s["hit_ms_p50"], font=font(F_BOLD, 22), fill=RED, anchor="lm")
        dr.text((x1 + 30, yc + 20), "not sent %.0f ms" % s["miss_ms_p50"], font=font(F_BOLD, 22), fill=BLUE,
                anchor="lm")
    dr.text((60, H - 60), "Red: the victim's document (cache hit). Blue: a fresh document of the same length. Medians on the"
            " right. Log scale.", font=font(F_REG, 22), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "prompt-cache-hit-miss-latency.webp"))


def mitigations(d):
    W, H = 1600, 980
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    mi = d["mitigate"]
    hd = d["hardened"]
    base = d["member"]["2048"]
    vc = d["victim_cost"]
    dr.text((60, 40), "Which fix closes it? Membership test at 2,048 tokens, pair guess accuracy", font=font(F_BOLD, 34),
            fill=FG)
    dr.text((60, 92), "50% means the attacker learns nothing. Extraction via cached_tokens shown in grey.",
            font=font(F_REG, 24), fill=MUTED)

    def col(v):
        return GREEN if v <= 65 else RED
    rows = [
        ("Default server, pass-through", base["pairwise_acc_pct"], "code read: %s" % d["extract_summary"]["field_exact"]
         + "/%d" % d["extract_summary"]["secrets"]),
        ("Gateway strips cache fields", mi["strip"]["pairwise_acc_pct"], "code read: %s" % mi["strip"]["field_guess"]),
        ("Request sets cache_prompt: false", mi["cache-off"]["pairwise_acc_pct"],
         "code read: %s" % mi["cache-off"]["field_guess"]),
        ("Per-tenant salt in the prefix", mi["salt"]["pairwise_acc_pct"], "code read: %s" % mi["salt"]["field_guess"]),
        ("Server: --cache-ram 0 -sps 0, victim 1 call", hd["victim_calls_1"]["pairwise_acc_pct"], ""),
        ("Same server, victim 4 calls", hd["victim_calls_4"]["pairwise_acc_pct"], ""),
        ("Same server + cache_prompt: false", hd["cache_off_victim_calls_4"]["pairwise_acc_pct"], ""),
        ("Same server + per-tenant salt", hd["salt_victim_calls_4"]["pairwise_acc_pct"], ""),
    ]
    y = hbars(dr, 60, 150, W - 120, [(a, b, col(b), c) for a, b, c in rows], 100.0, bar_h=42, gap=18,
              label_w=560, size=26, reserve=330)
    y += 20
    dr.line([60, y, W - 60, y], fill=BORDER, width=2)
    dr.text((60, y + 30), "What the victim pays (its own 2k-token prompt, repeat calls, p50):", font=font(F_BOLD, 28),
            fill=FG)
    dr.text((60, y + 80), "pass-through %.0f ms     per-tenant salt %.0f ms     cache_prompt: false %.0f ms" % (
        vc["pass-through"]["p50_ms"], vc["salt"]["p50_ms"], vc["cache-off"]["p50_ms"]), font=font(F_REG, 28), fill=FG)
    dr.text((60, H - 50), "%d trials per row. SmolLM2-135M, llama.cpp build 12359, -np 4, Apple M2 Pro." % base["n"],
            font=font(F_REG, 22), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "prompt-cache-mitigations.webp"))


def main():
    d = json.load(open(DATA))
    header(d)
    transcript(d)
    latency(d)
    mitigations(d)


if __name__ == "__main__":
    main()
