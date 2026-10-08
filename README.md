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

## The checks: `mise run check`

With `include_mise=true` every check is a mise task, and each tool's version
lives once, in `mise.toml` `[tools]` or the toolchain's lock file:

- `lint:<tool>` is one task per linter or formatter. Run with no files it
  checks the whole repo; the commit hook passes the staged files. A fixer task
  rewrites the files and fails when it changed one.
- `check:lint` (aliases `lint`, `fmt`) runs every `lint:` task, with or
  without pre-commit installed.
- `check:unit` runs the tests with diff coverage against `origin/$BASE_REF`
  (default `main`) once that branch exists. `test:fast` (alias `test`),
  `test:unit` and `test:changed` (the pre-push hook) run the tests alone.
- `check:secrets` scans the branch's commits with gitleaks.
- `check:agents`, with the agent layer on, runs `agent:sync -- --frozen` once
  `apm.lock.yaml` is committed.
- `check` runs `check:lint` and `check:unit`; `check:all` runs every `check:`
  part.
- `setup:dev` (alias `bootstrap`) installs the dependencies and the git hooks.

`.pre-commit-config.yaml` holds only `repo: local` hooks with
`language: system`; each hook's entry is `mise run lint:<tool> --`, so pre-commit
only stashes unstaged changes and passes the staged files.

Generated CI runs the same tasks. A `plan` job runs `mise run ci:parts`, which
lists the `check:` parts (all but `check:all`) this change needs:
`.github/check-paths.yml` maps a part to the paths that run it, and a part it
does not name always runs. A matrix job named after each part runs
`mise run <part>`. The aggregate `check` job passes only when the plan and every
part passed, and names a failed part with the command that reruns it. A project
adds a check as a `check:<name>` task in `mise.toml`; CI picks it up with no
workflow change. Without mise, CI keeps its per-step gate and remote-pinned
hooks.

## Coding-agent integration

With `include_mise=true` and `include_agent_layer=true` (both defaults), every
project gets project-owned coding agent configuration. The
`include_engineering_workflow=true` default adds one dependency on the
`agent-skills/engineering` capability pack; set it to false for the base
agent-layer scaffold only.

```bash
mise install
mise run agent:sync
mise run agent:sync -- --refresh
mise run agent:sync -- --frozen
mise run agent:claude
mise run agent:codex
mise run check
```

The old names `agent-sync`, `agent-claude` and `agent-codex` still run, as
aliases.

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
which `agent:sync` compiles into `AGENTS.md`, says every change that lands as a
PR runs it. Deleting that line turns the loop off. The loop reads this project's
facts from three files, seeded with a heading and a short prompt per fact:

- `docs/agents/loop.md`: owner, proof on a branch, acceptance references,
  the skill for each stage the project changes, where a person must approve
  too, how a finding is judged in use, the worktree command, the ledger path
  and any extra verifier checklist;
- `docs/agents/issue-tracker.md`: the tracker, components, what never reaches GitHub,
  extra labels and categories;
- `docs/agents/coding-standards.md`: domain facts only.

`mise run loop:approvals <point> [pr]` (alias `gate`) checks the proof each loop
step leaves on GitHub, with the pack's `approvals.py`. The gates are the merge
approval: the verifier's verdict is a review on the PR, and a PR whose proofs
hold needs no person's label. A `merge:` rule in `docs/agents/loop.md` §
Approvals asks for the owner's `approved:merge` label; a push removes it. The
seed asks for it on a change to `.github/**`, `.pre-commit-config.yaml`,
`mise.toml`, `apm.yml`, `docs/agents/**` or `CODEOWNERS`; `- merge: always`
asks for it on every merge. The
`.github/workflows/approvals.yml` workflow posts the merge result as the
`loop:approvals` commit status on the PR head: pending while it waits for CI's
`check` or a label a rule asks for, failure when a proof is missing, success once every proof
holds. It reruns when a label or the PR body changes and when CI completes, and
posts success on a merge-queue commit, since a PR is queued only once its status
was green. On success on a ready PR that has no auto-merge request yet, it turns
auto-merge on with the repo's `GITHUB_TOKEN`, pinned to the head
(`--match-head-commit`), so a PR made ready by hand lands with no agent action;
the job needs `contents: write` and `pull-requests: write` for that. It never
replaces an existing request. GitHub's free plan has no protection for private repos, so there the
status is only a mark (pending while it waits, red on a missing proof), not a
block: it catches a forgotten step, not a deliberate one.

`mise run loop:land <pr>` is the one way an agent lands a PR: it runs the pack's
`approvals.py land`, which checks every merge proof, then marks the PR ready and
squash-merges it pinned to its head, or turns auto-merge on while only required
checks are pending. It exits 0 once the PR merged or auto-merge is on, 1 on a
missing proof (the PR is left untouched) and 3 while it waits: run it again. It
runs as you, so its merge starts main's push workflows, which a merge caused by
the workflow's `GITHUB_TOKEN` does not.

Where GitHub offers rulesets and merge queues, main lands through a queue.
Generated CI skips draft PRs (marking one ready starts it) and runs on every push
to main and every `merge_group` entry, each in its own run, so a red main points
at one merge. A push compares changed lines against the commit before it, a
queue entry against the queue's base. With the loop on,
`.github/rulesets/main.json` is the `loop-merge-queue` ruleset on main: changes
only through a squashed PR with every review thread resolved, no bypass, and a merge queue (squash, all-green
grouping) that requires exactly two names, CI's `check` job and the
`loop:approvals` status. `mise run setup:github` (alias `merge-queue`) creates
that ruleset on GitHub, or updates it if one with that name exists, and sets
the repository's `allow_auto_merge` and `delete_branch_on_merge` to true, so
`mise run loop:land <n>` (or the approvals workflow) queues the PR once both
names are green and its branch is deleted after the merge. It never reads or changes another ruleset: GitHub
applies every active ruleset on a branch, so the repo's own rules on main keep
applying alongside it. The task prints both settings' previous values and the
`gh api -X PATCH` command that restores them. `mise run setup:github --revert`
deletes the `loop-merge-queue` ruleset, found by name; when it is already gone,
there is nothing to do. If GitHub rejects the ruleset, the task stops before it
changes the settings.

A project without CI, for example a private repo with GitHub Actions off, puts the
line `CI: none` in `docs/agents/loop.md`. The merge approval then stops looking for
a green `check`. Its proof instead is
`python3 .agents/skills/engineering-loop/scripts/approvals.py local-ci <pr>`, run
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

Updating to v0.4.1 replaces the PR template with the `pr` skill's Summary,
Evidence and Merge Danger when the engineering pack is on, and moves the pack to
`^0.9.0`. A repo that edited its PR template resolves that file once.

Updating to v0.5.0, with mise on:

- Splits `check` into `lint:<tool>` tasks and `check:` parts. `check`,
  `check:all`, `check:lint`, `check:unit`, `check:secrets`, `check:agents`,
  `test:fast`, `test:unit`, `test:changed`, `ci:parts`, `setup:dev`, and with
  the loop on `loop:approvals` and `setup:github`, are the new names. The old
  names (`lint`, `fmt`, `test`, `bootstrap`, `gate`, `merge-queue`,
  `agent-sync`, `agent-claude`, `agent-codex`) still run, as aliases.
- Rewrites `.pre-commit-config.yaml` to local hooks that call
  `mise run lint:<tool> --`, and moves every hook tool's version into
  `mise.toml`. The `.env` check becomes `lint:env`; pre-push runs
  `test:changed` and `check:secrets`.
- Replaces the CI job with the `plan`, part matrix and `check` jobs, and adds
  `.github/check-paths.yml`.
- With the loop on, replaces `.github/workflows/gate.yml` with
  `approvals.yml`. The ruleset now requires `check` and `loop:approvals`:
  delete `gate.yml`, then run `mise run setup:github` to update the ruleset and
  turn on `delete_branch_on_merge`.
- Moves the pack to `^0.12.0` and gitignores `.worktrees/`.

A repo that edited `mise.toml`, its hooks or its CI resolves those files once:
a custom check becomes a `check:<name>` task.

Updating to v0.6.0 moves the pack to `^0.13.0`. With the loop on:

- Adds `mise run loop:land <pr>`, and the approvals workflow turns on auto-merge
  for a ready PR whose proofs hold; its job now needs `contents: write`.
- The gates become the merge approval: `approved:merge` is needed only where a
  `merge:` rule in `docs/agents/loop.md` § Approvals asks. A new project's seed
  asks for it on CI, hook, task, pack and loop-file paths; an existing
  `loop.md` has no rule, so add one, or `- merge: always` to keep a label on
  every merge.
- The verifier's verdict is a PR review; a verdict comment no longer counts.
- The ruleset requires every review thread resolved: run
  `mise run setup:github` to update it.

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
