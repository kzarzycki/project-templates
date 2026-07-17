---
paths:
  - "**"
---

Demonstration-only instruction: the acceptance tests use this behavior. Project
instructions should describe the project's actual agent behavior.

# agent-layer-mvp

This repository demonstrates project-owned instructions, MCP configuration,
machine bindings, and native CLI authentication for Claude Code and Codex.

When asked to verify the agent layer, call the `agent-layer-canary` MCP server's
`probe` tool and report its fixed marker.
