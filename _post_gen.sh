#!/usr/bin/env bash
# Post-generation tasks, run by copier from the destination dir. Idempotent:
# every step guards itself so `copier update` re-runs it harmlessly.
#   $1 = project_type (e.g. software/python)   $2 = language (python|node|"")
set -euo pipefail

project_type="${1:-}"
language="${2:-}"
log() { printf '  → %s\n' "$1"; }

# Resolve the toolchain: fixed-language leaves imply it; ai/mcp carries $language.
case "$project_type" in
  software/python) language=python ;;
  software/node)   language=node ;;
  software/java)   language=java ;;
esac

# 1. git init (skip if already a repo). fresh_repo distinguishes scaffolding into
#    a new dir from adopting the template onto an existing repo — the force-install
#    and auto-commit below are only safe on a repo we created.
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  git init -q
  git branch -m main 2>/dev/null || true
  fresh_repo=true
  log "git initialised (branch: main)"
else
  fresh_repo=false
  log "git already initialised — adoption mode"
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
  java)
    # Gradle resolves on first build; nothing to pre-install here.
    log "java project — run ./gradlew build when ready"
    ;;
esac

# 3. install pre-commit hooks (skip if pre-commit absent). On a fresh repo, force
#    (-f): a global git template that seeds .git/hooks would otherwise drop a plain
#    install into "migration mode" and abort every later commit. On adoption, NEVER
#    force — that would clobber a hook the existing repo already relies on; a plain
#    install migrates any existing hook to .legacy instead.
if command -v pre-commit >/dev/null 2>&1; then
  if [ "$fresh_repo" = true ]; then
    pre-commit install -f --install-hooks >/dev/null 2>&1 && log "pre-commit installed" || true
  else
    pre-commit install --install-hooks >/dev/null 2>&1 && log "pre-commit installed (existing hooks preserved)" || true
  fi
else
  log "pre-commit not found — run 'uv tool install pre-commit && pre-commit install'"
fi

# 4. first commit — ONLY on a repo we created. On adoption we never auto-commit:
#    a `git add -A` here would sweep the existing repo's own files (tracked or not,
#    even when it has no commits yet) into a "scaffold" commit. Run hooks first so
#    any file they rewrite (EOF/whitespace) is normalised, then re-stage — otherwise
#    the commit aborts on a hook that "modified files".
if [ "$fresh_repo" = true ] && [ "$(git rev-list --all --count 2>/dev/null || echo 0)" -eq 0 ]; then
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
  log "adoption / existing commits — skipped initial commit"
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
