#!/usr/bin/env bash
# Watch script: flags external links in _posts that are broken (DNS failure,
# connection refused, timeout, or a 4xx/5xx status). tools/test.sh runs
# htmlproofer with --disable-external, so these links are never checked by
# the project's own build/test; a dead reference link degrades a reader's
# experience but passes CI silently today. This script is read-only and
# prints only when it finds a problem, so it is safe to run on a schedule.
#
# Two classes of false positives are filtered out so the report stays
# actionable:
#   * HTTP 404 from a single-page app host (e.g. tools.lamplitlabs.com on
#     GitHub Pages serves the app from 404.html for every client-side route,
#     so curl sees 404 while a browser renders the tool). A 404 is accepted
#     when the host's /sitemap.xml lists the URL.
#   * HTTP 403 from hosts that block non-browser clients wholesale
#     (medium.com, stackoverflow.com). When the host's root also answers 403
#     the status says nothing about the specific page, so it is not reported.
#   * Transient 5xx/429 answers are re-probed with a short backoff before
#     being reported: archive hosts (web.archive.org) rate-limit bursts with
#     a 503 that clears seconds later (seen on SCHED-013, 2026-10-20).
#
# Usage: tools/check_external_links.sh
# Exit status: 0 always (it is a watcher, not a gate); problems go to stdout.

set -u

UA='Mozilla/5.0 (blog-link-watch)'

urls="$(grep -rhoE '\]\(https?://[^) ]+\)' _posts --include='*.md' 2>/dev/null \
  | sed -E 's/^\]\(//; s/\)$//' \
  | sort -u)"

[ -z "$urls" ] && exit 0

# origin_of URL -> "https://host"
origin_of() {
  printf '%s' "$1" | sed -E 's#^(https?://[^/]+).*#\1#'
}

# Caches keyed by origin, so each host is probed at most once.
sitemap_cache_dir="$(mktemp -d 2>/dev/null || mktemp -d -t linkwatch)"
trap 'rm -rf "$sitemap_cache_dir"' EXIT

cache_key() { printf '%s' "$1" | tr -c 'A-Za-z0-9' '_'; }

# listed_in_sitemap URL -> 0 when the origin's sitemap.xml contains the URL
# (with or without a trailing slash).
listed_in_sitemap() {
  local url="$1" origin key file
  origin="$(origin_of "$url")"
  key="$(cache_key "$origin")"
  file="$sitemap_cache_dir/sitemap_$key"
  if [ ! -f "$file" ]; then
    curl -s --max-time 8 -L -A "$UA" "$origin/sitemap.xml" 2>/dev/null \
      | grep -oE '<loc>[^<]+' | sed -E 's/^<loc>//; s#/$##' > "$file" || true
  fi
  grep -qxF "${url%/}" "$file"
}

# root_forbidden URL -> 0 when the origin root itself answers 403
root_forbidden() {
  local origin key file code
  origin="$(origin_of "$1")"
  key="$(cache_key "$origin")"
  file="$sitemap_cache_dir/root_$key"
  if [ ! -f "$file" ]; then
    code="$(probe "$origin/")"
    printf '%s' "$code" > "$file"
  fi
  [ "$(cat "$file")" = "403" ]
}

# probe URL -> HTTP status code. --retry-all-errors makes --retry apply to
# 5xx/429 too, so one burst-limit answer does not surface as a broken link.
probe() {
  curl -s -o /dev/null -w '%{http_code}' --max-time 8 --retry 1 --retry-delay 2 \
    --retry-all-errors -L -A "$UA" "$1" 2>/dev/null
}

problems=0
while IFS= read -r url; do
  [ -z "$url" ] && continue
  code="$(probe "$url")"
  if [ -z "$code" ] || [ "$code" = "000" ]; then
    echo "UNREACHABLE  $url"
    problems=$((problems + 1))
  elif [ "$code" = "404" ] && listed_in_sitemap "$url"; then
    : # SPA client-side route served from 404.html; the site itself claims it
  elif [ "$code" = "403" ] && root_forbidden "$url"; then
    : # host blocks non-browser clients entirely; status is not about this page
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
