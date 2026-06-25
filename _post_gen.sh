#!/usr/bin/env bash
# Post-generation tasks, run by copier from the destination dir. Idempotent:
# every step guards itself so `copier update` re-runs it harmlessly.
#   $1 = language (python|node|content)   $2 = include_release_please (True|False)
set -euo pipefail

language="${1:-}"
log() { printf '  → %s\n' "$1"; }

# 1. git init (skip if already a repo)
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  git init -q
  git branch -m main 2>/dev/null || true
  log "git initialised (branch: main)"
else
  log "git already initialised — skipped"
fi

# 2. install dependencies per pack (best-effort; never fail the scaffold)
case "$language" in
  python)
    if command -v uv >/dev/null 2>&1; then
      uv sync >/dev/null 2>&1 && log "uv sync" || log "uv sync skipped (will run on first use)"
    fi
    ;;
  node)
    if command -v npm >/dev/null 2>&1; then
      npm install >/dev/null 2>&1 && log "npm install" || log "npm install skipped"
    fi
    ;;
esac

# 3. install pre-commit hooks (skip if pre-commit absent)
if command -v pre-commit >/dev/null 2>&1; then
  pre-commit install >/dev/null 2>&1 && log "pre-commit installed" || true
else
  log "pre-commit not found — run 'uv tool install pre-commit && pre-commit install'"
fi

# 4. first commit (skip if any commit already exists). Run hooks first so any
#    file they rewrite (EOF/whitespace) is normalised before we commit, then
#    re-stage — otherwise the commit aborts on a hook that "modified files".
if [ "$(git rev-list --all --count 2>/dev/null || echo 0)" -eq 0 ]; then
  git add -A
  if command -v pre-commit >/dev/null 2>&1; then
    pre-commit run --all-files >/dev/null 2>&1 || true
    git add -A
  fi
  if git commit -q -m "chore: scaffold project

Co-Authored-By: Claude <noreply@anthropic.com>"; then
    log "initial commit created"
  else
    log "commit failed — files are staged, commit manually"
  fi
else
  log "commits already present — skipped initial commit"
fi

# 5. optional GitHub remote — only on an interactive TTY, only if no remote yet,
#    and only after explicit confirmation. Non-interactive runs skip silently.
if [ -t 0 ] && command -v gh >/dev/null 2>&1 && ! git remote get-url origin >/dev/null 2>&1; then
  printf '\nCreate a GitHub repo and push? [y/N] '
  read -r reply
  case "$reply" in
    [yY]*)
      gh repo create --source . --private --push && log "pushed to GitHub" \
        || log "gh repo create failed — local commit is intact"
      ;;
    *) log "skipped GitHub remote — local commit is intact" ;;
  esac
fi

printf '\n✓ Project ready.\n'
