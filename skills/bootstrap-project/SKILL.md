---
name: bootstrap-project
description: >
  Scaffold a brand-new project repository with sensible engineering conventions
  baked in — directory layout, git init, pinned pre-commit hooks (ruff/biome/markdownlint
  + detect-secrets + gitleaks + actionlint/zizmor + dangling-symlink check),
  CLAUDE.md, LICENSE, README, GitHub Actions CI, and a per-type toolchain — then
  make the first commit. Deterministic: a Copier template driven by scripts.
  Supports software (Python · uv/ruff/pytest, Node · npm/biome/vitest, Java ·
  Gradle/Spotless/JaCoCo), data (dbt), authoring (docs/markdown), and AI repos
  (Claude Code skills, MCP servers). Trigger when the user wants to START A NEW
  PROJECT or REPO from scratch: "new project", "start a new project", "scaffold a
  project", "bootstrap a repo", "set up a new python/node/java project", "create a
  new repo", "init a project", "spin up a repo", "new mcp server", "new dbt
  project", "new skills repo", "kickstart a project". Also trigger when the user
  names a project and a type and asks to begin. Do NOT trigger for changes to an
  EXISTING project: adding a file, module, function, branch, test, or feature to
  the current repo; "new branch", "new file", "new component"; configuring CI or
  hooks on a repo that already exists; or merely discussing a project. This skill
  creates a fresh repo, it does not modify one.
---

# Bootstrap Project

Creates a new repository from the Copier template that ships in this same repo
(the `templates/<project_type>/` subtree, selected by the root `copier.yml`),
applying good engineering conventions. The template is the source of truth; this
skill only recognizes intent, gathers two inputs, and runs the deterministic
script.

## Flow

1. **Gather the two required inputs.** `project_name` (kebab-case) and
   `project_type`, one of:

   | `project_type`      | For                                             |
   |---------------------|-------------------------------------------------|
   | `software/python`   | Python service / library (uv · ruff · pytest)   |
   | `software/node`     | Node / TypeScript (npm · biome · vitest)        |
   | `software/java`     | Java / JVM (Gradle · Spotless · JaCoCo)         |
   | `data/dbt`          | dbt project (sqlfluff · dbt build/test)         |
   | `authoring/content` | docs, research, markdown (markdownlint · links) |
   | `ai/skills`         | a Claude Code skills / plugin repo              |
   | `ai/mcp`            | an MCP server (python or node toolchain)        |

   If the user gave a name and an obvious type, proceed; otherwise ask just for
   what's missing.
2. **For `ai/mcp` only, pick the toolchain.** Pass `--language python` or
   `--language node` (default python). No other type takes `--language`.
3. **Infer optionals from context — don't interrogate.** `description`,
   `license` (default MIT), `include_mise` (default true), and the runtime
   version (`python_version`/`node_version`/`java_version`) default sensibly —
   see the root `copier.yml` for the full question set. Pass an optional only
   when the user clearly wants it (e.g. "Apache licensed" → `license=Apache-2.0`).
   Author/email are resolved automatically from `git config`.
4. **Run the wrapper** (never re-implement scaffolding, never re-run `_tasks`):

   ```bash
   scripts/bootstrap.sh --name <project_name> --type <project_type> \
     [--dest <dir>] [--language python|node] [license=Apache-2.0] [include_mise=false]
   ```

   It calls `copier copy --trust --defaults --data ...` so nothing prompts.
   Copier's `_tasks` then run automatically: git init → install deps → install
   pre-commit hooks → first commit. On an interactive terminal it also offers
   to `gh repo create` (confirm-gated; declining leaves the local commit intact).
5. **Relay the result** — the generated path and what was created. Don't dump
   file contents.

## Notes

- Requires `copier` (`uv tool install copier`) and, for hooks, `pre-commit`
  (`uv tool install pre-commit`). The script degrades gracefully if a tool is
  missing and tells the user what to install.
- The wrapper points copier at `gh:kzarzycki/project-templates` by default, so a
  generated project records a real template ref and can later pull improvements:
  `cd <project> && copier update`. Override the source with
  `BOOTSTRAP_TEMPLATE_SRC=<path>` to test a local checkout.
- Full template internals and the per-type file inventory live in the root
  `copier.yml` and the `templates/` tree of this repo.
