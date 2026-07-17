# agent-layer-mvp

This generated project shows the boundary between Copier scaffolding and
project-owned agent configuration for Claude Code and Codex.

Copier created `apm.yml`, `fnox.toml`, the `.apm/` instruction seed, and the
`agent-*` tasks in `mise.toml`. This project then added its canary instruction,
local stdio MCP server, synthetic fnox profile, and native GitHub CLI auth check.
Those additions belong to this project.

## Demonstration fixtures

The example uses these fixtures to make its boundaries observable and testable:

- The canary instruction, `scripts/mcp_canary.py`, Python `mcp` dependency, and
  generated target files prove that both compiled MCP configurations work.
- `AGENT_LAYER_CANARY` proves that a value can be scoped to the MCP child.
- The `local` and `mcp-local` profile names illustrate separate process scopes;
  projects choose names that match their own environments.
- `scripts/check_native_auth.sh` proves one local setup: `gh` can authenticate
  from its credential store without an environment token. It is not a reusable
  authentication policy. Environment tokens remain valid for CI, containers,
  ephemeral machines, and projects that choose them explicitly.
- The CI workflow uses explicit `mise exec` calls for its non-interactive shell;
  activated local shells can invoke the selected tools directly.

These fixtures are project-specific example code, not Copier template defaults.

## Try it

```bash
mise install
mise run agent-sync
mise run agent-check
mise run agent-claude
mise run agent-codex
```

`agent-sync` compiles the committed Claude and Codex files from `apm.yml` and
`.apm/`. Both launch tasks resolve the `local` fnox profile in a fresh child
process. The MCP command resolves the separate `mcp-local` profile, so
`AGENT_LAYER_CANARY` is added to the MCP child and not the agent process.
Codex reads `.codex/config.toml` after this repository is trusted. The first
interactive Codex session records that machine-local trust decision; an
untrusted or unattended session ignores the project config.

## Inspect the result

- `AGENTS.md` and `.claude/rules/project.md` contain the compiled instruction.
- `.mcp.json` and `.codex/config.toml` contain the target-native MCP definitions.
- `apm.lock.yaml` records the APM and MCP resolution.
- `fnox.toml` contains a non-sensitive local profile; real projects replace it
  with their own local or company provider references.

## Test

```bash
uv sync
uv run pytest
fnox exec --profile mcp-local --no-defaults --non-interactive \
  --if-missing error -- python3 scripts/mcp_canary.py --probe
env -u GITHUB_TOKEN scripts/check_native_auth.sh
```

MIT © 2026 CI
