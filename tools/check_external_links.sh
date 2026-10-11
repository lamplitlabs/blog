#!/usr/bin/env bash
# Watch script: flags external links in _posts that are broken (DNS failure,
# connection refused, timeout, or a 4xx/5xx status). tools/test.sh runs
# htmlproofer with --disable-external, so these links are never checked by
# the project's own build/test; a dead reference link degrades a reader's
# experience but passes CI silently today. This script is read-only and
# prints only when it finds a problem, so it is safe to run on a schedule.
#
# Usage: tools/check_external_links.sh
# Exit status: 0 always (it is a watcher, not a gate); problems go to stdout.

set -u

urls="$(grep -rhoE '\]\(https?://[^) ]+\)' _posts --include='*.md' 2>/dev/null \
  | sed -E 's/^\]\(//; s/\)$//' \
  | sort -u)"

[ -z "$urls" ] && exit 0

problems=0
while IFS= read -r url; do
  [ -z "$url" ] && continue
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 --retry 1 -L -A 'Mozilla/5.0 (blog-link-watch)' "$url" 2>/dev/null)"
  if [ -z "$code" ] || [ "$code" = "000" ]; then
    echo "UNREACHABLE  $url"
    problems=$((problems + 1))
  elif [ "${code:0:1}" = "4" ] || [ "${code:0:1}" = "5" ]; then
    echo "HTTP $code  $url"
    problems=$((problems + 1))
  fi
done <<< "$urls"

if ((problems > 0)); then
  echo "---"
  echo "$problems of $(echo "$urls" | wc -l | tr -d ' ') external links in _posts look broken (tools/test.sh does not check these: htmlproofer runs with --disable-external)."
fi

exit 0
