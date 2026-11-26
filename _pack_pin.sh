#!/usr/bin/env bash
# The engineering pack's version in a generated project's apm.yml. The template names the pack with no
# ref (apm resolves that to the default branch, which moves); the project owns the ref from its first pin,
# and Renovate moves it. Run from the project root.
#   first                   Pin a ref-less pack line to the newest stable release tag (`<package>-vX.Y.Z`,
#                           no `-next`), read with `git ls-remote` from github.com/<owner>/<repo>. Called by
#                           _post_gen.sh at generation. Offline, or with no tag found, it changes nothing,
#                           says how to pin by hand and exits 0. A line that already has a ref is left alone,
#                           so a `copier update` re-running it never touches the project's pin.
#   strip|restore <pack>    Copier migration (copier.yml) for a project generated before the template stopped
#                           setting the ref. Without it the update's three-way merge deletes the project's
#                           ref, or conflicts with the one Renovate has since moved.
#                             strip   (before the merge) apm.yml names the pack with no ref, as the new
#                                     template renders it, so the merge sees the same change on both sides.
#                             restore (after the merge) the ref is read back from apm.yml as the project last
#                                     committed it. A pack entry that is not the plain two-line form is left
#                                     alone. Idempotent.
set -euo pipefail

mode="${1:?first|strip|restore}"
[ -f apm.yml ] || exit 0

if [ "$mode" = first ]; then
  pack=$(sed -n 's|^    - \([A-Za-z0-9_.-]*/[A-Za-z0-9_.-]*/[A-Za-z0-9_.-]*\)$|\1|p' apm.yml | head -1)
  [ -n "$pack" ] || exit 0
  package="${pack##*/}"
  tag=$(GIT_TERMINAL_PROMPT=0 git ls-remote --tags --refs "https://github.com/${pack%/*}" "refs/tags/$package-v*" 2>/dev/null \
    | sed 's|.*refs/tags/||' | grep -E "^$package-v[0-9]+\.[0-9]+\.[0-9]+$" | sort -V | tail -1 || true)
  if [ -z "$tag" ]; then
    echo "  → could not read $pack's release tags (offline?): apm.yml names it with no ref, which installs the default branch; add 'ref: $package-vX.Y.Z' under it" >&2
    exit 0
  fi
  awk -v pack="$pack" -v tag="$tag" '$0 == "    - " pack { print "    - git: " pack; print "      ref: " tag; next } { print }' apm.yml > apm.yml.new
  mv apm.yml.new apm.yml
  echo "  → pinned $pack to $tag"
  exit 0
fi

pack="${2:?the pack source}"

case "$mode" in
  strip)
    awk -v pack="$pack" '
      skip { skip = 0; if ($0 ~ /^      ref:/) next }
      $0 == "    - git: " pack { print "    - " pack; skip = 1; next }
      { print }
    ' apm.yml > apm.yml.new
    mv apm.yml.new apm.yml
    # Copier diffs the index, so the edit has to be staged to count.
    git add apm.yml 2>/dev/null || true
    ;;
  restore)
    ref=$(git show HEAD:apm.yml 2>/dev/null | awk -v pack="$pack" '
      held { if ($0 ~ /^      ref:/) { sub(/^      ref:[ \t]*/, ""); sub(/[ \t]+$/, ""); print; exit } held = 0 }
      $0 == "    - git: " pack { held = 1 }
    ') || true
    [ -n "$ref" ] || exit 0
    awk -v pack="$pack" -v ref="$ref" '
      skip { skip = 0; if ($0 ~ /^      ref:/) next }
      $0 == "    - " pack || $0 == "    - git: " pack { print "    - git: " pack; print "      ref: " ref; skip = 1; next }
      { print }
    ' apm.yml > apm.yml.new
    mv apm.yml.new apm.yml
    ;;
  *) echo "usage: $0 strip|restore <pack>" >&2; exit 2 ;;
esac
