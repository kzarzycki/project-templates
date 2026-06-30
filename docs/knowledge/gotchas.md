# Gotchas

Durable, reusable lessons. Each entry is the gotcha + the fix, actionable cold.

## Git / scaffolding

- **`git rev-parse --git-dir` walks up to a parent repo.** To decide "is *this*
  directory its own repo" (e.g. scaffolding tools choosing init vs. adopt), test
  for `.git` in the current directory itself (`[ -e .git ]`). The traversal
  version misfires whenever you generate into a subdirectory of an existing repo.
- **`pre-commit install -f` overwrites `.git/hooks/pre-commit`.** Use `-f` only on
  a repo you just created (it beats "migration mode" when a global git template
  seeds the hooks dir). On an existing repo, a plain `pre-commit install` migrates
  the existing hook to `pre-commit.legacy` and chains it — force would destroy it.

## Copier

- **`copier copy <git-repo>` reads *committed* files, not the working tree.** To
  test uncommitted template changes, render from a non-git snapshot
  (`rsync -a --exclude=.git ./ /tmp/snap/` then `copier copy /tmp/snap dest`).

## GitHub Actions

- **`github.base_ref` is empty on `push` events** (set only on `pull_request`).
  Any diff-coverage / changed-lines gate that defaults the base to `main` on push
  compares HEAD against itself → empty diff → the gate silently passes. Scope such
  gates to `if: github.event_name == 'pull_request'`.
- **`astral-sh/setup-uv` with `enable-cache: true` hard-fails when no `uv.lock`
  exists** ("No file matched to [**/uv.lock]"). Drop the cache for repos without a
  Python lockfile (e.g. template/tooling repos).
- **A job that generates and commits a project runs that project's pre-commit
  hooks** — so the job needs whatever toolchain those hooks invoke (JDK for
  spotless, node for biome, etc.), even if the job itself isn't "a java/node job."

## Java / Gradle / spotless

- **Spotless runs google-java-format on the Gradle *daemon* JVM, not the compile
  `toolchain`.** Pinning `toolchain { languageVersion = of(21) }` does not control
  which JVM formats the code — that's `JAVA_HOME` / `org.gradle.java.home`.
- **google-java-format 1.34.1 needs JDK ≥24 at runtime** (references
  `com.sun.tools.javac.tree.JCTree$JCAnyPattern`); on an older daemon JVM it dies
  with `NoClassDefFoundError`. Match the daemon JDK to a version the pinned
  google-java-format supports (1.34.1 works on JDK 21+ for ordinary code), or pin
  an older format version. Set up the JDK explicitly in CI rather than relying on
  the runner default.
