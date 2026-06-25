# project-templates

Copier templates for new repositories, with my conventions baked in — git init,
pinned pre-commit hooks, `CLAUDE.md`, CI, and a language toolchain — plus the
`bootstrap-project` Claude Code skill that drives them.

This repo is two things at once, read by two consumers that never collide:

- a **Copier template** — `copier copy gh:kzarzycki/project-templates <dest>`
  renders only the selected template subdirectory (`new-project/` today).
- a **Claude Code plugin** — `.claude-plugin/` + `skills/bootstrap-project/`,
  loaded via the agent-skills marketplace. Copier never sees `skills/`.

## Use it directly

```bash
uv tool install copier pre-commit
copier copy --trust gh:kzarzycki/project-templates my-tool \
  --data project_name=my-tool --data language=python
```

`language` is `python` | `node` | `content`. See `copier.yml` for every
question and its default. Post-generation tasks (`_post_gen.sh`) run git init,
install deps, install hooks, and make the first commit.

## Use it via Claude

Ask Claude to "start a new python project called my-tool" — the
`bootstrap-project` skill gathers name + language and runs the same copier call
non-interactively.

## Update an existing project

When a template improves, pull it into a project generated from it:

```bash
cd my-tool && copier update --trust
```

## Templates

| Template | Subdir | For |
|---|---|---|
| new-project | `new-project/` | A code/content repo (Python, Node/TS, or docs) |

Adding another: drop a sibling subdir, add a `template_kind` question, and
switch `_subdirectory` to `"{{ template_kind }}"`.
