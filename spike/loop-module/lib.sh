# Shared helpers for the spike scripts. Sourced, not run.
export GIT_AUTHOR_NAME=spike GIT_AUTHOR_EMAIL=spike@example.com GIT_COMMITTER_NAME=spike GIT_COMMITTER_EMAIL=spike@example.com
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# copier flags go after the subcommand; --trust is off (no tasks in these templates).
cp_() { local sub=$1; shift; copier "$sub" --defaults --skip-tasks --quiet "$@" 2>&1 | grep -v -i -E 'warn|^$' || true; }
# Publish a template folder as a tagged git repo (copier update needs tags).
publish() { # <src folder> <dest> <tag>
  rm -rf "$2"; mkdir -p "$2"; cp -r "$1"/. "$2"/
  (cd "$2" && git init -q && git add -A && git commit -qm "$3" && git tag "$3")
}
retag() { # <template repo> <src folder> <tag>: replace the content, commit, tag
  (cd "$1" && git rm -rqf . && cp -r "$2"/. . && git add -A && git commit -qm "$3" && git tag "$3")
}
commit_all() { (cd "$1" && git add -A && git commit -qm "$2" --allow-empty); }
step() { printf '\n=== %s ===\n' "$*"; }
