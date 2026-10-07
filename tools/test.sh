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
  all_posts="$(find _posts -name '*.md' | sort)"
  total="$(printf '%s\n' "$all_posts" | grep -c .)"
  missing="$(grep -L -E '^## Related' $all_posts || true)"
  count="$(printf '%s\n' "$missing" | grep -c . || true)"
  if [[ -n $missing ]]; then printf '       %s\n' $missing; fi
  for dir in _posts $(find _posts -mindepth 1 -type d | sort); do
    dtotal="$(find "$dir" -maxdepth 1 -name '*.md' | grep -c . || true)"
    [[ $dtotal -eq 0 ]] && continue
    dmissing="$(find "$dir" -maxdepth 1 -name '*.md' -print0 | xargs -0 grep -L -E '^## Related' | grep -c . || true)"
    echo "       $dir: $dmissing/$dtotal without '## Related'"
  done
  echo "ai-related-coverage: $count/$total _posts posts without a '## Related' heading (rule: grep -L -E '^## Related' \$(find _posts -name '*.md'))"
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
    printf '%s\n' "$links" | awk -F '\t' '{ print "       " $1 " (" $4 "): /posts/" $2 "/ (" $3 ")" }' >&2
    echo "       With future:false the target is not built until its date, so the link is a 404 that fails htmlproofer." >&2
    echo "       Drop the link (plain text) until the target is published, or link from the later post back to the earlier one." >&2
    exit 1
  fi
  echo "forward-link-coverage: $count/$_posts_total posts linking to a not-yet-published later-dated /posts/<slug>/ (rule: no link whose target filename date is after both the referencing post and today $today)"
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
  check_tab_order_unique
  report_image_coverage
  report_alt_coverage
  report_body_image_coverage
  report_ai_related_coverage
  check_related_link_resolution
  check_forward_links

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
  JEKYLL_ENV=production bundle exec jekyll b \
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
  rm -f "$_build_log"

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
