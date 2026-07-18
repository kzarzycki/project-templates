# agent-layer-mvp

A new software/python project.

## Conventions

- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`). Optional scope: `feat(api):`.
- **Branches:** `feat/<kebab-case>`, `fix/<kebab-case>`.
- **Before committing:** show the diff and the message. Hooks run on commit; run `pre-commit run --all-files` to check everything.
- **Secrets:** never commit `.env`. CI fails if `.env` is tracked. Add false positives to `.gitleaks.toml`.
- **Decisions:** record architecture decisions as ADRs in `docs/adr/` (start from `docs/adr/0001-record-architecture-decisions.md`).

## Tooling (Python)

- `uv sync` — install deps · `uv add <pkg>` — add a dep
- `uv run pytest` — tests · `uv run ruff check . && uv run ruff format .` — lint + format
- CI gates **diff coverage**: 100% of changed lines, via `diff-cover` over `pytest --cov`.
- Layout: `src/agent_layer_mvp/`, tests in `tests/`. Python >= 3.14.
