#!/usr/bin/env bash
# Non-interactive front door to the Copier template. Resolves author/email/year
# from git config, then runs copier with everything supplied via --data so no
# prompt blocks. Extra `key=value` args are passed through to copier as --data.
#
# Usage:
#   bootstrap.sh --name my-tool --language python [--dest DIR] [key=value ...]
#
# Languages: python | node | content
set -euo pipefail

# Template source. Defaults to the published repo (a `gh:` URL so copier records
# a real ref and `copier update` works in generated projects). Override with
# BOOTSTRAP_TEMPLATE_SRC=. (or a local path) to test an unpushed checkout.
template="${BOOTSTRAP_TEMPLATE_SRC:-gh:kzarzycki/project-templates}"

name=""; language=""; dest=""
extra_data=()
while [ $# -gt 0 ]; do
  case "$1" in
    --name) name="$2"; shift 2 ;;
    --language) language="$2"; shift 2 ;;
    --dest) dest="$2"; shift 2 ;;
    *=*) extra_data+=("$1"); shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[ -n "$name" ] || { echo "error: --name is required" >&2; exit 2; }
[ -n "$language" ] || { echo "error: --language is required (python|node|content)" >&2; exit 2; }
[ -n "$dest" ] || dest="$name"

author="$(git config user.name 2>/dev/null || echo 'Your Name')"
email="$(git config user.email 2>/dev/null || echo 'you@example.com')"
year="$(date +%Y)"

command -v copier >/dev/null 2>&1 || { echo "error: copier not installed — 'uv tool install copier'" >&2; exit 1; }

data=(
  --data "project_name=$name"
  --data "language=$language"
  --data "author=$author"
  --data "email=$email"
  --data "year=$year"
)
for kv in "${extra_data[@]:-}"; do
  [ -n "$kv" ] && data+=(--data "$kv")
done

echo "Scaffolding '$name' ($language) → $dest"
copier copy --trust --defaults "${data[@]}" "$template" "$dest"
