#!/usr/bin/env python3
"""Build the webp images for the "document permissions in RAG, measured" post.

Usage:
  python3 scripts/rag-acl/gen_images.py

Reads scripts/data/rag-acl-enforcement.json (written by summarise.py). Every number
in the images comes from that file; the terminal panel prints the transcript that
capture.py recorded, line for line (long lines cut with an ellipsis).

Outputs:
  assets/img/headers/ai/ai-security-rag-document-permissions-measured.webp  (1600x840, 40:21)
  assets/img/posts/ai/rag-acl-unauthorized-answers.webp
  assets/img/posts/ai/rag-acl-prompt-rule-transcript.webp
  assets/img/posts/ai/rag-acl-post-filter-depth.webp
  assets/img/posts/ai/rag-acl-shared-cache.webp
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "scripts", "data", "rag-acl-enforcement.json")
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


def tw(dr, text, f):
    return dr.textlength(text, font=f)


def hbars(dr, x, y, w, rows, vmax, bar_h=46, gap=22, label_w=330, fmt="{:.1f}%", size=26, reserve=230):
    """rows: (label, value, colour, note)."""
    f = font(F_REG, size)
    fb = font(F_BOLD, size)
    for label, value, colour, note in rows:
        dr.text((x, y + bar_h / 2), label, font=f, fill=FG, anchor="lm")
        bx = x + label_w
        bw = (w - label_w - reserve) * value / vmax
        dr.rectangle([bx, y, bx + w - label_w - reserve, y + bar_h], fill=PANEL)
        dr.rectangle([bx, y, bx + max(bw, 3), y + bar_h], fill=colour)
        dr.text((bx + max(bw, 3) + 14, y + bar_h / 2), fmt.format(value), font=fb, fill=FG, anchor="lm")
        if note:
            dr.text((bx + max(bw, 3) + 14 + tw(dr, fmt.format(value), fb) + 14, y + bar_h / 2), note,
                    font=font(F_REG, size - 6), fill=MUTED, anchor="lm")
        y += bar_h + gap
    return y


def header(d):
    W, H = 1600, 840
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    un = d["llm_unauthorized"]
    n = un["none"]["pairs"]
    dr.text((80, 64), "Document permissions in RAG, measured", font=font(F_BOLD, 56), fill=FG)
    dr.text((80, 146), "A contractor (public group only) asks %d questions whose answer sits only in" % n,
            font=font(F_REG, 28), fill=MUTED)
    dr.text((80, 184), "finance, HR, legal, engineering or exec documents. Replies that gave the answer:",
            font=font(F_REG, 28), fill=MUTED)
    rows = [
        ("No ACL check", un["none"]["answer_pct"], RED, "%d of %d" % (un["none"]["answer_in_reply"], n)),
        ("Prompt rule (\"RESTRICTED\")", un["prompt-rule"]["answer_pct"], RED,
         "%d of %d" % (un["prompt-rule"]["answer_in_reply"], n)),
        ("Post-filter, fetch 100", un["post-filter@100"]["answer_pct"], GREEN,
         "%d of %d" % (un["post-filter@100"]["answer_in_reply"], n)),
        ("Pre-filter in the query", un["pre-filter"]["answer_pct"], GREEN,
         "%d of %d" % (un["pre-filter"]["answer_in_reply"], n)),
        ("No documents at all", un["no-context"]["answer_pct"], GREY,
         "%d of %d (model's own knowledge)" % (un["no-context"]["answer_in_reply"], n)),
    ]
    hbars(dr, 80, 270, W - 160, rows, 25.0, bar_h=58, gap=26, label_w=430, size=30)
    c = d["cache"]
    dr.text((80, 700), "Shared answer cache keyed on the question only: %d leaked answers in %d queries (3 runs);"
            % (c["question"]["leaks_total"], 3 * c["question"]["queries"]), font=font(F_REG, 26), fill=FG)
    dr.text((80, 738), "keyed on question + group set: %d." % c["question+groups"]["leaks_total"],
            font=font(F_REG, 26), fill=FG)
    dr.text((80, 788), "%s docs, SQLite FTS5 BM25 top %d, %s" % (format(d["n_docs"], ","), d["k"],
                                                              "SmolLM2-135M on llama.cpp, Apple M2 Pro"),
            font=font(F_REG, 22), fill=MUTED)
    save(img, os.path.join(OUT_HEAD, "ai-security-rag-document-permissions-measured.webp"), quality=90)


def unauthorized(d):
    W, H = 1600, 1000
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    un = d["llm_unauthorized"]
    au = d["llm_authorized_mixed"]
    n = un["none"]["pairs"]
    na = au["none"]["pairs"]
    dr.text((60, 40), "Did the contractor get an answer it may not see?", font=font(F_BOLD, 34), fill=FG)
    dr.text((60, 92), "%d questions whose only source is a restricted document. Answer string found in the reply."
            % n, font=font(F_REG, 24), fill=MUTED)
    rows = [
        ("No ACL check", un["none"]["answer_pct"], RED, "%d" % un["none"]["answer_in_reply"]),
        ("Prompt rule", un["prompt-rule"]["answer_pct"], RED, "%d" % un["prompt-rule"]["answer_in_reply"]),
        ("Post-filter @100", un["post-filter@100"]["answer_pct"], GREEN, "%d" % un["post-filter@100"]["answer_in_reply"]),
        ("Pre-filter", un["pre-filter"]["answer_pct"], GREEN, "%d" % un["pre-filter"]["answer_in_reply"]),
        ("No documents (baseline)", un["no-context"]["answer_pct"], GREY, "%d" % un["no-context"]["answer_in_reply"]),
    ]
    y = hbars(dr, 60, 150, W - 120, rows, 25.0, label_w=340)
    p = d["prompt_rule_paired"]
    dr.text((60, y + 6), "Paired: of the %d questions leaked with no check (and not answered without documents), the prompt rule"
            % p["leaked_without_rule"], font=font(F_REG, 24), fill=FG)
    dr.text((60, y + 40), "still leaked %d. Refusals under the rule: %d of %d."
            % (p["still_leaked_with_rule"], un["prompt-rule"]["refused"], n), font=font(F_REG, 24), fill=FG)
    y += 110
    dr.line([60, y, W - 60, y], fill=BORDER, width=2)
    y += 30
    dr.text((60, y), "Right question, right user: does the ACL method cost answers?", font=font(F_BOLD, 34), fill=FG)
    dr.text((60, y + 52), "%d questions a user may see, where the unfiltered top %d also held documents they may not."
            % (na, d["k"]), font=font(F_REG, 24), fill=MUTED)
    rows = [
        ("No ACL check", au["none"]["correct_pct"], BLUE, "%d correct" % au["none"]["correct"]),
        ("Prompt rule", au["prompt-rule"]["correct_pct"], ORANGE, "%d correct" % au["prompt-rule"]["correct"]),
        ("Pre-filter", au["pre-filter"]["correct_pct"], GREEN, "%d correct" % au["pre-filter"]["correct"]),
    ]
    y = hbars(dr, 60, y + 108, W - 120, rows, 30.0, label_w=340)
    dr.text((60, H - 46), "SmolLM2-135M-Instruct, temperature 0, llama.cpp on an Apple M2 Pro. Small model: absolute accuracy is low;"
            " compare the rows.", font=font(F_REG, 21), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "rag-acl-unauthorized-answers.webp"))


def transcript(d, qid):
    lines = d["captures"][qid]
    size = 20
    mono = font(F_MONO, size)
    line_h = int(size * 1.55)
    W = 1600
    H = 130 + line_h * len(lines) + 40
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle([20, 20, W - 20, H - 20], radius=12, fill=PANEL, outline=BORDER, width=2)
    for i, c in enumerate((RED, YELLOW, GREEN)):
        dr.ellipse([48 + i * 30, 44, 64 + i * 30, 60], fill=c)
    dr.text((160, 52), "capture.py: same question, same user, two ACL strategies (real model output)",
            font=font(F_BOLD, 22), fill=MUTED, anchor="lm")
    y = 100
    width = 118
    for ln in lines:
        if len(ln) > width:
            ln = ln[:width - 3] + "..."
        colour = FG
        if ln.startswith("model>"):
            colour = BLUE
        elif "RESTRICTED" in ln:
            colour = ORANGE
        elif ln.startswith("# gold answer in reply: YES"):
            colour = RED
        elif ln.startswith("# gold answer in reply: no"):
            colour = GREEN
        elif ln.startswith("---"):
            colour = MUTED
        dr.text((50, y), ln, font=mono, fill=colour)
        y += line_h
    save(img, os.path.join(OUT_POSTS, "rag-acl-prompt-rule-transcript.webp"))


def post_filter(d):
    W, H = 1600, 900
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    r = d["retrieval"]
    con = {s: r[s]["per_user"]["contractor"] for s in r}
    q = con["none"]["queries"]
    dr.text((60, 40), "Post-filtering starves the users with the least access", font=font(F_BOLD, 36), fill=FG)
    dr.text((60, 96), "Contractor, %d questions, top %d wanted. Bars: share of questions that got fewer than %d documents."
            % (q, d["k"], d["k"]), font=font(F_REG, 24), fill=MUTED)
    strategies = [("post-filter@4", "Post-filter, fetch 4"), ("post-filter@20", "Post-filter, fetch 20"),
                  ("post-filter@100", "Post-filter, fetch 100"), ("pre-filter", "Pre-filter")]
    rows = []
    for s, label in strategies:
        empty = con[s]["empty_context"]
        short = con[s]["short_context"]
        rows.append((label, 100.0 * (empty + short) / q,
                     RED if (empty + short) / q > 0.2 else (YELLOW if (empty + short) / q > 0.02 else GREEN),
                     "%d empty, %d with 1-%d docs" % (empty, short, d["k"] - 1)))
    y = hbars(dr, 60, 160, W - 120, rows, 100.0, label_w=330, reserve=480)
    dr.text((60, y + 4), "Contractor recall@%d on questions it may see: fetch 4 %.1f%%, fetch 20 %.1f%%, fetch 100 %.1f%%, pre-filter %.1f%%."
            % (d["k"], con["post-filter@4"]["recall_at_k"], con["post-filter@20"]["recall_at_k"],
               con["post-filter@100"]["recall_at_k"], con["pre-filter"]["recall_at_k"]), font=font(F_REG, 24), fill=FG)
    y += 70
    dr.line([60, y, W - 60, y], fill=BORDER, width=2)
    y += 26
    dr.text((60, y), "Retrieval latency, all 5 users x %d questions (median of 3 runs each), ms"
            % (q), font=font(F_BOLD, 28), fill=FG)
    y += 56
    cols = [("none", "No ACL"), ("post-filter@4", "Post @4"), ("post-filter@20", "Post @20"),
            ("post-filter@100", "Post @100"), ("pre-filter", "Pre-filter")]
    fx = font(F_REG, 26)
    fb = font(F_BOLD, 26)
    x0 = 60
    dr.text((x0, y), "", font=fx, fill=FG)
    for i, (s, label) in enumerate(cols):
        dr.text((x0 + 220 + i * 260, y), label, font=fb, fill=MUTED)
    for j, (k, name) in enumerate((("ms_p50", "p50"), ("ms_p95", "p95"), ("ms_p99", "p99"))):
        yy = y + 46 + j * 44
        dr.text((x0, yy), name, font=fb, fill=FG)
        for i, (s, label) in enumerate(cols):
            dr.text((x0 + 220 + i * 260, yy), "%.2f" % r[s][k], font=fx, fill=FG)
    dr.text((60, H - 46), "SQLite %s FTS5, BM25, %s documents, Python %s on an Apple M2 Pro (shared host)."
            % (d["sqlite"], format(d["n_docs"], ","), d["python"]), font=font(F_REG, 21), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "rag-acl-post-filter-depth.webp"))


def cache(d):
    W, H = 1600, 820
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    c = d["cache"]
    n = c["question"]["queries"]
    dr.text((60, 40), "A shared answer cache keyed on the question alone", font=font(F_BOLD, 36), fill=FG)
    dr.text((60, 96), "%d queries from 5 users with different group sets, Zipf-popular questions; median of 3 runs."
            % n, font=font(F_REG, 24), fill=MUTED)
    y = 160
    for keying, title in (("question", "Key: normalised question"), ("question+groups", "Key: question + sorted group set")):
        k = c[keying]
        dr.text((60, y), title, font=font(F_BOLD, 28), fill=FG)
        y += 50
        rows = [
            ("Cache hits", 100.0 * k["hits_median"] / n, BLUE, "%d" % k["hits_median"]),
            ("Hit built for other groups", 100.0 * k["cross_scope_median"] / n, ORANGE if k["cross_scope_median"] else GREEN,
             "%d" % k["cross_scope_median"]),
            ("Hit built from docs it can't read", 100.0 * k["restricted_built_median"] / n,
             RED if k["restricted_built_median"] else GREEN, "%d" % k["restricted_built_median"]),
            ("Answer it could not get itself", 100.0 * k["leaks_median"] / n, RED if k["leaks_median"] else GREEN,
             "%d (all 3 runs: %d)" % (k["leaks_median"], k["leaks_total"])),
        ]
        y = hbars(dr, 60, y, W - 120, rows, 100.0, bar_h=40, gap=16, label_w=470, size=24)
        y += 24
    dr.text((60, H - 46), "Leak = the served reply holds the gold answer, the requester's own pre-filtered answer does not,"
            " and no document it may read contains it.", font=font(F_REG, 21), fill=MUTED)
    save(img, os.path.join(OUT_POSTS, "rag-acl-shared-cache.webp"))


def main():
    d = json.load(open(DATA))
    header(d)
    unauthorized(d)
    transcript(d, "57264d9edd62a815002e80fe")
    post_filter(d)
    cache(d)


if __name__ == "__main__":
    main()
