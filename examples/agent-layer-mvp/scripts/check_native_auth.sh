#!/usr/bin/env bash
# Demonstration-only acceptance check for keyring-backed local gh auth.
# This is not a general policy: environment tokens are valid in CI, containers,
# ephemeral machines, and projects that choose them explicitly.
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
