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
  _posts="$(find _posts -name '*.md' ! -name README.md | sort)"
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
  local pinned_ruby
  pinned_ruby="$(tr -d '[:space:]' <.ruby-version 2>/dev/null || echo 'unknown')"

  if ! command -v bundle >/dev/null 2>&1; then
    # Scheduled runs and hooks often start with a bare PATH (no mise shims), so
    # 'bundle' is missing even though mise has the pinned Ruby installed. Re-exec
    # once under mise rather than failing with "command not found" (exit 127).
    if [[ -z ${TEST_SH_REEXEC:-} ]] && command -v mise >/dev/null 2>&1 \
      && mise exec "ruby@$pinned_ruby" -- bundle -v >/dev/null 2>&1; then
      echo "note: 'bundle' not on PATH; re-running under mise ruby@$pinned_ruby (.ruby-version)." >&2
      TEST_SH_REEXEC=1 exec mise exec "ruby@$pinned_ruby" -- bash "$0" ${_orig_args[@]+"${_orig_args[@]}"}
    fi
    echo "error: 'bundle' not found on PATH." >&2
    echo "       Activate the pinned toolchain (e.g. 'mise exec -- bash tools/test.sh') and try again." >&2
    exit 1
  fi

  # Fail fast when the Ruby on PATH is not the pinned one. Under `set -e` the
  # silenced `bundle install --local` below otherwise exits 7 with no output when
  # a global Ruby (e.g. Homebrew 4.x) shadows the pinned 3.3.5, and the gem-set
  # diagnostic further down is never reached.
  local found_ruby
  found_ruby="$(ruby -e 'print RUBY_VERSION' 2>/dev/null || echo 'none')"
  if [[ $found_ruby != "$pinned_ruby" ]]; then
    # The scheduler and most callers run `bash tools/test.sh` with a bare PATH.
    # When mise has the pinned Ruby installed, re-exec once under it instead of
    # asking a human to retype the command (guarded so a wrong re-exec cannot loop).
    if [[ -z ${TEST_SH_REEXEC:-} ]] && command -v mise >/dev/null 2>&1 \
      && mise exec "ruby@$pinned_ruby" -- ruby -e 'exit 0' >/dev/null 2>&1; then
      echo "note: ruby on PATH is $found_ruby; re-running under mise ruby@$pinned_ruby (.ruby-version)." >&2
      TEST_SH_REEXEC=1 exec mise exec "ruby@$pinned_ruby" -- bash "$0" ${_orig_args[@]+"${_orig_args[@]}"}
    fi
    echo "error: ruby on PATH is $found_ruby ($(command -v ruby 2>/dev/null || echo 'not found')) but .ruby-version pins $pinned_ruby." >&2
    echo "       Run 'mise exec ruby@$pinned_ruby -- bash tools/test.sh' so bundle uses the pinned Ruby." >&2
    exit 1
  fi

  # Recover a stale-but-cached gem set without touching the network or the lockfile.
  bundle check >/dev/null 2>&1 || bundle install --local >/dev/null 2>&1

  if ! bundle exec ruby -e 'exit 0' >/dev/null 2>&1; then
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

# Fail when two posts use the same category with different letter case (e.g. "Drawio"
# vs "drawio", fixed in a97a525): Jekyll would then emit a "Conflict:" line buried in the build
# output and silently drop one category page. Reads every front-matter style used in
# _posts: space-separated (`categories: a b`), inline list (`categories: [a, b]`) and
# multi-line YAML list (`categories:` followed by `  - a` lines). Scans every post
# recursively (_posts/AI, _posts/Beginner, ... too), not just _posts/*.md.
check_category_case_duplicates() {
  local categories dupes
  categories="$(awk '
    FNR == 1 { fm = 0; in_categories = 0 }
    /^---[[:space:]]*$/ { fm++; in_categories = 0; next }
    fm != 1 { next }
    in_categories && /^[[:space:]]*-[[:space:]]+/ {
      sub(/^[[:space:]]*-[[:space:]]+/, ""); gsub(/["'"'"']/, ""); sub(/[[:space:]]+$/, "")
      if ($0 != "") print $0
      next
    }
    { in_categories = 0 }
    /^categories:/ {
      sub(/^categories:[[:space:]]*/, "")
      if ($0 == "") { in_categories = 1; next }
      gsub(/[][,"'"'"']/, " ")
      for (i = 1; i <= NF; i++) print $i
    }
  ' $_posts | sort -u)"

  dupes="$(printf '%s\n' "$categories" | awk '{ k = tolower($0); if (k in seen) print seen[k] " / " $0; else seen[k] = $0 }')"

  if [[ -n $dupes ]]; then
    echo "error: categories that differ only by letter case were found in _posts/:" >&2
    printf '       %s\n' "$dupes" >&2
    echo "       Use one spelling per category so Jekyll does not drop a category page with a 'Conflict:' warning." >&2
    exit 1
  fi
  echo "category-case-duplicates: 0 case-variant category collisions across $(printf '%s\n' "$categories" | grep -c .) distinct categories in $_posts_total posts (rule: categories equal under tolower() but spelled differently)"
}

# Report (and ratchet) tag synonym clusters: posts tagged ".NET", ".NET7", ".NET8" or
# "dotnet8" never show up on the "dotnet" tag page, so readers browsing one tag miss the
# others. Each line in TAG_SYNONYM_GROUPS is "canonical variant variant ..."; the check
# counts posts that use a non-canonical variant and fails when that number grows past
# TAG_SYNONYM_ALLOWED (the count at the time the check was added), so new posts must use
# the canonical tag while old posts can be migrated one at a time by lowering the cap.
TAG_SYNONYM_GROUPS='dotnet .NET .NET7 .NET8 dotnet8 net net8;csharp c# C# CSharp;azure-devops AzureDevOps azuredevops;software-engineering software-engineer'
TAG_SYNONYM_ALLOWED=0
check_tag_synonym_groups() {
  local hits count
  hits="$(awk -v groups="$TAG_SYNONYM_GROUPS" '
    BEGIN {
      n = split(groups, lines, ";")
      for (l = 1; l <= n; l++) {
        m = split(lines[l], w, " ")
        for (i = 2; i <= m; i++) canon[w[i]] = w[1]
      }
    }
    FNR == 1 { fm = 0; in_tags = 0 }
    /^---[[:space:]]*$/ { fm++; in_tags = 0; next }
    fm != 1 { next }
    in_tags && /^[[:space:]]*-[[:space:]]+/ {
      sub(/^[[:space:]]*-[[:space:]]+/, ""); gsub(/["'"'"']/, ""); sub(/[[:space:]]+$/, "")
      if ($0 in canon) print FILENAME ": " $0 " -> " canon[$0]
      next
    }
    { in_tags = 0 }
    /^tags:/ {
      sub(/^tags:[[:space:]]*/, "")
      if ($0 == "") { in_tags = 1; next }
      gsub(/[][,"'"'"']/, " ")
      for (i = 1; i <= NF; i++) if ($i in canon) print FILENAME ": " $i " -> " canon[$i]
    }
  ' $_posts | sort)"
  count="$(printf '%s\n' "$hits" | grep -c . || true)"

  if ((count > TAG_SYNONYM_ALLOWED)); then
    echo "error: $count post tags use a synonym of a canonical tag (allowed: $TAG_SYNONYM_ALLOWED):" >&2
    printf '       %s\n' "$hits" >&2
    echo "       Use the canonical tag (left of the arrow) so the post lands on the same tag page as its siblings." >&2
    exit 1
  fi
  echo "tag-synonym-groups: $count/$TAG_SYNONYM_ALLOWED post tags still use a non-canonical synonym across $(printf '%s' "$TAG_SYNONYM_GROUPS" | tr ';' '\n' | grep -c .) groups in $_posts_total posts (lower TAG_SYNONYM_ALLOWED after migrating a post)"
  if [[ -n $hits ]]; then printf '  %s\n' "$hits"; fi
}

# Report image coverage of _posts so image-coverage cards can cite one number.
# A post counts as having an image when it has a front-matter `image:` key, a
# markdown `![` image or an `<img` tag; the denominator is every `*.md` under
# _posts including subfolders (same rule as
# `grep -L -E '^image:|!\[|<img' $(find _posts -name '*.md' ! -name README.md)`). Lists the posts
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
  echo "image-coverage: $count/$_posts_total posts without image (rule: grep -L -E '^image:|!\\[|<img' \$(find _posts -name '*.md' ! -name README.md))"
  if [[ -n $without ]]; then
    printf '  %s\n' $without
  fi
}

# Report alt-text coverage of post header images so alt-text cards can cite one
# number. A post counts as covered when its front-matter `image:` block has a
# nested `alt:` key (Chirpy renders it as the header <img alt>); screen readers
# and image search otherwise get an empty alt. Denominator: posts with an
# `image:` front-matter key (subfolders included). Lists the posts still lacking
# alt text and fails the build when any post lacks it.
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
  # Fail, not just report: the count reached 0/148 (it was 28/42 missing on
  # 2026-09-30), so any post with a header image and no nested `alt:` is a
  # regression that leaves screen-reader users with an unlabelled image.
  if ((count > 0)); then
    echo "error: $count/$with_image_total posts have a front-matter image but no alt text (rule: 'image:' block without a nested 'alt:' key; allowed: 0):" >&2
    printf '       %s\n' $without >&2
    echo "       Add 'alt: <what the image shows>' under the 'image:' block so screen readers and image search get a description." >&2
    exit 1
  fi
  echo "alt-coverage: $count/$with_image_total posts with a front-matter image but no alt text (rule: 'image:' block without a nested 'alt:' key; any >0 fails)"

  # Duplicate coverage: the same alt text repeated verbatim across more than one
  # post is generic/copy-pasted and tells screen readers and image search nothing
  # about this post (regression fixed in 3853af3). Compares the trimmed value of
  # the nested `alt:` key, case-insensitively, and lists each repeated value with
  # the posts that share it.
  local dupes
  dupes="$(for f in $with_image; do
    awk -v file="$f" '
      FNR == 1 { fm = 0; in_image = 0 }
      /^---[[:space:]]*$/ { fm++; in_image = 0; next }
      fm != 1 { next }
      /^image:/ { in_image = 1; next }
      /^[^[:space:]]/ { in_image = 0 }
      in_image && /^[[:space:]]+alt:[[:space:]]*[^[:space:]]/ {
        v = $0; sub(/^[[:space:]]+alt:[[:space:]]*/, "", v)
        sub(/[[:space:]]+$/, "", v); gsub(/^["'"'"']|["'"'"']$/, "", v)
        print tolower(v) "\t" file
      }
    ' "$f"
  done | sort | awk -F'\t' '
    { n[$1]++; files[$1] = files[$1] "\n    " $2 }
    END { for (k in n) if (n[k] > 1) print "  \"" k "\" (" n[k] " posts)" files[k] }
  ')"
  local dupe_count=0
  if [[ -n $dupes ]]; then
    dupe_count="$(printf '%s\n' "$dupes" | grep -c '^  "' || true)"
  fi
  echo "alt-duplicate-coverage: $dupe_count alt text values repeated verbatim across more than one post (rule: identical trimmed, case-folded nested 'alt:' value in >1 post)"
  if [[ -n $dupes ]]; then
    printf '%s\n' "$dupes"
  fi
}

# Report inline-image coverage of post bodies so "publish more posts with
# screenshots" has a numerator/denominator. A post counts as covered when its
# body (after the closing front-matter '---') contains at least one Markdown
# image `![...](...)`; a header `image:` alone does not count. Lists the posts
# with no inline image. Informational only: never fails the build.
report_body_image_coverage() {
  local without
  without="$(for f in $_posts; do
    awk '
      FNR == 1 { fm = 0; found = 0 }
      /^---[[:space:]]*$/ && fm < 2 { fm++; next }
      fm == 2 && /!\[.*\]\(/ { found = 1 }
      END { exit found ? 0 : 1 }
    ' "$f" || echo "$f"
  done)"
  local count=0
  if [[ -n $without ]]; then
    count="$(printf '%s\n' "$without" | wc -l | tr -d ' ')"
  fi
  echo "body-image-coverage: $count/$_posts_total posts without an inline ![...] image in the body (rule: no Markdown image after the front matter)"
  if [[ -n $without ]]; then
    printf '  %s\n' $without
  fi
}

# Fail when a post references an image that does not exist in the repo. Covers
# every Markdown image `![...](path)` in the body and every front-matter `image:`
# path (inline `image: /x.webp` or a nested `path:` key under `image:`). Paths
# starting with `/` or `assets/` are resolved against the repo root; other paths
# (external URLs, relative) are skipped. A broken path renders as a missing
# header or an empty box with alt text, so readers lose the screenshot the post
# was written around. Hard fail: exits non-zero listing post -> missing path.
report_image_link_coverage() {
  local broken
  broken="$(for f in $_posts; do
    awk -v file="$f" '
      FNR == 1 { fm = 0; in_image = 0 }
      /^---[[:space:]]*$/ && fm < 2 { fm++; in_image = 0; next }
      fm == 1 && /^image:[[:space:]]*[^[:space:]]/ {
        v = $0; sub(/^image:[[:space:]]*/, "", v); emit(v); next
      }
      fm == 1 && /^image:[[:space:]]*$/ { in_image = 1; next }
      fm == 1 && /^[^[:space:]]/ { in_image = 0 }
      fm == 1 && in_image && /^[[:space:]]+path:[[:space:]]*[^[:space:]]/ {
        v = $0; sub(/^[[:space:]]+path:[[:space:]]*/, "", v); emit(v)
      }
      fm == 2 {
        line = $0
        while (match(line, /!\[[^]]*\]\([^)]*\)/)) {
          img = substr(line, RSTART, RLENGTH)
          line = substr(line, RSTART + RLENGTH)
          sub(/^!\[[^]]*\]\(/, "", img); sub(/\)$/, "", img)
          sub(/[[:space:]].*$/, "", img)
          emit(img)
        }
      }
      function emit(v) {
        sub(/[[:space:]]+$/, "", v); gsub(/^["\x27]|["\x27]$/, "", v)
        if (v ~ /^\// || v ~ /^assets\//) print file "\t" v
      }
    ' "$f"
  done | while IFS="$(printf '\t')" read -r post path; do
    rel="${path#/}"
    if [[ ! -f "./$rel" ]]; then
      echo "$post -> $path"
    fi
  done)"
  local count=0
  if [[ -n $broken ]]; then
    count="$(printf '%s\n' "$broken" | wc -l | tr -d ' ')"
  fi
  echo "image-link-coverage: $count/$_posts_total broken (rule: every '![...](path)' and front-matter 'image:'/'path:' value starting with / or assets/ must exist as a file under the repo root)"
  if [[ -n $broken ]]; then
    echo "error: $count post image path(s) point at files that do not exist:" >&2
    printf '       %s\n' "$broken" >&2
    echo "       Fix the path or add the image under assets/ so the post renders its screenshot." >&2
    exit 1
  fi
}

# Fail when a post has no front-matter `description:` key. jekyll-seo-tag and the
# Atom feed fall back to the generic site description otherwise, so every post
# would show the same search snippet. Same rule as
# `grep -L "^description:" $(find _posts -name '*.md' ! -name README.md)` (subfolders included).
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
  echo "description-coverage: all $_posts_total posts have a front-matter description of 50-160 characters (rule: grep -L '^description:' \$(find _posts -name '*.md' ! -name README.md), plus length check)"
}

# Fail when a post under _posts/<Folder>/ has no front-matter `categories` value
# containing the lowercased folder name (e.g. _posts/Automation/x.md must list
# `automation`). The categories/ pages are keyed on these values, so a post whose
# categories are unrelated to its folder drifts off the category page its folder
# promises; this was previously silent. Reads the three styles used in _posts:
# space-separated (`categories: a b`), inline list (`categories: [a, b]`) and
# multi-line YAML list. Posts directly under _posts/ are not checked.
check_folder_categories() {
  local bad
  bad="$(for f in $_posts; do
    folder="${f#_posts/}"
    [[ $folder == */* ]] || continue
    folder="${folder%%/*}"
    want="$(printf '%s' "$folder" | tr '[:upper:]' '[:lower:]')"
    awk -v want="$want" '
      FNR == 1 { fm = 0; in_cat = 0; found = 0 }
      /^---[[:space:]]*$/ { fm++; in_cat = 0; next }
      fm != 1 { next }
      in_cat && /^[[:space:]]*-[[:space:]]+/ {
        sub(/^[[:space:]]*-[[:space:]]+/, ""); gsub(/["'"'"']/, ""); sub(/[[:space:]]+$/, "")
        if (tolower($0) == want) found = 1
        next
      }
      { in_cat = 0 }
      /^categories:/ {
        sub(/^categories:[[:space:]]*/, "")
        if ($0 == "") { in_cat = 1; next }
        gsub(/[][,"'"'"']/, " ")
        for (i = 1; i <= NF; i++) if (tolower($i) == want) found = 1
      }
      END { exit found ? 0 : 1 }
    ' "$f" || echo "$f (expected category: $want)"
  done)"
  if [[ -n $bad ]]; then
    echo "error: posts whose front-matter 'categories' does not contain their _posts/ folder name were found:" >&2
    printf '       %s\n' "$bad" >&2
    echo "       Add the lowercased folder name to 'categories' so the post appears on the category page its folder promises." >&2
    exit 1
  fi
  echo "folder-categories: every post under _posts/<Folder>/ lists its lowercased folder name in 'categories'"
}

# Fail when a post's filename date (_posts/**/YYYY-MM-DD-*.md) differs from its
# front-matter `date:` day. Jekyll takes the front-matter date for the permalink
# and for feed/home ordering, so a drifted filename makes the file list, the
# URL and the feed disagree about when a post was published (e.g. a 2024-05-23
# filename published under /posts/2024-05-22/...). Compares the first ten
# characters (YYYY-MM-DD) of both; posts without a `date:` key fall back to the
# filename in Jekyll and are not checked.
check_date_match() {
  local bad
  bad="$(for f in $_posts; do
    name="$(basename "$f")"
    file_date="${name:0:10}"
    fm_date="$(awk '
      FNR == 1 { fm = 0 }
      /^---[[:space:]]*$/ { fm++; next }
      fm != 1 { next }
      /^date:/ { sub(/^date:[[:space:]]*/, ""); gsub(/["'"'"']/, ""); print substr($0, 1, 10); exit }
    ' "$f")"
    [[ -n $fm_date ]] || continue
    if [[ $file_date != "$fm_date" ]]; then echo "$f (filename $file_date, front matter $fm_date)"; fi
  done)"
  if [[ -n $bad ]]; then
    echo "error: posts whose filename date differs from their front-matter 'date:' were found in _posts/:" >&2
    printf '       %s\n' "$bad" >&2
    echo "       Rename the file or fix 'date:' so the permalink, feed order and file list agree on the publish day." >&2
    exit 1
  fi
  echo "date-match-coverage: 0 mismatches between filename date and front-matter 'date:' across $_posts_total posts (rule: first 10 chars of basename equal YYYY-MM-DD of 'date:')"
}

# Fail when the backlog of future-dated posts grows past what readers can be
# expected to wait for. _config.yml sets future:false, so a post dated after
# today is invisible on the live site until its day arrives; a large or far-out
# backlog (we once found 44 posts scheduled up to two months ahead) means
# finished work sits unread. Uses the filename date (YYYY-MM-DD prefix), which
# check_date_match keeps equal to 'date:'. Read-only: it never rewrites dates.
# The cap and horizon may need revisiting once the backlog is compressed.
FUTURE_POST_CAP=10
FUTURE_POST_HORIZON_DAYS=14
check_future_backlog() {
  local today future count far
  today="$(date +%Y-%m-%d)"
  # "<days-ahead>\t<date>\t<file>" for every post dated strictly after today.
  future="$(for f in $_posts; do n="$(basename "$f")"; printf '%s\t%s\n' "${n:0:10}" "$f"; done | awk -F '\t' -v today="$today" '
    # Days since epoch for YYYY-MM-DD (proleptic Gregorian), no external date tool needed.
    function days(d,  y, m, dd, a, yy, mm) {
      y = substr(d, 1, 4) + 0; m = substr(d, 6, 2) + 0; dd = substr(d, 9, 2) + 0
      a = int((14 - m) / 12); yy = y + 4800 - a; mm = m + 12 * a - 3
      return dd + int((153 * mm + 2) / 5) + 365 * yy + int(yy / 4) - int(yy / 100) + int(yy / 400) - 32045
    }
    $1 ~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$/ && $1 > today { print days($1) - days(today) "\t" $1 "\t" $2 }
  ' | sort -n)"
  count="$(printf '%s' "$future" | grep -c . || true)"
  far="$(printf '%s\n' "$future" | awk -F '\t' -v max="$FUTURE_POST_HORIZON_DAYS" 'NF && $1 > max { print $3 " (dated " $2 ", " $1 " days ahead)" }')"
  if ((count > FUTURE_POST_CAP)); then
    echo "error: $count posts in _posts/ are dated after today ($today); the cap is $FUTURE_POST_CAP:" >&2
    printf '%s\n' "$future" | awk -F '\t' '{ print "       " $3 " (dated " $2 ", " $1 " days ahead)" }' >&2
    echo "       With future:false these posts are invisible to readers until their date. Publish or re-date them so the backlog stays at or under $FUTURE_POST_CAP." >&2
    exit 1
  fi
  if [[ -n $far ]]; then
    echo "error: posts in _posts/ are scheduled more than $FUTURE_POST_HORIZON_DAYS days after today ($today):" >&2
    printf '       %s\n' "$far" >&2
    echo "       With future:false a post this far out stays unread for weeks. Move 'date:' and the filename to within $FUTURE_POST_HORIZON_DAYS days." >&2
    exit 1
  fi
  echo "future-backlog: $count/$_posts_total posts dated after today $today, none more than $FUTURE_POST_HORIZON_DAYS days out (rule: at most $FUTURE_POST_CAP future posts, each within $FUTURE_POST_HORIZON_DAYS days)"
}

# Fail when two sidebar tabs (_tabs/*.md) share the same front-matter `order:`.
# Chirpy sorts the sidebar nav by `order`, so a collision (e.g. All Posts and
# About both at order: 5) silently reorders the nav by file name instead of the
# intended position. Tabs without an `order:` key are not checked.
check_tab_order_unique() {
  local bad
  bad="$(for f in _tabs/*.md; do
    [[ -f $f ]] || continue
    awk -v f="$f" '
      FNR == 1 { fm = 0 }
      /^---[[:space:]]*$/ { fm++; next }
      fm != 1 { next }
      /^order:/ { sub(/^order:[[:space:]]*/, ""); gsub(/["'"'"'[:space:]]/, ""); if ($0 != "") print $0 "\t" f; exit }
    ' "$f"
  done | sort -t "$(printf '\t')" -k1,1n -k2,2 | awk -F "\t" '
    $1 == prev { print "order: " $1 " shared by " prevf " and " $2 }
    { prev = $1; prevf = $2 }
  ')"
  if [[ -n $bad ]]; then
    echo "error: _tabs/*.md files with a duplicate front-matter 'order:' value were found:" >&2
    printf '       %s\n' "$bad" >&2
    echo "       Give each tab a distinct 'order:' so the sidebar nav keeps its intended position." >&2
    exit 1
  fi
  echo "tab-order-coverage: all _tabs/*.md 'order:' values are unique (rule: no two tabs share the same front-matter 'order:')"
}

# Report how many posts (all categories) lack a "## Related" footer linking to
# related posts, so readers finishing any post are offered the next one.
# Reports a count rather than failing so the number can drop toward 0 while
# new posts land. Also reports the per-folder breakdown so a regression in one
# category stands out.
report_ai_related_coverage() {
  local all_posts total missing count dir dtotal dmissing
  all_posts="$(find _posts -name '*.md' ! -name README.md | sort)"
  total="$(printf '%s\n' "$all_posts" | grep -c .)"
  missing="$(grep -L -E '^## Related' $all_posts || true)"
  count="$(printf '%s\n' "$missing" | grep -c . || true)"
  if [[ -n $missing ]]; then printf '       %s\n' $missing; fi
  for dir in _posts $(find _posts -mindepth 1 -type d | sort); do
    dtotal="$(find "$dir" -maxdepth 1 -name '*.md' ! -name README.md | grep -c . || true)"
    [[ $dtotal -eq 0 ]] && continue
    dmissing="$(find "$dir" -maxdepth 1 -name '*.md' ! -name README.md -print0 | xargs -0 grep -L -E '^## Related' | grep -c . || true)"
    echo "       $dir: $dmissing/$dtotal without '## Related'"
  done
  echo "ai-related-coverage: $count/$total _posts posts without a '## Related' heading (rule: grep -L -E '^## Related' \$(find _posts -name '*.md' ! -name README.md))"
}

# Fail when a `(/posts/<slug>/)` link under a post's "## Related" heading points
# at a slug no file in _posts produces. Posts are published at /posts/:title/
# (_config.yml), where :title is the filename with its YYYY-MM-DD- prefix and
# .md suffix stripped, so a typo or a renamed post leaves readers on a 404 that
# htmlproofer cannot see (it only checks links on pages that were built). Scans
# every line from "## Related" to the next "## " heading or end of file.
check_related_link_resolution() {
  local slugfile links bad count
  slugfile="$(mktemp)"
  for f in $_posts; do n="$(basename "$f" .md)"; echo "${n:11}"; done | sort -u > "$slugfile"
  # "<file>\t<slug>" for every Related link, then keep the ones not in slugfile.
  links="$(for f in $_posts; do
    awk -v file="$f" '
      /^## Related/ { in_rel = 1; next }
      /^## / { in_rel = 0 }
      in_rel {
        s = $0
        while (match(s, /\(\/posts\/[^)#?]+/)) {
          link = substr(s, RSTART + 8, RLENGTH - 8)
          sub(/\/$/, "", link)
          print file "\t" link
          s = substr(s, RSTART + RLENGTH)
        }
      }
    ' "$f"
  done | awk -F '\t' 'NR == FNR { ok[$0] = 1; next } !($2 in ok)' "$slugfile" -)"
  rm -f "$slugfile"
  bad="$(printf '%s\n' "$links" | cut -f1 | grep -c . || true)"
  count="$(printf '%s\n' "$links" | cut -f1 | sort -u | grep -c . || true)"
  if ((count > 0)); then
    echo "error: $count posts have $bad '## Related' links to /posts/<slug>/ that no file in _posts produces:" >&2
    printf '%s\n' "$links" | awk -F '\t' '{ print "       " $1 ": /posts/" $2 "/" }' >&2
    echo "       Point each link at an existing post slug (filename without its date prefix and .md) so readers do not land on a 404." >&2
    exit 1
  fi
  echo "related-link-resolution: $count/$_posts_total posts with unresolved Related links (rule: every (/posts/<slug>/) under '## Related' matches a _posts/**/YYYY-MM-DD-<slug>.md)"
}

# Fail when a post links to /posts/<slug>/ whose source post is dated after the
# referencing post (a forward "next in series" link). With future:false the
# target is not built until its publish day, so on every build before that day
# the earlier post ships a 404 and htmlproofer fails the whole build. Compares
# the YYYY-MM-DD filename prefixes of both posts; links to same-day or earlier
# posts are fine, and so are links to later posts that are already published
# (target date <= today): those were retro-fitted and both pages exist on every
# build. Scans every (/posts/<slug>/) link in the post body.
check_forward_links() {
  local datefile links bad count today
  today="$(date +%Y-%m-%d)"
  datefile="$(mktemp)"
  for f in $_posts; do n="$(basename "$f" .md)"; printf '%s\t%s\n' "${n:11}" "${n:0:10}"; done | sort -u > "$datefile"
  # "<file>\t<file-date>\t<slug>" for every /posts/ link, then keep those whose target is dated later.
  links="$(for f in $_posts; do
    n="$(basename "$f" .md)"
    awk -v file="$f" -v fdate="${n:0:10}" '
      FNR == 1 { fm = 0 }
      /^---[[:space:]]*$/ && fm < 2 { fm++; next }
      fm != 2 { next }
      {
        s = $0
        while (match(s, /\(\/posts\/[^)#?]+/)) {
          link = substr(s, RSTART + 8, RLENGTH - 8)
          sub(/\/$/, "", link)
          print file "\t" fdate "\t" link
          s = substr(s, RSTART + RLENGTH)
        }
      }
    ' "$f"
  done | awk -F '\t' -v today="$today" 'NR == FNR { d[$1] = $2; next } ($3 in d) && d[$3] > $2 && d[$3] > today { print $1 "\t" $3 "\t" d[$3] "\t" $2 }' "$datefile" -)"
  rm -f "$datefile"
  bad="$(printf '%s\n' "$links" | cut -f1 | grep -c . || true)"
  count="$(printf '%s\n' "$links" | cut -f1 | sort -u | grep -c . || true)"
  if ((count > 0)); then
    echo "error: $count posts have $bad links to /posts/<slug>/ whose target post is dated later than the referencing post:" >&2
    printf '%s\n' "$links" | awk -F '\t' '{ print "       " $1 " (" $4 "): /posts/" $2 "/ (target publish date " $3 ")" }' >&2
    printf '%s\n' "$links" | awk -F '\t' '{ print "       date-gated: add this link on or after " $3 " (/posts/" $2 "/ in " $1 ")" }' >&2
    echo "       With future:false the target is not built until its publish date, so the link is a 404 that fails htmlproofer." >&2
    echo "       This is a date gate, not a code defect: retrying before that date fails the same way." >&2
    echo "       Drop the link (plain text) until the target is published, or link from the later post back to the earlier one." >&2
    exit 1
  fi
  echo "forward-link-coverage: $count/$_posts_total posts linking to a not-yet-published later-dated /posts/<slug>/ (rule: no link whose target filename date is after both the referencing post and today $today)"
}

# A post dated today with a time-of-day later than the current clock (or a
# timezone offset that pushes it past now) is skipped by `future: false` in the
# production deploy: Jekyll logs "Skipping: <post> has a future date", exits 0,
# and the post silently does not appear on the live site even though the
# post-count signal moved. The main build below runs with --future (so link
# checks cover scheduled posts), which hides that warning; probe the production
# read without --future and fail when a post dated today is the one skipped.
check_today_not_future() {
  local today _skipped
  today="$(date +%Y-%m-%d)"
  _skipped="$(JEKYLL_ENV=production bundle exec ruby -e '
    require "jekyll"
    cfg = Jekyll.configuration("config" => ["_config.yml"])
    site = Jekyll::Site.new(cfg)
    site.reset
    site.read
  ' 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep 'has a future date' | grep -F "_posts/$today-" || true)"
  if [[ -n $_skipped ]]; then
    echo "ERROR: a post dated today ($today) is skipped as a future post by the production build (future: false), so it lands invisibly on the live site:" >&2
    printf '%s\n' "$_skipped" >&2
    echo "       Set the post's date/time (and +offset) to a moment that has already passed, or date it tomorrow to schedule it deliberately." >&2
    exit 1
  fi
  echo "today-not-future-coverage: 0 posts dated $today skipped as 'has a future date' by a production (no --future) read (rule: any >0 fails)"
}

main() {
  preflight
  collect_posts
  check_tag_case_duplicates
  check_category_case_duplicates
  check_tag_synonym_groups
  check_post_descriptions
  check_folder_categories
  check_date_match
  check_future_backlog
  check_tab_order_unique
  report_image_coverage
  report_image_link_coverage
  report_alt_coverage
  report_body_image_coverage
  report_ai_related_coverage
  check_related_link_resolution
  check_forward_links
  check_today_not_future

  # clean up
  if [[ -d $SITE_DIR ]]; then
    rm -rf "$SITE_DIR"
  fi

  read_baseurl

  # build
  # Capture the build log: Jekyll prints "Liquid Warning: Liquid syntax error ..."
  # for an unescaped `{{ ... }}` / `{% ... %}` in a post body, exits 0, and
  # silently drops that text from the rendered page, so readers see a sentence
  # with a hole in it. Fail the check so the author fixes it before merge.
  local _build_log
  _build_log=$(mktemp)
  local _build_rc=0
  # Build with --future so scheduled posts (dated after today, skipped by
  # future:false in production) are rendered too and htmlproofer checks their
  # links and images now, in CI, instead of on publish day.
  JEKYLL_ENV=production bundle exec jekyll b --future \
    -d "$SITE_DIR$_baseurl" -c "$_config" 2>&1 | tee "$_build_log" || _build_rc=${PIPESTATUS[0]}
  if ((_build_rc != 0)); then
    rm -f "$_build_log"
    exit "$_build_rc"
  fi
  if grep -q 'Liquid Warning' "$_build_log"; then
    echo "ERROR: jekyll build emitted Liquid Warning lines; the affected text is dropped from the rendered page:" >&2
    grep 'Liquid Warning' "$_build_log" | sed 's/\x1b\[[0-9;]*m//g' >&2
    echo "       Wrap literal {{ ... }} or {% ... %} in {% raw %}...{% endraw %} in the post source." >&2
    rm -f "$_build_log"
    exit 1
  fi
  # Jekyll also prints "Conflict: The following destination is shared by multiple
  # files." (exit 0) when two tag or category pages resolve to the same output
  # path; one page silently overwrites the other and that archive lists only
  # part of the posts. Fail so the colliding tag/category is fixed before merge.
  local _conflicts
  _conflicts="$(sed 's/\x1b\[[0-9;]*m//g' "$_build_log" | grep -c 'Conflict: The following destination is shared by multiple files' || true)"
  if ((_conflicts > 0)); then
    echo "ERROR: jekyll build emitted $_conflicts 'Conflict:' destination warning(s); one tag/category page silently overwrites another:" >&2
    sed 's/\x1b\[[0-9;]*m//g' "$_build_log" | grep -A 3 'Conflict: The following destination' >&2
    echo "       Use one spelling per tag/category so every archive page lists all its posts." >&2
    rm -f "$_build_log"
    exit 1
  fi
  echo "tag-conflict-coverage: $_conflicts 'Conflict: The following destination is shared by multiple files' warnings in the jekyll build log (rule: grep -c on the captured build output; any >0 fails)"
  rm -f "$_build_log"

  # test
  bundle exec htmlproofer "$SITE_DIR" \
    --disable-external \
    --ignore-urls "/^http:\/\/127.0.0.1/,/^http:\/\/0.0.0.0/,/^http:\/\/localhost/"

  # Second pass: external links in scheduled (future-dated) posts only. The
  # full-site pass above skips external URLs so CI stays fast and immune to the
  # whole back catalogue's link rot; the few posts that have not gone live yet
  # are still editable, so a dead outbound link there is caught before publish
  # day instead of by a reader afterwards. Posts are matched to their rendered
  # directory by the filename slug (permalink /posts/:title/). The site's own
  # URLs are skipped (a scheduled post's canonical link is a 404 until it goes
  # live, by definition) as are the bare font preconnect hosts, which answer 404
  # at their root.
  local _today _future_dirs=() _f _slug _dir
  _today="$(date +%F)"
  for _f in $_posts; do
    _slug="$(basename "$_f" .md)"
    if [[ ${_slug:0:10} > $_today ]]; then
      _dir="$SITE_DIR$_baseurl/posts/${_slug:11}"
      if [[ -d $_dir ]]; then
        _future_dirs+=("$_dir")
      else
        echo "WARNING: scheduled post $_f has no rendered page at $_dir; external links not checked" >&2
      fi
    fi
  done
  echo "future-external-links: ${#_future_dirs[@]} scheduled post page(s) checked with external links enabled (rule: posts dated after $_today, permalink /posts/:title/)"
  if ((${#_future_dirs[@]} > 0)); then
    bundle exec htmlproofer "${_future_dirs[@]}" \
      --root-dir "$SITE_DIR$_baseurl" \
      --no-check-external-hash \
      --ignore-status-codes "403,429,999" \
      --ignore-urls "/^http:\/\/127.0.0.1/,/^http:\/\/0.0.0.0/,/^http:\/\/localhost/,/^https:\/\/blogs\.lamplitlabs\.com\//,/^https:\/\/tools\.lamplitlabs\.com\//,/^https:\/\/fonts\.(googleapis|gstatic)\.com\/?$/"
  fi
}

# Keep the original arguments so preflight can re-exec with them intact.
_orig_args=("$@")

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
