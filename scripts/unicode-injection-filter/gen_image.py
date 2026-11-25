#!/usr/bin/env python3
"""Draw the body chart for the Unicode prompt-injection filter post.

Usage:
  python3 scripts/unicode-injection-filter/gen_image.py

Reads scripts/data/unicode-injection-filter.json (written by bench.py) and
writes assets/img/posts/ai/unicode-injection-filter-catch-rate.webp. Every
number comes from the JSON.
"""
import io
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image  # noqa: E402

SRC = "scripts/data/unicode-injection-filter.json"
OUT = "assets/img/posts/ai/unicode-injection-filter-catch-rate.webp"
LABELS = {"raw": "raw\n(casefold)", "nfkc": "+ NFKC", "strip_cf": "+ strip Cf",
          "strip_mn": "+ strip Mn", "confusable": "+ confusable\ntable"}


def main():
    with open(SRC, encoding="utf-8") as f:
        data = json.load(f)
    layers = list(data["layers"])
    caught = [data["layers"][l]["caught_pct"] for l in layers]
    changed = [data["layers"][l]["benign_changed"] for l in layers]

    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
    ticks = ["%s\n%d/%d benign rewritten" % (LABELS[l], ch, data["benign"]) for l, ch in zip(layers, changed)]
    bars = ax.bar(ticks, caught, color="#4c78a8")
    for b, c in zip(bars, caught):
        ax.text(b.get_x() + b.get_width() / 2, c + 1.5, "%.1f%%" % c,
                ha="center", fontsize=13, fontweight="bold")
    ax.set_ylim(0, 108)
    ax.set_ylabel("attack strings caught (%)")
    ax.set_title("One keyword filter, %s Unicode-obfuscated injections:\ncatch rate after each cumulative normalisation layer"
                 % format(data["attacks"], ","), fontsize=13)
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.99, 0.01, "Python %s, Unicode %s, seed %d" % (data["python"], data["unicode_version"], data["seed"]),
             ha="right", fontsize=8, color="#666")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    Image.open(buf).convert("RGB").save(OUT, "WEBP", quality=88, method=6)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
