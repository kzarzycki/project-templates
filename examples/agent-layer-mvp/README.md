# agent-layer-mvp

This generated project shows the boundary between Copier scaffolding and
project-owned agent configuration for Claude Code and Codex.

Copier created `apm.yml`, `fnox.toml`, the `.apm/` instruction seed, and the
`agent-*` tasks in `mise.toml`. This project then added its canary instruction,
local stdio MCP server, synthetic fnox profile, and native GitHub CLI auth check.
Those additions belong to this project; they are not template defaults.

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
process. The canary receives only the synthetic `AGENT_LAYER_CANARY` value.

`scripts/check_native_auth.sh` confirms that `gh` can use its credential-store
login while `GITHUB_TOKEN` and `GH_TOKEN` are absent. It calls `gh auth status`,
suppresses its output, and never extracts or copies the token into fnox.

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
fnox exec --profile local --no-defaults --non-interactive \
  --if-missing error -- python3 scripts/mcp_canary.py --probe
env -u GITHUB_TOKEN scripts/check_native_auth.sh
```

MIT © 2026 CI
