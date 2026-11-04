#!/usr/bin/env bash
# Full fine-tune SmolLM2-135M-Instruct on this blog's posts with llama-finetune, one epoch at a time,
# and evaluate every checkpoint with llama-perplexity: seen-text PPL, held-out-post PPL, general-text
# PPL + KL divergence to the base model, HellaSwag and Winogrande.
#
#   scripts/finetune-eval/run_sweep.sh <work_dir> <base.gguf>
#
# <work_dir>/corpus must hold the files build_corpora.py writes. Everything else lands in <work_dir>.
# Env: LRS (default "1e-5 1e-4"), EPOCHS (default 3), TRAIN_CHARS (default 400000).
set -euo pipefail
work=$(cd "$1" && pwd); base=$(cd "$(dirname "$2")" && pwd)/$(basename "$2")
LRS=${LRS:-"1e-5 1e-4"}; EPOCHS=${EPOCHS:-3}; TRAIN_CHARS=${TRAIN_CHARS:-400000}
cd "$work"; mkdir -p logs models
head -c "$TRAIN_CHARS" corpus/blog_train.txt > corpus/train_subset.txt
head -c 100000 corpus/train_subset.txt > corpus/train_seen.txt

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
  llama-perplexity -m "$m" -f corpus/winogrande_val.csv --winogrande -c 512 -ngl 99 > logs/$t.winogrande.log 2>&1
  llama-completion -m "$m" -p "The first thing to check when an Azure OpenAI client starts getting 429 errors is" \
    -n 48 --temp 0 -s 1 -no-cnv -ngl 99 > logs/$t.sample.txt 2> /dev/null || true
  touch logs/$t.eval.done
}

evaluate "$base" base
for lr in $LRS; do
  prev=$base
  for ep in $(seq 1 "$EPOCHS"); do
    tag="lr${lr}_ep${ep}"; out=models/$tag.gguf
    if [[ ! -f $out ]]; then
      start=$(date +%s)
      llama-finetune -m "$prev" -f corpus/train_subset.txt -c 256 -b 256 -ub 256 -ngl 99 \
        -epochs 1 -lr "$lr" -s 1 -o "$out" > logs/$tag.train.log 2>&1
      echo $(( $(date +%s) - start )) > logs/$tag.train_seconds
    fi
    evaluate "$out" "$tag"
    [[ $prev != "$base" ]] && rm -f "$prev"   # keep disk use flat: only the latest checkpoint per lr
    prev=$out
    echo "$(date +%T) done $tag"
  done
done
