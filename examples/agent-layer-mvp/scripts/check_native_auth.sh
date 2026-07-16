#!/usr/bin/env bash
set -eu

if [ -n "${GITHUB_TOKEN:-}" ] || [ -n "${GH_TOKEN:-}" ]; then
  echo "error: environment GitHub tokens must be unset; use gh's native credential-store login" >&2
  exit 1
fi

command -v gh >/dev/null || {
  echo "error: gh is required; install GitHub CLI and run 'gh auth login'" >&2
  exit 127
}

gh auth status >/dev/null 2>&1
