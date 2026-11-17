#!/bin/bash
# claude-cloud setup script (incubating: not proven yet). `mise run claude-cloud:setup` makes it the
# setup script of your claude-cloud environment. It runs once per environment snapshot, before the
# environment's variables and network secrets apply, so it installs tools and leaves nothing running.
set -x
command -v mise >/dev/null || curl -fsSL https://mise.run | sh
export PATH="$HOME/.local/bin:$PATH"
repo=$(for d in /home/user/*/; do [ -f "$d/mise.toml" ] && echo "$d" && break; done)
if [ -n "$repo" ]; then
  cd "$repo" && mise trust -q . && mise install
fi

# Docker, where the image ships it. sudo drops the session's proxy variables, and a dockerd started
# without them pulls past the proxy, so a private pull fails `unauthorized` even with a network secret.
if command -v dockerd >/dev/null && ! docker info >/dev/null 2>&1; then
  (setsid sudo -n env HTTPS_PROXY="${HTTPS_PROXY:-}" HTTP_PROXY="${HTTP_PROXY:-${HTTPS_PROXY:-}}" NO_PROXY="${NO_PROXY:-}" \
    dockerd >/tmp/dockerd.log 2>&1 </dev/null &)
fi
exit 0
