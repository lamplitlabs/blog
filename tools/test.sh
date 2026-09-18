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
    echo "error: required gems are not available for this Ruby/bundler." >&2
    echo "       Run 'bundle install' (with the pinned Ruby active) and try again." >&2
    exit 1
  fi
}

# Fail when two posts use the same tag with different letter case (e.g. "Azurite"
# vs "azurite"): Jekyll would then emit a "Conflict:" line buried in the build
# output and silently drop one tag page. Reads every front-matter style used in
# _posts: space-separated (`tags: a b`), inline list (`tags: [a, b]`) and
# multi-line YAML list (`tags:` followed by `  - a` lines).
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
  ' _posts/*.md | sort -u)"

  dupes="$(printf '%s\n' "$tags" | awk '{ k = tolower($0); if (k in seen) print seen[k] " / " $0; else seen[k] = $0 }')"

  if [[ -n $dupes ]]; then
    echo "error: tags that differ only by letter case were found in _posts/:" >&2
    printf '       %s\n' "$dupes" >&2
    echo "       Use one spelling per tag so Jekyll does not drop a tag page with a 'Conflict:' warning." >&2
    exit 1
  fi
}

main() {
  preflight
  check_tag_case_duplicates

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
