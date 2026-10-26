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
| `apple/xcode`       | Apple app (Xcode · SwiftPM · its own gate script)     |
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
  `lint:json` skips the paths matching `LINT_JSON_SKIP`, an ERE the project
  sets under `[env]` in `mise.toml`, for files with a `.json` name that hold no JSON.
- `check:lint` (aliases `lint`, `fmt`) runs every `lint:` task, with or
  without pre-commit installed.
- `check:unit` runs the tests through `scripts/gate-slot`, which holds one of the
  host's `GATE_SLOTS` (default 1) so parallel agents' gates queue instead of
  overloading one machine, and exports `GATE_JOBS` (the free cores) for a
  parallel runner (`pytest -n "$GATE_JOBS"`); the content template's `check:unit`, a link check bound by the network rather than the host, runs without one. It runs them with diff coverage against `origin/$BASE_REF`
  (default `main`) once that branch exists. `test:fast` (alias `test`),
  `test:unit` and `test:changed` (the pre-push hook) run the tests alone.
- `check:secrets` scans the branch's commits with gitleaks.
- `check:agents`, with the compiled agent layer, runs `agent:sync -- --frozen`
  once `apm.lock.yaml` is committed. The vendored layer has none.
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
`mise run <part>`. In a mise monorepo root, which names its own tasks `//:<task>`,
the parts are the root's own `check:` tasks. The aggregate `check` job passes only when the plan and every
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

### Vendored agent layer

`agent_layer_mode=vendored` is for a repo whose people own the root instructions
and edit skills directly. Nobody there has to know APM: the skills and
`CLAUDE.md` are ordinary committed files.

- `CLAUDE.md` is hand-written, and `AGENTS.md` points Codex at it. Copier writes
  both only when they are missing, so a project's own files survive `copy` and
  `update`. There is no `.apm/instructions`, no `apm compile` and no
  `check:agents`.
- The pack's skills are committed under `.claude/skills/` and `.agents/skills/`;
  only `apm_modules/` is ignored. `apm.lock.yaml` records each deployed file's
  hash.
- The skill list is the project's. `apm install <source>#<ref> --skill <name>`
  writes the pin as `skills:` under the dependency in `apm.yml` (it also
  rewrites the entry's `git:` to the short form); editing that list works too.
  `agent:sync` installs from it, and the install removes a skill dropped from
  it. `apm prune` removes a dropped package from `apm_modules/`.

Anyone may edit a synced skill file and commit it. A plain `apm install` would
silently put the pack's copy back, so `mise run agent:sync` refuses (exit 1)
while a deployed file differs from the pack's copy, naming each file and
`mise run agent:intake`. An edit is a file whose sha256 differs from the hash
`apm.lock.yaml` records, so it shows whatever `apm.yml` says, and a lock that
records no hash for a deployed file makes both tasks fail rather than pass. The
APM maintainer then runs:

```bash
mise run agent:intake               # one patch per edited file, listed
mise run agent:intake -- --refresh  # take the newer compatible pack first
```

`agent:intake` writes each edit as a patch from the pack's copy to the committed
file under `.agent-intake/` (gitignored) and exits 1 while any patch is left.
The pack's copy is what an install would deploy from the lock, installed into a
scratch directory so the tree keeps its edits. Each patch ends one of two ways:

- Port it into the pack and release it, then run `agent:intake -- --refresh`.
  It takes the newer compatible pack; an edited file the release now matches
  resolves itself and its patch goes. Any other edited file is put back and its
  patch stays, now against the new release. That holds for a file or a whole
  skill the release removes: its patch is against `/dev/null`, and a deletion
  you made resolves.
- Drop it: delete the patch, and the next `agent:sync` restores the pack's
  copy. A file the pack no longer ships is removed instead, with its skill
  directory once empty. APM itself keeps an edited file it no longer deploys.
  Sync removes the file only while it still holds the bytes intake took in, so
  an edit made after intake ran makes sync refuse and name the file; run intake
  again. It removes only a file inside a skill directory the lock deploys
  (`.claude/skills/<skill>/`, `.agents/skills/<skill>/`), reached through no
  symlink. Any other path in `.agent-intake/intaken` makes sync refuse, name it
  and remove nothing.

`.agent-intake/` goes once a sync succeeds, audit included, so a failed sync
keeps it.

A minor pack bump goes the same way: edit the ref in `apm.yml` (a caret on 0.x,
`^0.17.0`, excludes 0.18.0), then run `mise run agent:intake -- --refresh`.
Plain `agent:intake` cannot install the old release once the ref is ahead of
the lock and says so.

`--refresh` writes each edited file's bytes to `.agent-intake/saved.json`
before `apm update` runs, and the hash of what the update deployed once it
finishes. A failed update puts the edits back. After an interrupted one,
`agent:sync` refuses and the next `agent:intake` puts back each edit whose file
still holds what the update deployed. Any other file may hold a newer edit, so
it is left as is, the saved edit goes to `.agent-intake/<path>.saved`, and
intake exits 1 until you keep one: move the `.saved` file over the original (or
port it into the pack first), or delete it to keep the current file. A saved
deletion is an empty `.saved` marker: delete both the file and the marker to
keep the deletion.

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
which `agent:sync` compiles into `AGENTS.md` (in `CLAUDE.md` with the vendored
layer), says every change that lands as a PR runs it, unless a developer's personal
instructions say `Engineering loop: off` and loop.md allows it. Deleting that line turns the loop off. The loop reads this project's
facts from three files, seeded with a heading and a short prompt per fact:

- `docs/agents/loop.md`: a `## Settings` block of YAML the pack's `approvals.py`
  reads (the spec policy, the risk rule, the skill for each stage the project
  changes), then in prose the owner, proof on a branch, acceptance references,
  why a person must approve, the project's risk criteria, how a finding is
  judged in use, the worktree command, the ledger path and any extra verifier
  checklist;
- `docs/agents/issue-tracker.md`: the tracker, a `## Settings` block of YAML with
  the components, extra labels and categories, renames and the board's name for
  each loop column, then what never reaches GitHub;
- `docs/agents/coding-standards.md`: domain facts only.

`mise run loop:approvals <point> [pr]` (alias `gate`) checks the proof each loop
step leaves on GitHub, with the pack's `approvals.py`. The gates are the merge
approval: the verifier's verdict is a review on the PR, and a PR whose proofs
hold needs no person's label. Only people approve: `docs/agents/loop.md` §
Settings is the owner's standing policy (`spec.auto`: `bug`, `follow-up`,
`sub-issue`), and a high-risk PR, one with `risk:high` or matching the `risk` rule, waits for the
owner's `approved:merge` label; a push removes it. The seed's rule is
`verifier: true`, which holds when the verifier's pass on the head says
anything but `Risk: low`, plus the paths no check can settle: `.github/**`,
`CODEOWNERS` and `docs/agents/loop.md`. `always: true` asks for the label on
every merge. § Approvals explains three settings the seed leaves off:
`spec.auto: true`, a `signoff` section and `opt_out: true` under `loop`. The
`.github/workflows/approvals.yml` workflow posts the merge result as the
`loop:approvals` commit status on the PR head: pending while it waits for CI's
`check` or a label a rule asks for, failure when a proof is missing, success once every proof
holds. It reruns when a label or the PR body changes and when CI completes, and
posts success on a merge-queue commit, since a PR is queued only once its status
was green. On success on a ready PR that has no auto-merge request yet, and when
the workflow runs with the optional GitHub App's token (`APPROVALS_APP_CLIENT_ID`), it turns
auto-merge on, pinned to the head
(`--match-head-commit`), so a PR made ready by hand lands with no agent action;
the job needs `contents: write` and `pull-requests: write` for that, and `actions: read` to read each check run's workflow (without it GitHub refuses the merge check's query). It never
replaces an existing request, and it turns nothing on when the repo's `allow_auto_merge`
is not `true` or can't be read: there, with no required check pending, `gh pr merge --auto`
would merge at once with `GITHUB_TOKEN`, so no push workflow would run on main. Without
the App token it turns nothing on either: GitHub starts no workflow for an event `GITHUB_TOKEN`
makes, so a merge queue would build the group commit with no CI and wait out its timeout. In
each case the job stops at the status and `mise run loop:land <pr>` queues or merges the PR
with the agent's own token. GitHub's free plan has no protection for private repos, so there the
status is only a mark (pending while it waits, red on a missing proof), not a
block: it catches a forgotten step, not a deliberate one.

`mise run loop:land <pr>` is the one way an agent lands a PR: it runs the pack's
`approvals.py land`, which checks every merge proof, then marks the PR ready and
squash-merges it pinned to its head, or turns auto-merge on while only required
checks are pending. It exits 0 once the PR merged or auto-merge is on, 1 on a
missing proof (the PR is left untouched) and 3 while it waits: run it again, or
pass `--wait` to return only once the PR merges or needs someone. It
runs as you, so a merge it makes starts main's push workflows.

By default the approvals workflow only posts the status, and `loop:land` lands
the PR: GitHub starts no workflow for an event the workflow's `GITHUB_TOKEN`
causes, so a merge it made would start no push workflow on main (CI's push run,
Pages, tags). To have the workflow land a PR made ready by hand too, give it a
GitHub App's token, whose merge starts them:

1. Create a GitHub App with repository permissions Contents: write, Pull requests:
   write, Commit statuses: write, Issues: write, Checks: read and Actions: read, and install it on
   the repo.
2. Set the repo variable `APPROVALS_APP_CLIENT_ID` to the App's client ID and the
   secret `APPROVALS_APP_PRIVATE_KEY` to a private key it generated
   (`gh variable set`, `gh secret set`).

With the variable set, the workflow runs everything with the App's token and,
on success, turns auto-merge on where the repo allows it and the PR has no
request (the paragraph above); without it, it posts the status with `GITHUB_TOKEN` and
turns nothing on. `mise run setup:github` prints which one the repo uses.

Where GitHub offers rulesets and merge queues, main lands through a queue.
Generated CI skips draft PRs (marking one ready starts it) and runs on every push
to main and every `merge_group` entry, each in its own run, so a red main points
at one merge. A push compares changed lines against the commit before it, a
queue entry against the queue's base. With the loop on,
`.github/rulesets/main.json` is the `loop-merge-queue` ruleset on main: changes
only through a squashed PR with every review thread resolved, no bypass, and a merge queue (squash, all-green
grouping) that requires exactly two names, CI's `check` job and the
`loop:approvals` status. GitHub offers merge queues only on organization-owned
repos, so a user-owned repo answers `merge_queue=false`: the ruleset then has no
queue and keeps every other rule, and auto-merge lands the PR once both names
are green. Its name stays `loop-merge-queue`, since `setup:github` finds its
ruleset by that name. `mise run setup:github` (alias `merge-queue`) creates
that ruleset on GitHub, or updates it if one with that name exists, and sets
the repository's `allow_auto_merge` and `delete_branch_on_merge` to true, so
`mise run loop:land <n>` (or, with the App token, the approvals workflow) queues
the PR once both names are green, or without a queue merges it, and its branch is deleted after the merge. It never reads or changes another ruleset: GitHub
applies every active ruleset on a branch, so the repo's own rules on main keep
applying alongside it. The task prints both settings' previous values and the
`gh api -X PATCH` command that restores them. `mise run setup:github --revert`
deletes the `loop-merge-queue` ruleset, found by name; when it is already gone,
there is nothing to do. If GitHub rejects the ruleset, the task stops before it
changes the settings. A private repo on GitHub Free has no rulesets and no
auto-merge: the task first reads the rules on main, and when GitHub answers that
read with its 403 naming the plan (the probe `land` uses), it skips the ruleset
and auto-merge, sets squash-only merges (`allow_merge_commit` and
`allow_rebase_merge` false, `allow_squash_merge` true) and
`delete_branch_on_merge`, prints their restore command and that GitHub enforces
nothing on main, so `loop:land`'s proofs are the only gate. Any other error on
that read stops the task before a write.
Last, it runs the pack's `labels.py`, the labels' one definition: renames in
place first (`bug`, `enhancement`, `chore` and `documentation` to their `kind:`
names, and § Renamed labels in `docs/agents/issue-tracker.md`), so every issue
keeps its label, then creates the loop's labels (states, `kind:`, sizes) and an
`area:` label for each component the tracker lists, and deletes an unlisted
label only once nothing carries it. `mise run setup:github --dry-run` prints that
plan and writes nothing to GitHub: no ruleset, settings or labels.

A project without CI, for example a private repo with GitHub Actions off or one
whose own workflows only release, answers `include_ci=false`. It then gets no CI
workflow and no `.github/check-paths.yml`, and no `ci:parts` or `ci:check` task;
no workflow but `approvals.yml` is written, so the repo's own workflows stay as
they are. The ruleset requires only `loop:approvals`, and the seeded
`docs/agents/loop.md` has `ci: false` under `loop` in its settings. The merge approval then stops looking for
a green `check`. Its proof instead is
`uv run .agents/skills/engineering-loop/scripts/approvals.py local-ci <pr>`, run
on a clean checkout at the PR's head commit. It runs `mise run check:all` there and,
when the check passes without changing the tree, posts `Local check passed` with
that head on the PR. So anything the project's CI enforced has to be in
`mise run check:all` too, or it stops being enforced.
The approvals workflow then reruns on that comment instead of on CI's completion,
so `loop:approvals` turns green with no other event.

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

Until a release newer than v0.8.0 is tagged, reaching anything after v0.8.0,
the `apple/xcode` project type included, needs `--vcs-ref main` (or a commit
SHA) on `copier update`. Without it, Copier
targets the newest tag, v0.8.0:

- A project at v0.8.0 stays there.
- A project generated from a later commit records a version like
  `0.8.0.post4.dev0+92bf097`, newer than v0.8.0. Copier refuses the downgrade
  and exits 1 ("You are downgrading from 0.8.0.post4.dev0+92bf097 to 0.8.0.
  Downgrades are not supported.").

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

Updating to v0.6.0 moves the pack to `^0.13.1`. With the loop on:

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
- The approvals workflow can run with a GitHub App's token, so the merges it
  makes start main's push workflows: set `APPROVALS_APP_CLIENT_ID` and
  `APPROVALS_APP_PRIVATE_KEY` (Engineering loop). Without them it runs with
  `GITHUB_TOKEN`, as before.
- The approvals job also gets `actions: read`: the pack reads each check run's
  workflow, which GitHub refuses without it ("Resource not accessible by
  integration").

Updating to v0.7.0 moves the pack to `^0.15.0`. With the loop on:

- Only people approve: an agent no longer records a spec or merge approval.
  The seed's § Approvals gets `- spec: auto unless risk`,
  `- merge: auto unless risk` and a `risk:` rule; an existing `loop.md` keeps
  its lines, a `merge:` condition read as a `risk:` rule, so add the two policy
  lines to let the policy approve bugs, follow-ups and stories of an approved epic.
- The approvals job gets `issues: write` (and the App `permission-issues:
  write`), so the gate can add `risk:high` to a PR it finds high risk. A repo
  using an App raises the App's Issues permission to write and accepts it on the
  installation first, or the token step fails and `loop:approvals` never posts.
- An optional `cap: <n>` line in loop.md changes the verifier's pass cap.

Updating to v0.8.0 moves the pack to `^0.16.0`. With the loop on:

- `mise run setup:github` ends by syncing the labels with the pack's
  `labels.py`, and takes `--dry-run`, which prints the label plan and writes
  nothing.
- `docs/agents/issue-tracker.md` lists components as `area:<name>` labels, a new
  project's seeded with its leaf's parts plus `area:tooling` and `area:docs`,
  and gets an optional § Renamed labels. An existing tracker keeps its lines:
  write each component as a bullet with its name in backticks, a bare name
  being read as `area:<name>`, and each extra category the same way as
  `kind:<name>`.
- Run the sync once: `mise run agent:sync` for the 0.16.0 pack, then
  `mise run setup:github --dry-run`, read the plan, and `mise run setup:github`.
  Renames happen in place, so issues keep their labels, and a label still on an
  issue is never deleted.

Updating to the next release moves APM to 0.33.0 and asks `agent_layer_mode`:

- `compiled`, the default, keeps today's layer. Run `mise install`, then
  `mise run agent:sync`, and commit what it changes.
- `vendored` (Vendored agent layer) drops `check:agents` and the
  `.apm/instructions` seed, adds `agent:intake` and gitignores `.agent-intake/`.
  Copier keeps an existing `CLAUDE.md` and `AGENTS.md`, so make them the
  hand-written ones. Delete `.apm/instructions` and the nested `AGENTS.md` and
  `CLAUDE.md` files `apm compile` wrote, since nothing updates them any more,
  then run `mise run agent:sync` and commit the result.

The next release asks `merge_queue` (default true) with the loop on. A
user-owned repo, where GitHub rejected the ruleset's merge queue and
`setup:github` stopped before any change, answers false and runs
`mise run setup:github` again. With the default the ruleset is byte-identical.

On the next release, a private repo on GitHub Free, where `setup:github` stopped
at the ruleset's 403, runs `mise run setup:github` again: it now sets
squash-only merges and head branch deletion and syncs the labels.

On the next release, with the loop on and no approvals App configured, the approvals
workflow posts `loop:approvals` and stops: it no longer turns auto-merge on with
`GITHUB_TOKEN`, whose merge-queue entry got no CI. `mise run loop:land <pr>` lands the PR.

Updating to the next release asks `include_ci` (default true; with it true
nothing changes). Answering false, with the loop on:

- Copier no longer writes `.github/workflows/ci.yml` or
  `.github/check-paths.yml`, and `mise.toml` loses `ci:parts` and `ci:check`.
  An update doesn't delete the files an earlier version wrote: delete them by
  hand. Every other workflow is left as it is.
- The approvals workflow reruns on a PR comment whose first line is
  `Local check passed` (the record `approvals.py local-ci` posts) instead of on
  CI's completion.
- The ruleset requires only `loop:approvals`: run `mise run setup:github` to
  update it.
- An existing `docs/agents/loop.md` is the project's and keeps its lines: add
  the line `CI: none` to it.

Without mise, CI's `uv sync` becomes `uv sync --locked`, so a stale `uv.lock`
fails CI there too. A new project gets its `uv.lock` at generation; an existing
repo without mise that has none (dbt) runs `uv lock` and commits it before
updating.

Updating to the next release adds the `apple/xcode` project type and its
`gate_script` question; other project types render as before.

Updating to the next release moves the pack to `^0.18.0`; run
`mise run agent:sync` and commit what it changes. A new project's seeds
explain pack 0.18.0's lines without switching any on, so it behaves as before.
An existing project's `docs/agents/*.md` are its own and keep their lines, so
it adds what it wants by hand:

- loop.md § Approvals: `- spec: auto` in place of `- spec: auto unless risk`
  to approve every spec by policy except one a `risk:` rule holds;
  `- signoff: <condition>` lines for changes the owner signs off in use; and
  the line `Opt-out: allowed` to let a developer whose personal instructions
  say `Engineering loop: off` work outside the loop.
- issue-tracker.md: a `## Board` section naming the board's column for each
  loop column, such as ``- `Build` is `In progress` ``, when the board's
  names differ from the loop's.
- With the vendored layer, `CLAUDE.md` is the project's too: add the opt-out
  clause to its loop line by hand. The compiled layer's
  `.apm/instructions/project.instructions.md` gets it from the update.

Updating to the next release sets `indent_size = 4` for `*.swift` in
`.editorconfig`, since Xcode honours the file and would otherwise indent Swift
by 2. An `apple/xcode` project's `.pre-commit-config.yaml` loses its trailing
blank line, which failed its own `lint:eof`. Copier keeps a deleted file
deleted on update, so a project that deleted either file to work around this
copies it back from a fresh render.

Updating to the next release moves the pack to the exact tag
`engineering-v0.23.2`, which Renovate moves on from there (below): run
`mise run agent:intake -- --refresh`, then `agent:sync`, and commit what they
change. It replaces `.github/dependabot.yml` with `renovate.json`.

Updating to the next release moves the pack to `engineering-v0.24.1`. Since
0.24.0 its `approvals.py`, `labels.py` and `board.py` read loop.md's and
issue-tracker.md's settings from a YAML block under `## Settings` and refuse a
file still on the line form (kzarzycki/agent-skills#344, #352). An older
reader finds no lines in the block and runs with no settings, so move both
files in the same commit as the pack, after `mise run agent:sync`. 0.24.1 puts
a `__pycache__` file in each skill's `scripts/`, so a project that ignores
cache folders writes `__pycache__/` with the slash, as the python leaves'
`.gitignore` does. The pack's 0.24.0 changelog maps every old line to its key:

- loop.md: a `## Settings` heading with a `yaml` block in place of the
  `- spec:`, `- merge:` and `- risk:` lines, as a fresh render writes it.
  `spec: auto unless risk` becomes `spec:` `auto:` with `bug`, `follow-up` and
  `sub-issue`; `merge: auto unless risk` goes; `CI: none`, `cap: <n>` and
  `Opt-out: allowed` become `ci: false`, `cap: <n>` and `opt_out: true` under
  `loop:`; § Practice's lines become `practice:` keys (`spec: brainstorming`);
  each `risk:`, `plan:` and `signoff:` condition becomes that section's
  `paths` and `labels`, one per line, `component billing` written
  `area:billing` and `size:L or larger` `size:L` and `size:XL`. A fresh
  render's rule is `verifier: true` with `.github/**`, `CODEOWNERS` and
  `docs/agents/loop.md`: the verifier now judges a change to `mise.toml`,
  `.pre-commit-config.yaml`, `apm.yml` or the rest of `docs/agents/`, so keep
  those paths if the owner should still see each one.
- issue-tracker.md: a `## Settings` block in place of § Components, § Extra
  labels, § Extra categories, § Renamed labels and § Board: `components:`,
  `labels:`, `categories:`, `renames:` (`frontend: area:web`) and `board:`
  (`Build: In progress`), each item `name: text`. § Never on GitHub stays
  prose.
- The loop line in `CLAUDE.md` or `.apm/instructions/project.instructions.md`
  names `opt_out: true` instead of `Opt-out: allowed`; the compiled layer gets
  it from the update, a vendored `CLAUDE.md` takes it by hand.
- The tasks call the scripts with `uv run`, which installs their PyYAML, and
  the approvals workflow installs `uv` through mise.

Updating to v0.10.0 moved the pack to `^0.21.0` (a caret on 0.x:
`^0.18.0` never takes 0.19.0, nor `^0.20.0` 0.21.0); run
`mise run agent:intake -- --refresh`, then `agent:sync`, and commit what they
change. 0.19.0 adds the optional `chief-of-staff` skill, and since 0.18.3
`engineering-loop` links to `orchestrating-agents`. A project whose `apm.yml`
lists its skills by name adds `orchestrating-agents`, and `chief-of-staff` if it
wants one; the rendered `apm.yml` lists none and so deploys both. In 0.20.0 a
chief of staff follows its leads through Omnigent session subscriptions, which
need an Omnigent build that has them; on an older build, `start --top-level`
prints `not subscribed` and that lead is followed with `watch`. 0.21.0 archives
a finished sub-agent and needs an Omnigent build with kzarzycki/omnigent 4dd0af32;
on an older build, archiving a sub-agent stops its parent too.

## Dependency updates: Renovate

With mise, a project gets `renovate.json` and `mise run deps:renovate`, which runs the
Renovate CLI (free, AGPL-3.0) on the repo with the developer's own `gh` login (scopes
`repo` and `workflow`), so it needs no org admin: its PRs are the developer's, and a PR a
user token opens starts CI. A nightly scheduled agent runs it. Updates fall in two classes:

- **verify** (label `verify`, draft): the template (Renovate's `copier` manager, which
  trusts the template's tasks), the `apm.yml` packages pinned to a `<package>-vX.Y.Z`
  tag (then `agent:sync --refresh` regenerates the lock and agent files), grouped into
  one PR a night; and every major update, each its own PR. An agent reviews each before
  `loop:land`.
- **routine**: patch and minor updates of tools, libraries and actions, one group a week
  after 3 days, with auto-merge on. A verifier reviews it too: its PRs are the developer's, and
  loop.md's `bot` section exempts only a GitHub App's account.

Mend's hosted Renovate does not fit: its free tier runs no scripts and no
`postUpgradeTasks`, so template and pack updates would fail or leave the lock stale.
Upgrades that take it off a person's machine: a classic PAT in a repo secret and a
workflow, or a GitHub App, which needs an org owner.

## Adopt an existing (pre-template) repo

A repo that predates the template can be brought under management — `copier copy`
onto its directory writes `.copier-answers.yml` + the governance scaffold,
prompting on any file that already exists:

```bash
cd existing-repo
copier copy --trust --data project_type=software/python --data include_example=false gh:your-org/project-templates .
git add -p && git commit          # keep what you want from the prompted merge
```

An Xcode repo adopts with `--data project_type=apple/xcode --data
gate_script=Scripts/gate.sh --data include_example=false`, naming its own gate
script: `mise run check` then runs it.

Governance files (hooks, CI, `.editorconfig`, ADR, CODEOWNERS) land clean;
toolchain config (`pyproject.toml`, `build.gradle`) is hand-merged once.

## How the template is organized

```
templates/
  _base/              universal governance — included whole by every leaf
  _lang/{python,node,java}/   language toolchains — included by coded leaves
  software/{python,node,java}/
  infra/terraform/
  apple/xcode/
  data/dbt/
  authoring/content/
  ai/{skills,mcp}/
```

`_base` and `_lang` live outside any rendered subtree; leaves pull their content
in with repo-root-relative Jinja `{% include %}`. See
`.workflow/2026-06-25-borrow-feedbacks-app-practices/02-TECH-DESIGN.mdx` for the
full design.
