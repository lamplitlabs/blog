#!/usr/bin/env bash
# Train SmolLM2-135M-Instruct on each replay mix with llama-finetune (one epoch at a time, same
# settings as scripts/finetune-eval/run_sweep.sh) and evaluate every checkpoint: seen-blog PPL,
# held-out-post PPL, general-English PPL + KL divergence to the base model, and HellaSwag.
#
#   scripts/finetune-replay/run_mixes.sh <work_dir> <base.gguf>
#
# <work_dir>/corpus must hold the files build_corpora.py and build_mixes.py write.
# Env: MIXES (default "0 10 25 50"; "25s1" is mix_25s1.txt from build_mixes.py --order-seed 1), LR (default 1e-5, llama-finetune's default), EPOCHS (default 2).
set -euo pipefail
work=$(cd "$1" && pwd); base=$(cd "$(dirname "$2")" && pwd)/$(basename "$2")
MIXES=${MIXES:-"0 10 25 50"}; LR=${LR:-1e-5}; EPOCHS=${EPOCHS:-2}
cd "$work"; mkdir -p logs models

evaluate() { # model tag
  local m=$1 t=$2
  [[ -f logs/$t.eval.done ]] && return
  llama-perplexity -m "$m" -f corpus/train_seen.txt -c 512 -ngl 99 > logs/$t.ppl_seen.log 2>&1
  llama-perplexity -m "$m" -f corpus/blog_heldout.txt -c 512 -ngl 99 > logs/$t.ppl_heldout.log 2>&1
  if [[ $t == base ]]; then
    llama-perplexity -m "$m" -f corpus/general_wiki.txt -c 512 -ngl 99 --kl-divergence-base base_general.kld > logs/$t.general.log 2>&1
  else
    llama-perplexity -m "$m" -f corpus/general_wiki.txt -c 512 -ngl 99 --kl-divergence-base base_general.kld --kl-divergence > logs/$t.general.log 2>&1
  fi
  llama-perplexity -m "$m" -f corpus/hellaswag_val.txt --hellaswag --hellaswag-tasks 1000 -c 512 -ngl 99 > logs/$t.hellaswag.log 2>&1
  touch logs/$t.eval.done
}

evaluate "$base" base
for mix in $MIXES; do
  num=${mix%%s*}; mix=$(printf '%02d' "$num")${mix#"$num"}
  # resume: a mix whose last epoch is already evaluated is finished (its earlier checkpoints were deleted)
  [[ -f logs/mix${mix}_lr${LR}_ep${EPOCHS}.eval.done ]] && continue
  prev=$base
  for ep in $(seq 1 "$EPOCHS"); do
    tag="mix${mix}_lr${LR}_ep${ep}"; out=models/$tag.gguf
    if [[ ! -f $out ]]; then
      start=$(date +%s)
      llama-finetune -m "$prev" -f "corpus/mix_${mix}.txt" -c 256 -b 256 -ub 256 -ngl 99 \
        -epochs 1 -lr "$LR" -s 1 -o "$out" > logs/$tag.train.log 2>&1
      echo $(( $(date +%s) - start )) > logs/$tag.train_seconds
    fi
    evaluate "$out" "$tag"
    [[ $prev != "$base" ]] && rm -f "$prev"   # keep disk use flat: only the latest checkpoint per mix
    prev=$out
    echo "$(date +%T) done $tag"
  done
done
