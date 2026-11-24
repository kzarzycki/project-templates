#!/bin/bash
# claude-cloud setup script (incubating: not proven yet). `mise run claude-cloud:setup` makes it the
# setup script of your claude-cloud environment. It runs once per environment snapshot, before the
# environment's variables and network secrets apply, so it installs tools and leaves nothing running.
# A failed step is logged as `FAILED: <step>` and the script goes on: it always exits 0, since a
# failing setup script blocks the session from starting.
# The cloud network policy blocks mise's own installer host; npm's registry is reachable, so mise comes from npm.
# ponytail: no per-tool prefetching here; it is tracked in kzarzycki/agent-skills#962.

step() {
  local name=$1
  shift
  echo "==> $name"
  "$@" || echo "FAILED: $name"
}

# shellcheck disable=SC2329  # called through step
install_mise() { command -v mise >/dev/null || npm install -g -s @jdxcode/mise; }
# shellcheck disable=SC2329
trust_and_install() { mise trust -q . && mise install; }

step "install mise" install_mise
export PATH="$HOME/.local/bin:$PATH"
repo=$(for d in /home/user/*/; do [ -f "$d/mise.toml" ] && echo "$d" && break; done)
if [ -n "$repo" ]; then
  cd "$repo" || echo "FAILED: cd repo"
  step "mise prefer_offline" mise settings set prefer_offline true
  step "mise install" trust_and_install
fi

# Docker, where the image ships it. sudo drops the session's proxy variables, and a dockerd started
# without them pulls past the proxy, so a private pull fails `unauthorized` even with a network secret.
if command -v dockerd >/dev/null && ! docker info >/dev/null 2>&1; then
  (setsid sudo -n env HTTPS_PROXY="${HTTPS_PROXY:-}" HTTP_PROXY="${HTTP_PROXY:-${HTTPS_PROXY:-}}" NO_PROXY="${NO_PROXY:-}" \
    dockerd >/tmp/dockerd.log 2>&1 </dev/null &)
fi
exit 0
