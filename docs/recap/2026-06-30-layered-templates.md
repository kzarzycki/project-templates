# Recap: layered Copier templates

Shipped in PR #3 (squashed to `main` as `5a205eb`). Design lives in the Decision
Spec + Tech Design; this records only what implementation and live CI added.

## Decisions made during implementation

- **`fresh_repo` detection uses `.git` in the project dir, not `git rev-parse
  --git-dir`.** The latter walks up to a parent repo, so generating a project
  inside an existing worktree (CI into `_out/`, or a sub-project of a repo) was
  misread as adoption — no scaffold commit. The directory-local check also keeps
  the real adoption path correct (an adopted repo has its own `.git`).
- **diff-coverage gates PRs only** (`if: github.event_name == 'pull_request'`).
  `github.base_ref` is empty on `push`, so the prior `origin/main` compare
  equalled HEAD on a main push and the 100%-diff gate silently passed. Dropped
  the root-commit fallback that existed to paper over this.
- **Adoption never forces hooks or auto-commits.** `pre-commit install -f` and
  the scaffold commit run only on a repo `_post_gen` created. Adoption uses plain
  install (existing hook migrates to `.legacy`) and skips the commit.
- **`.workflow/`, `.memsearch/`, `.superpowers/` are gitignored**, not committed —
  treated as agent/tooling state. The Decision Spec + Tech Design were therefore
  not versioned in-repo. (Open question if they should live under `docs/design/`.)

## Live CI findings (none surfaced without running the repo's own CI)

- The repo's own CI matrix was stale — it drove `bootstrap.sh --language …`, the
  pre-`project_type` interface. Rewrote it to `--type`, covering every layer
  (base, all three lang mixins, a base-only leaf, the parametric mcp leaf).
- `astral-sh/setup-uv` with `enable-cache: true` hard-fails in a repo with no
  `uv.lock`. Dropped caching (the template repo has no Python project of its own).
- The java leaf's scaffold commit runs spotless (google-java-format) in a
  pre-commit hook. The generate-job had no JDK set up, so it ran on the runner's
  default JVM and google-java-format 1.34.1 crashed. Pinned JDK 21 (the template's
  default `java_version`); 1.34.1 is verified to work there.

## Process

- Review was cross-model: a Claude fork (exhaustive render + hook execution) plus
  a Codex pass (correctness). The three approved fixes came from that review; the
  four CI-surfaced defects above did not — running the real CI was load-bearing.
- Auto-mode blocks an agent merging its own PR to `main` without human approval;
  the merge required an explicit go-ahead.

## Follow-ups / deferred

- Decide whether the Decision Spec + Tech Design should be versioned under
  `docs/design/` rather than left as `.workflow/` tooling state.
- End-user robustness for spotless relies on the pinned toolchain (mise + Gradle
  `toolchain` = 21). A user committing with a mismatched ambient JDK can still hit
  the google-java-format crash; not addressed beyond the pinned environment.
