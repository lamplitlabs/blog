#!/usr/bin/env bash
# Shell + jq policy gate of the tool-call argument differential bench.
#   bash gate_jq.sh <payloads.b64>
# The pattern many hook scripts use: p=$(jq -r .path <<<"$args"), then a case
# glob for the prefix and a substring test for "..". Prints one JSON line per
# payload: {"allow":bool,"path":string|null,"err":string}.
set -u
while IFS= read -r line; do
  args="$(printf '%s' "$line" | base64 -D 2>/dev/null || printf '%s' "$line" | base64 -d)"
  if ! p="$(printf '%s' "$args" | jq -r '.path // empty' 2>/tmp/gate_jq_err.$$)"; then
    jq -cn --arg e "$(head -c 200 /tmp/gate_jq_err.$$)" '{allow:false,path:null,err:$e}'
    continue
  fi
  allow=false
  case "$p" in
    workspace/*) [[ "/$p/" == */../* ]] || allow=true ;;
  esac
  if [[ -z "$p" ]]; then
    jq -cn '{allow:false,path:null,err:""}'
  else
    jq -cn --arg p "$p" --argjson a "$allow" '{allow:$a,path:$p,err:""}'
  fi
done <"$1"
rm -f /tmp/gate_jq_err.$$
