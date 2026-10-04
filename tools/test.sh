#!/usr/bin/env bash
#
# Build and test the site content
#
# Requirement: html-proofer, jekyll
#
# Usage: See help information

set -eu

SITE_DIR="_site"

_config="_config.yml"

_baseurl=""

# Every post under _posts (subfolders included), sorted; computed once in main()
# so all checks share one glob and one denominator.
collect_posts() {
  _posts="$(find _posts -name '*.md' | sort)"
  _posts_total="$(printf '%s\n' "$_posts" | wc -l | tr -d ' ')"
}

help() {
  echo "Build and test the site content"
  echo
  echo "Usage:"
  echo
  echo "   bash $0 [options]"
  echo
  echo "Options:"
  echo '     -c, --config   "<config_a[,config_b[...]]>"    Specify config file(s)'
  echo "     -h, --help               Print this information."
}

read_baseurl() {
  if [[ $_config == *","* ]]; then
    # multiple config
    IFS=","
    read -ra config_array <<<"$_config"

    # reverse loop the config files
    for ((i = ${#config_array[@]} - 1; i >= 0; i--)); do
      _tmp_baseurl="$(grep '^baseurl:' "${config_array[i]}" | sed "s/.*: *//;s/['\"]//g;s/#.*//")"

      if [[ -n $_tmp_baseurl ]]; then
        _baseurl="$_tmp_baseurl"
        break
      fi
    done

  else
    # single config
    _baseurl="$(grep '^baseurl:' "$_config" | sed "s/.*: *//;s/['\"]//g;s/#.*//")"
  fi
}

preflight() {
  if ! command -v bundle >/dev/null 2>&1; then
    echo "error: 'bundle' not found on PATH." >&2
    echo "       Activate the pinned toolchain (e.g. 'mise exec -- bash tools/test.sh') and try again." >&2
    exit 1
  fi

  if ! bundle exec ruby -e 'exit 0' >/dev/null 2>&1; then
    local found_ruby pinned_ruby
    found_ruby="$(ruby -e 'print RUBY_VERSION' 2>/dev/null || echo 'none')"
    pinned_ruby="$(tr -d '[:space:]' <.ruby-version 2>/dev/null || echo 'unknown')"
    echo "error: required gems are not available for this Ruby/bundler." >&2
    echo "       ruby on PATH: $found_ruby; pinned in .ruby-version: $pinned_ruby" >&2
    if [[ $found_ruby != "$pinned_ruby" ]]; then
      echo "       The Ruby versions differ: run 'mise exec ruby@$pinned_ruby -- bash tools/test.sh'." >&2
    else
      echo "       Run 'bundle install' (with the pinned Ruby active) and try again." >&2
    fi
    exit 1
  fi
}

# Fail when two posts use the same tag with different letter case (e.g. "Azurite"
# vs "azurite"): Jekyll would then emit a "Conflict:" line buried in the build
# output and silently drop one tag page. Reads every front-matter style used in
# _posts: space-separated (`tags: a b`), inline list (`tags: [a, b]`) and
# multi-line YAML list (`tags:` followed by `  - a` lines). Scans every post
# recursively (_posts/AI, _posts/Beginner, ... too), not just _posts/*.md.
check_tag_case_duplicates() {
  local tags dupes
  tags="$(awk '
    FNR == 1 { fm = 0; in_tags = 0 }
    /^---[[:space:]]*$/ { fm++; in_tags = 0; next }
    fm != 1 { next }
    in_tags && /^[[:space:]]*-[[:space:]]+/ {
      sub(/^[[:space:]]*-[[:space:]]+/, ""); gsub(/["'"'"']/, ""); sub(/[[:space:]]+$/, "")
      if ($0 != "") print $0
      next
    }
    { in_tags = 0 }
    /^tags:/ {
      sub(/^tags:[[:space:]]*/, "")
      if ($0 == "") { in_tags = 1; next }
      gsub(/[][,"'"'"']/, " ")
      for (i = 1; i <= NF; i++) print $i
    }
  ' $_posts | sort -u)"

  dupes="$(printf '%s\n' "$tags" | awk '{ k = tolower($0); if (k in seen) print seen[k] " / " $0; else seen[k] = $0 }')"

  if [[ -n $dupes ]]; then
    echo "error: tags that differ only by letter case were found in _posts/:" >&2
    printf '       %s\n' "$dupes" >&2
    echo "       Use one spelling per tag so Jekyll does not drop a tag page with a 'Conflict:' warning." >&2
    exit 1
  fi
  echo "tag-case-duplicates: 0 case-variant tag collisions across $(printf '%s\n' "$tags" | grep -c .) distinct tags in $_posts_total posts (rule: tags equal under tolower() but spelled differently)"
}

# Report image coverage of _posts so image-coverage cards can cite one number.
# A post counts as having an image when it has a front-matter `image:` key, a
# markdown `![` image or an `<img` tag; the denominator is every `*.md` under
# _posts including subfolders (same rule as
# `grep -L -E '^image:|!\[|<img' $(find _posts -name '*.md')`). Lists the posts
# still lacking any image so the next one to illustrate can be picked without
# grepping. Informational only: never fails the build.
report_image_coverage() {
  local without
  without="$(grep -L -E '^image:|!\[|<img' $_posts || true)"
  local count=0
  if [[ -n $without ]]; then
    count="$(printf '%s\n' "$without" | wc -l | tr -d ' ')"
  fi
  # Print the exact rule so handoff cards copy this command, not a variant
  # (an unanchored 'image:' would also match "*Header image: ...*" captions).
  echo "image-coverage: $count/$_posts_total posts without image (rule: grep -L -E '^image:|!\\[|<img' \$(find _posts -name '*.md'))"
  if [[ -n $without ]]; then
    printf '  %s\n' $without
  fi
}

# Report alt-text coverage of post header images so alt-text cards can cite one
# number. A post counts as covered when its front-matter `image:` block has a
# nested `alt:` key (Chirpy renders it as the header <img alt>); screen readers
# and image search otherwise get an empty alt. Denominator: posts with an
# `image:` front-matter key (subfolders included). Lists the posts still lacking
# alt text. Informational only: never fails the build.
report_alt_coverage() {
  local with_image without
  with_image="$(grep -l '^image:' $_posts || true)"
  local with_image_total=0
  if [[ -n $with_image ]]; then
    with_image_total="$(printf '%s\n' "$with_image" | wc -l | tr -d ' ')"
  fi
  without="$(for f in $with_image; do
    awk '
      FNR == 1 { fm = 0; in_image = 0; found = 0 }
      /^---[[:space:]]*$/ { fm++; in_image = 0; next }
      fm != 1 { next }
      /^image:/ { in_image = 1; next }
      /^[^[:space:]]/ { in_image = 0 }
      in_image && /^[[:space:]]+alt:[[:space:]]*[^[:space:]]/ { found = 1 }
      END { exit found ? 0 : 1 }
    ' "$f" || echo "$f"
  done)"
  local count=0
  if [[ -n $without ]]; then
    count="$(printf '%s\n' "$without" | wc -l | tr -d ' ')"
  fi
  echo "alt-coverage: $count/$with_image_total posts with a front-matter image but no alt text (rule: 'image:' block without a nested 'alt:' key)"
  if [[ -n $without ]]; then
    printf '  %s\n' $without
  fi
}

# Fail when a post has no front-matter `description:` key. jekyll-seo-tag and the
# Atom feed fall back to the generic site description otherwise, so every post
# would show the same search snippet. Same rule as
# `grep -L "^description:" $(find _posts -name '*.md')` (subfolders included).
check_post_descriptions() {
  local missing
  missing="$(grep -L '^description:' $_posts || true)"
  if [[ -n $missing ]]; then
    echo "error: posts without a front-matter 'description:' were found in _posts/:" >&2
    printf '       %s\n' $missing >&2
    echo "       Add a one-sentence 'description:' so search snippets and the feed describe the post itself." >&2
    exit 1
  fi

  # Also fail when a description is shorter than 50 or longer than 160
  # characters: search engines truncate snippets around 160 characters and
  # very short ones say nothing about the post. Quotes around the value are
  # stripped before counting; the first `description:` line of a post is used.
  local bad
  bad="$(for f in $_posts; do
    d="$(grep -m1 '^description:' "$f" | sed "s/^description:[[:space:]]*//;s/^[\"']//;s/[\"'][[:space:]]*\$//")"
    n=${#d}
    if ((n < 50 || n > 160)); then echo "$n chars: $f"; fi
  done)"
  if [[ -n $bad ]]; then
    echo "error: posts whose front-matter 'description:' is outside 50-160 characters were found in _posts/:" >&2
    printf '       %s\n' "$bad" >&2
    echo "       Keep descriptions between 50 and 160 characters so search engines show them uncut." >&2
    exit 1
  fi
  echo "description-coverage: all $_posts_total posts have a front-matter description of 50-160 characters (rule: grep -L '^description:' \$(find _posts -name '*.md'), plus length check)"
}

main() {
  preflight
  collect_posts
  check_tag_case_duplicates
  check_post_descriptions
  report_image_coverage
  report_alt_coverage

  # clean up
  if [[ -d $SITE_DIR ]]; then
    rm -rf "$SITE_DIR"
  fi

  read_baseurl

  # build
  JEKYLL_ENV=production bundle exec jekyll b \
    -d "$SITE_DIR$_baseurl" -c "$_config"

  # test
  bundle exec htmlproofer "$SITE_DIR" \
    --disable-external \
    --ignore-urls "/^http:\/\/127.0.0.1/,/^http:\/\/0.0.0.0/,/^http:\/\/localhost/"
}

while (($#)); do
  opt="$1"
  case $opt in
  -c | --config)
    _config="$2"
    shift
    shift
    ;;
  -h | --help)
    help
    exit 0
    ;;
  *)
    # unknown option
    help
    exit 1
    ;;
  esac
done

main
