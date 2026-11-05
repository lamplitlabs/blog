#!/usr/bin/env python3
"""Convert a small Hugging Face llama-family checkpoint (SmolLM2) to an F32 GGUF for llama.cpp.

Self-contained: stdlib + numpy only (no torch, no `gguf` package, no llama.cpp checkout). It reads
bf16/f16/f32 safetensors directly, permutes q/k for llama.cpp's rope layout, and writes the
byte-level BPE tokenizer. Written for the fine-tuning evaluation post; it covers what SmolLM2 needs
and nothing more.

    python3 scripts/finetune-eval/hf_to_gguf.py <hf_snapshot_dir> <out.gguf>
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import numpy as np

ALIGN = 32
T_U32, T_I32, T_F32, T_BOOL, T_STR, T_ARR = 4, 5, 6, 7, 8, 9
TOK_NORMAL, TOK_CONTROL, TOK_USER = 1, 3, 4


def pad(n: int) -> int:
    return (n + ALIGN - 1) // ALIGN * ALIGN


def s(x: str) -> bytes:
    raw = x.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def val(t: int, v) -> bytes:
    if t == T_U32:
        return struct.pack("<I", v)
    if t == T_I32:
        return struct.pack("<i", v)
    if t == T_F32:
        return struct.pack("<f", v)
    if t == T_BOOL:
        return struct.pack("<?", v)
    if t == T_STR:
        return s(v)
    et, items = v
    return struct.pack("<IQ", et, len(items)) + b"".join(val(et, i) for i in items)


def load_safetensors(path: Path) -> dict[str, np.ndarray]:
    raw = path.read_bytes()
    (hlen,) = struct.unpack("<Q", raw[:8])
    header = json.loads(raw[8 : 8 + hlen])
    base = 8 + hlen
    out = {}
    for name, meta in header.items():
        if name == "__metadata__":
            continue
        a, b = meta["data_offsets"]
        buf = raw[base + a : base + b]
        if meta["dtype"] == "BF16":
            u = np.frombuffer(buf, dtype="<u2").astype(np.uint32) << 16
            arr = u.view(np.float32)
        elif meta["dtype"] == "F16":
            arr = np.frombuffer(buf, dtype="<f2").astype(np.float32)
        elif meta["dtype"] == "F32":
            arr = np.frombuffer(buf, dtype="<f4").copy()
        else:
            raise SystemExit(f"unsupported dtype {meta['dtype']} for {name}")
        out[name] = arr.reshape(meta["shape"])
    return out


def permute(w: np.ndarray, n_head: int) -> np.ndarray:
    return w.reshape(n_head, 2, w.shape[0] // n_head // 2, *w.shape[1:]).swapaxes(1, 2).reshape(w.shape)


LAYER_MAP = {
    "input_layernorm.weight": "attn_norm.weight",
    "post_attention_layernorm.weight": "ffn_norm.weight",
    "self_attn.q_proj.weight": "attn_q.weight",
    "self_attn.k_proj.weight": "attn_k.weight",
    "self_attn.v_proj.weight": "attn_v.weight",
    "self_attn.o_proj.weight": "attn_output.weight",
    "mlp.gate_proj.weight": "ffn_gate.weight",
    "mlp.up_proj.weight": "ffn_up.weight",
    "mlp.down_proj.weight": "ffn_down.weight",
}


def gguf_name(hf: str) -> str | None:
    if hf == "model.embed_tokens.weight":
        return "token_embd.weight"
    if hf == "model.norm.weight":
        return "output_norm.weight"
    if hf.startswith("model.layers."):
        _, _, idx, *rest = hf.split(".")
        tail = LAYER_MAP.get(".".join(rest))
        return f"blk.{idx}.{tail}" if tail else None
    return None


def main(src: Path, dst: Path) -> None:
    cfg = json.loads((src / "config.json").read_text())
    tok = json.loads((src / "tokenizer.json").read_text())
    tcfg = json.loads((src / "tokenizer_config.json").read_text())
    n_head, n_kv = cfg["num_attention_heads"], cfg["num_key_value_heads"]
    kv: list[tuple[str, int, object]] = [
        ("general.architecture", T_STR, "llama"),
        ("general.name", T_STR, "SmolLM2-135M-Instruct"),
        ("general.file_type", T_U32, 0),
        ("llama.context_length", T_U32, cfg["max_position_embeddings"]),
        ("llama.embedding_length", T_U32, cfg["hidden_size"]),
        ("llama.block_count", T_U32, cfg["num_hidden_layers"]),
        ("llama.feed_forward_length", T_U32, cfg["intermediate_size"]),
        ("llama.attention.head_count", T_U32, n_head),
        ("llama.attention.head_count_kv", T_U32, n_kv),
        ("llama.attention.layer_norm_rms_epsilon", T_F32, cfg["rms_norm_eps"]),
        ("llama.rope.freq_base", T_F32, float(cfg["rope_theta"])),
        ("llama.rope.dimension_count", T_U32, cfg["hidden_size"] // n_head),
        ("llama.vocab_size", T_U32, cfg["vocab_size"]),
    ]
    vocab = tok["model"]["vocab"]
    added = {t["id"]: t for t in tok.get("added_tokens", [])}
    n_vocab = max(max(vocab.values()), *added.keys()) + 1
    tokens, types = [""] * n_vocab, [TOK_NORMAL] * n_vocab
    for text, i in vocab.items():
        tokens[i] = text
    for i, t in added.items():
        tokens[i] = t["content"]
        types[i] = TOK_CONTROL if t.get("special") else TOK_USER
    merges = [m if isinstance(m, str) else " ".join(m) for m in tok["model"]["merges"]]
    by_text = {t: i for i, t in enumerate(tokens)}
    kv += [
        ("tokenizer.ggml.model", T_STR, "gpt2"),
        ("tokenizer.ggml.pre", T_STR, "smollm"),
        ("tokenizer.ggml.tokens", T_ARR, (T_STR, tokens)),
        ("tokenizer.ggml.token_type", T_ARR, (T_I32, types)),
        ("tokenizer.ggml.merges", T_ARR, (T_STR, merges)),
        ("tokenizer.ggml.add_bos_token", T_BOOL, False),
    ]
    for key, gkey in (("bos_token", "bos"), ("eos_token", "eos"), ("pad_token", "padding"), ("unk_token", "unknown")):
        v = tcfg.get(key)
        if isinstance(v, dict):
            v = v.get("content")
        if isinstance(v, str) and v in by_text:
            kv.append((f"tokenizer.ggml.{gkey}_token_id", T_U32, by_text[v]))
    if isinstance(tcfg.get("chat_template"), str):
        kv.append(("tokenizer.chat_template", T_STR, tcfg["chat_template"]))

    weights = {}
    for f in sorted(src.glob("*.safetensors")):
        weights.update(load_safetensors(f))
    tensors = []
    for hf in sorted(weights):
        name = gguf_name(hf)
        if name is None:
            continue
        arr = weights[hf].astype(np.float32)
        if name.endswith("attn_q.weight"):
            arr = permute(arr, n_head)
        elif name.endswith("attn_k.weight"):
            arr = permute(arr, n_kv)
        tensors.append((name, np.ascontiguousarray(arr)))

    head = bytearray(b"GGUF" + struct.pack("<IQQ", 3, len(tensors), len(kv)))
    for key, t, v in kv:
        head += s(key) + struct.pack("<I", t) + val(t, v)
    off = 0
    for name, arr in tensors:
        dims = list(reversed(arr.shape))
        head += s(name) + struct.pack("<I", len(dims)) + b"".join(struct.pack("<Q", d) for d in dims)
        head += struct.pack("<IQ", 0, off)
        off += pad(arr.nbytes)
    head += b"\0" * (pad(len(head)) - len(head))
    with dst.open("wb") as fh:
        fh.write(head)
        for _, arr in tensors:
            data = arr.tobytes()
            fh.write(data + b"\0" * (pad(len(data)) - len(data)))
    print(f"wrote {dst} ({len(tensors)} tensors, {dst.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
