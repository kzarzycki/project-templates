# project-templates

One Copier template that scaffolds a new repository of **any kind** — software,
data, docs, or AI — on one shared engineering base: git, pinned pre-commit hooks
(incl. secret scanning + actionlint/zizmor), CI, conventions, `CLAUDE.md`, and a
per-type toolchain. Plus the `bootstrap-project` Claude Code skill that drives it.

This repo is two things at once, read by two consumers that never collide:

- a **Copier template** — `copier copy gh:your-org/project-templates <dest>`
  renders the selected `project_type` subtree under `templates/`.
- a **Claude Code plugin** — `.claude-plugin/` + `skills/bootstrap-project/`,
  loaded via the agent-skills marketplace. Copier never sees `skills/`.

## Use it directly

```bash
uv tool install copier pre-commit
copier copy --trust gh:your-org/project-templates my-tool \
  --data project_name=my-tool --data project_type=software/python
```

`project_type` is one of:

| `project_type`      | For                                                   |
|---------------------|-------------------------------------------------------|
| `software/python`   | Python service / library (uv · ruff · pytest)         |
| `software/node`     | Node / TypeScript (npm · biome · vitest)              |
| `software/java`     | Java / JVM (Gradle · Spotless · JaCoCo)               |
| `infra/terraform`   | Infrastructure (Terraform · TFLint)                    |
| `data/dbt`          | dbt project (sqlfluff · dbt build/test)               |
| `authoring/content` | docs, research, markdown (markdownlint · link-check)  |
| `ai/skills`         | a Claude Code skills / plugin repo                    |
| `ai/mcp`            | an MCP server — python or node toolchain (parametric) |

See `copier.yml` for every question. Post-generation (`_post_gen.sh`) runs git
init, installs deps, installs hooks, and makes the first commit.

## The gate: `mise run check`

With `include_mise=true` every project gets `mise run check`: the toolchain's
tests (and diff coverage against `origin/$BASE_REF`, default `main`, once that
branch exists), the project's own checks, then `pre-commit run --all-files`,
which carries lint and format. With the agent layer on it also runs
`mise run agent-sync -- --frozen` once `apm.lock.yaml` is committed; before the
first sync it says so and skips that step. Generated CI installs the pinned
tools with mise and runs `mise run check` as its gate, so agents and CI run the
same command. A project adds a check by editing the task. Without mise, CI keeps
its per-step gate.

## Coding-agent integration

With `include_mise=true` and `include_agent_layer=true` (both defaults), every
project gets project-owned coding agent configuration. The
`include_engineering_workflow=true` default adds one dependency on the
`agent-skills/engineering` capability pack; set it to false for the base
agent-layer scaffold only.

```bash
mise install
mise run agent-sync
mise run agent-sync -- --refresh
mise run agent-sync -- --frozen
mise run agent-claude
mise run agent-codex
mise run check
```

The first default sync creates `apm.lock.yaml`, installs the selected skills,
compiles both supported coding-agent targets, and audits the result. Commit the
manifest, lock, `.apm` sources, and generated Claude/Codex files. Later default
syncs converge against that lock. Use `--refresh` to seek compatible dependency
updates and `--frozen` in CI to reject stale committed state.

`apm.yml` is the single source of configured APM targets. Claude Code and Codex
are the only coding agents currently implemented and acceptance-tested. GitHub
Copilot and Cursor are planned integrations, not supported coding agents.

To add another coding-agent integration:

1. Add its APM mapping to `apm.yml`.
2. Add native-output validation for its generated files.
3. Add an optional launcher only when the product has a stable CLI.
4. Add an acceptance fixture for the compiled configuration.
5. Add product-specific setup docs.

The template supplies the compiler contract and task names. Instructions,
skills, concrete MCP servers, CLI dependencies, endpoints, and coding-agent-specific
additions are project-owned. `include_fnox=true` adds an empty
`fnox.toml` for machine bindings; the project chooses its profiles and providers.
Native CLI credentials such as `gh auth login` remain in the CLI credential
store.

Copier does not install APM or fnox, contact a secret provider, compile coding
agent configuration, or launch a coding agent. `mise install` installs the
pinned tools after generation. Use `include_agent_layer=false` to omit the
coding-agent integration or `include_fnox=false` to keep APM and the launch tasks
without fnox wrapping. Codex loads the generated `.codex/config.toml` only after
the repository is trusted; the trust decision is machine state and is not
committed to the repo.

## Engineering loop

With the pack on, `engineering_loop=true` (the default) turns on the pack's
`engineering-loop` skill: one line in `.apm/instructions/project.instructions.md`,
which `agent-sync` compiles into `AGENTS.md`, says every change that lands as a
PR runs it. Deleting that line turns the loop off. The loop reads this project's
facts from three files, seeded with a heading and a short prompt per fact:

- `docs/agents/loop.md`: owner, proof on a branch, acceptance references,
  the skill for each stage the project changes, where a person must approve
  too, how a finding is judged in use, the worktree command, the ledger path
  and any extra verifier checklist;
- `docs/agents/issue-tracker.md`: the tracker, components, what never reaches GitHub,
  extra labels and categories;
- `docs/agents/coding-standards.md`: domain facts only.

Its gate is `mise run check`. `mise run gate <build|merge> [pr]` checks the
proof each loop step leaves on GitHub (the pack's `gate.py`, then any check the
project adds to the task); a pre-push hook runs it for build, and its own
workflow, `.github/workflows/gate.yml`, runs it for merge on every ready PR, apart
from the project's CI. GitHub's free plan has no protection for private
repos, so that job is a red check, not a block: it catches a forgotten step, not
a deliberate one.

A project without CI, for example a private repo with GitHub Actions off, puts the
line `CI: none` in `docs/agents/loop.md`. The merge gate then stops looking for
green CI checks. Its proof instead is
`python3 .agents/skills/engineering-loop/scripts/gate.py record-check <pr>`, run
on a clean checkout at the PR's head commit. It runs `mise run check` there and,
when the check passes without changing the tree, posts `Local check passed` with
that head on the PR. So anything the project's CI enforced has to be in
`mise run check` too, or it stops being enforced.

## Use it via Claude

Ask Claude to "start a new python project called my-tool" — the
`bootstrap-project` skill gathers name + type and runs the same copier call
non-interactively.

## Update an existing project

This template is alpha, and coding-agent updates can be breaking. Projects with
legacy `shared_apm` or `toolkit_stack` answers are not automatically compatible.
Before running Copier update, choose explicit `include_agent_layer`,
`include_engineering_workflow`, and `include_fnox` values, then resolve or
replace old coding agent files that conflict with the new scaffold.

Review the resulting diff before accepting it. The template does not include a
migration layer for legacy coding-agent configuration.

Updating to v0.4.0 asks `engineering_loop`, adds `mise run check` and the CI
gate that calls it, and, with the loop on, the loop line and the `docs/agents/`
skeletons, the `gate` task, its pre-push hook and its workflow.

## Adopt an existing (pre-template) repo

A repo that predates the template can be brought under management — `copier copy`
onto its directory writes `.copier-answers.yml` + the governance scaffold,
prompting on any file that already exists:

```bash
cd existing-repo
copier copy --trust --data project_type=software/python --data include_example=false gh:your-org/project-templates .
git add -p && git commit          # keep what you want from the prompted merge
```

Governance files (hooks, CI, `.editorconfig`, ADR, CODEOWNERS) land clean;
toolchain config (`pyproject.toml`, `build.gradle`) is hand-merged once.

## How the template is organized

```
templates/
  _base/              universal governance — included whole by every leaf
  _lang/{python,node,java}/   language toolchains — included by coded leaves
  software/{python,node,java}/
  infra/terraform/
  data/dbt/
  authoring/content/
  ai/{skills,mcp}/
```

`_base` and `_lang` live outside any rendered subtree; leaves pull their content
in with repo-root-relative Jinja `{% include %}`. See
`.workflow/2026-06-25-borrow-feedbacks-app-practices/02-TECH-DESIGN.mdx` for the
full design.
