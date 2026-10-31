#!/usr/bin/env python3
"""Generate the three webp images for the LoRA fine-tuning practical guide post.

All three are programmatically drawn (no external assets), saved at webp
quality ~82, matching the dimensions recent posts use (1400x840).
"""
from PIL import Image, ImageDraw, ImageFont

W, H = 1400, 840
OUT = "assets/img/posts/ai"

F_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
F_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
F_MONO = "/System/Library/Fonts/Monaco.ttf"

# Dark poster palette (matches the blueprint look of recent post art)
BG = (13, 17, 23)
PANEL = (22, 27, 34)
BORDER = (48, 54, 61)
FG = (230, 237, 243)
MUTED = (139, 148, 158)
BLUE = (88, 166, 255)
GREEN = (63, 185, 80)
ORANGE = (240, 136, 62)
RED = (248, 81, 73)
PURPLE = (188, 140, 255)


def font(path, size):
    return ImageFont.truetype(path, size)


def text_size(d, s, f):
    box = d.textbbox((0, 0), s, font=f)
    return box[2] - box[0], box[3] - box[1]


def ctext(d, cx, cy, s, f, fill):
    w, h = text_size(d, s, f)
    d.text((cx - w / 2, cy - h / 2), s, font=f, fill=fill)


def rrect(d, xy, radius, fill, outline, width=2):
    d.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def arrow(d, x0, y0, x1, y1, fill, width=4, head=14):
    d.line((x0, y0, x1, y1), fill=fill, width=width)
    import math
    ang = math.atan2(y1 - y0, x1 - x0)
    for a in (ang + 2.6, ang - 2.6):
        d.line((x1, y1, x1 + head * math.cos(a), y1 + head * math.sin(a)),
               fill=fill, width=width)


def save(img, name):
    img.save(f"{OUT}/{name}", "WEBP", quality=82)
    print("wrote", f"{OUT}/{name}", img.size)


# ---------------------------------------------------------------- hero
def hero():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # grid
    for x in range(0, W, 40):
        d.line((x, 0, x, H), fill=(20, 25, 32), width=1)
    for y in range(0, H, 40):
        d.line((0, y, W, y), fill=(20, 25, 32), width=1)

    title = font(F_BOLD, 88)
    sub = font(F_REG, 34)
    small = font(F_BOLD, 26)

    ctext(d, W / 2, 120, "LoRA", font(F_BOLD, 150), BLUE)
    ctext(d, W / 2, 235, "Fine-Tuning LLMs: A Practical Guide", title, FG)
    ctext(d, W / 2, 300, "adapters, ranks, learning rates and the eval harness that says it worked", sub, MUTED)

    # frozen base model block
    bx0, by0, bx1, by1 = 130, 400, 720, 720
    rrect(d, (bx0, by0, bx1, by1), 18, PANEL, BORDER, 3)
    ctext(d, (bx0 + bx1) / 2, by0 + 42, "pretrained base model", small, FG)
    ctext(d, (bx0 + bx1) / 2, by0 + 78, "W  (frozen)", font(F_MONO, 30), MUTED)
    # weight matrix with snowflakes
    snow = font(F_REG, 22)
    cell = 44
    gx0 = bx0 + 55
    gy0 = by0 + 110
    for r in range(4):
        for c in range(8):
            x0 = gx0 + c * cell
            y0 = gy0 + r * cell
            d.rectangle((x0, y0, x0 + cell - 6, y0 + cell - 6),
                        fill=(33, 38, 45), outline=BORDER)
            ctext(d, x0 + (cell - 6) / 2, y0 + (cell - 6) / 2, "*", snow, BLUE)

    # trainable LoRA adapter
    ax0, ay0, ax1, ay1 = 830, 430, 1270, 690
    rrect(d, (ax0, ay0, ax1, ay1), 18, (22, 40, 30), GREEN, 4)
    ctext(d, (ax0 + ax1) / 2, ay0 + 40, "LoRA adapter (trainable)", small, GREEN)
    # A and B matrices
    ctext(d, ax0 + 95, ay0 + 150, "A", font(F_BOLD, 60), ORANGE)
    ctext(d, ax0 + 95, ay0 + 205, "r x d", font(F_MONO, 24), MUTED)
    ctext(d, (ax0 + ax1) / 2, ay0 + 150, "x", font(F_BOLD, 44), FG)
    ctext(d, ax1 - 95, ay0 + 150, "B", font(F_BOLD, 60), PURPLE)
    ctext(d, ax1 - 95, ay0 + 205, "d x r", font(F_MONO, 24), MUTED)
    # slim rank bar
    d.rectangle((ax0 + 40, ay0 + 240 - 12, ax1 - 40, ay0 + 240 + 12), fill=(63, 185, 80))
    ctext(d, (ax0 + ax1) / 2, ay0 + 240, "rank r = 16", font(F_BOLD, 20), BG)

    arrow(d, bx1 + 10, (by0 + by1) / 2, ax0 - 10, (ay0 + ay1) / 2, BLUE, 5)
    ctext(d, (bx1 + ax0) / 2, (by0 + by1) / 2 - 45, "attach", font(F_BOLD, 24), BLUE)

    ctext(d, W / 2, H - 50, "lamplit labs", font(F_BOLD, 24), MUTED)
    save(img, "lora-fine-tuning-practical-guide.webp")


# ------------------------------------------------------- rank vs memory
def rank_chart():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    ctext(d, W / 2, 60, "LoRA rank r: trainable parameters and optimizer memory", font(F_BOLD, 44), FG)
    ctext(d, W / 2, 108, "7B base model, bf16 weights, AdamW states, adapter on attention + MLP projections", font(F_REG, 26), MUTED)

    # plot area
    px0, py0, px1, py1 = 150, 160, 1150, 700
    d.line((px0, py0, px0, py1), fill=BORDER, width=3)
    d.line((px0, py1, px1, py1), fill=BORDER, width=3)

    ranks = [1, 4, 8, 16, 32, 64, 128]
    params_m = [4.2, 16.8, 33.6, 67.1, 134.2, 268.4, 536.9]   # millions, illustrative
    optim_gb = [p * 12 / 1024 for p in params_m]               # AdamW fp32 m+v+master ~12 B/param
    xmax = len(ranks)
    ymax = 600.0

    def xy(i, v):
        x = px0 + (i + 0.5) / xmax * (px1 - px0)
        y = py1 - v / ymax * (py1 - py0)
        return x, y

    # gridlines + y labels
    lbl = font(F_REG, 22)
    for gv in range(0, 601, 100):
        y = py1 - gv / ymax * (py1 - py0)
        d.line((px0, y, px1, y), fill=(28, 33, 40), width=1)
        d.text((px0 - 90, y - 12), f"{gv} M", font=lbl, fill=MUTED)
    for i, r in enumerate(ranks):
        x, _ = xy(i, 0)
        ctext(d, x, py1 + 34, f"r={r}", font(F_BOLD, 24), FG)

    # bars: params (M)
    bw = 42
    for i, p in enumerate(params_m):
        x, y = xy(i, p)
        d.rectangle((x - bw, y, x - 4, py1), fill=BLUE)
        ctext(d, x - bw / 2 - 2, y - 18, f"{p:.0f}", font(F_BOLD, 20), BLUE)

    # line: optimizer GB on twin scale (600M ~ 7.0 GB)
    pts = []
    for i, g in enumerate(optim_gb):
        x, _ = xy(i, 0)
        y = py1 - (g / 7.0) * (py1 - py0)
        pts.append((x + bw - 4, y))
    d.line(pts, fill=ORANGE, width=4)
    for (x, y), g in zip(pts, optim_gb):
        d.ellipse((x - 7, y - 7, x + 7, y + 7), fill=ORANGE)
        ctext(d, x, y - 24, f"{g:.1f}", font(F_BOLD, 20), ORANGE)

    # right axis label
    d.text((px1 + 12, py0 - 6), "GB", font=lbl, fill=ORANGE)
    d.text((px0 - 96, py0 - 34), "params", font=lbl, fill=BLUE)

    # legend
    d.rectangle((px0 + 20, py0 + 20, px0 + 44, py0 + 44), fill=BLUE)
    d.text((px0 + 56, py0 + 20), "trainable parameters (M)", font=lbl, fill=FG)
    d.line((px0 + 20, py0 + 76, px0 + 44, py0 + 76), fill=ORANGE, width=5)
    d.text((px0 + 56, py0 + 64), "AdamW optimizer memory (GB)", font=lbl, fill=FG)

    # sweet spot callout
    sx, sy = xy(3, params_m[3])
    rrect(d, (sx - 130, sy - 120, sx + 170, sy - 56), 10, (22, 40, 30), GREEN, 3)
    ctext(d, sx + 20, sy - 88, "sweet spot for most tasks: r = 8-32", font(F_BOLD, 22), GREEN)

    save(img, "lora-rank-parameters-memory.webp")


# ------------------------------------------------------------ pipeline
def pipeline():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    ctext(d, W / 2, 56, "The fine-tuning loop that keeps quality honest", font(F_BOLD, 44), FG)

    stages = [
        ("1. dataset", "JSONL chat records\nconsistent format\nnear-duplicate split", BLUE),
        ("2. config", "rank, alpha, dropout\ntarget modules\nLR + schedule", PURPLE),
        ("3. train", "1 smoke epoch first\nloss curve watched\ncheckpoints kept", ORANGE),
        ("4. eval", "held-out rubric set\nbase vs tuned diff\nregression gate", GREEN),
        ("5. merge", "adapter merged\nor served alongside\ntagged + versioned", RED),
    ]

    box_w, box_h, gap = 230, 320, 30
    total = len(stages) * box_w + (len(stages) - 1) * gap
    x = (W - total) / 2
    y0 = 200
    small = font(F_REG, 22)
    for i, (title, body, color) in enumerate(stages):
        x0 = x + i * (box_w + gap)
        rrect(d, (x0, y0, x0 + box_w, y0 + box_h), 16, PANEL, color, 4)
        ctext(d, x0 + box_w / 2, y0 + 40, title, font(F_BOLD, 28), color)
        lines = body.split("\n")
        for j, ln in enumerate(lines):
            ctext(d, x0 + box_w / 2, y0 + 120 + j * 44, ln, small, FG)
        if i < len(stages) - 1:
            arrow(d, x0 + box_w + 3, y0 + box_h / 2,
                  x0 + box_w + gap - 3, y0 + box_h / 2, MUTED, 4)

    # feedback loop: eval -> dataset/config
    fy = y0 + box_h + 90
    d.line((x + 3.5 * (box_w + gap) - box_w / 2 - gap, y0 + box_h, x + 3.5 * (box_w + gap) - box_w / 2 - gap, fy), fill=GREEN, width=4)
    d.line((x + 3.5 * (box_w + gap) - box_w / 2 - gap, fy, x + box_w / 2, fy), fill=GREEN, width=4)
    arrow(d, x + box_w / 2, fy, x + box_w / 2, y0 + box_h + 6, GREEN, 4)
    ctext(d, W / 2, fy + 34, "eval failures become new training examples - the loop repeats until the gate passes", font(F_BOLD, 26), GREEN)

    save(img, "lora-fine-tuning-pipeline.webp")


hero()
rank_chart()
pipeline()
