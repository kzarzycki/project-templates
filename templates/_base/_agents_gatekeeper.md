# Gatekeeper policy

The gatekeeper (`mise run loop:approvals`, `loop:land`) reads this file's `## Policy` block as the
project's standing policy; the engineering loop's `docs/agents/loop.md` keeps the prose. It is YAML:
`key: value` under a section name, a list one item per line. Quote a value that starts with `*` or
reads as another type (`no`, `on`, `1.10`). A key or section the gatekeeper doesn't know is refused,
naming it. The gatekeeper skill's `policy.md` has every key; loop.md § Approvals says what the seed's
settings do.

## Policy

```yaml
spec:
  # specs approved by policy, with no owner record; any other waits for the owner
  auto:
    - bug
    - follow-up
    - sub-issue
{% if not include_ci %}
loop:
  ci: false
{% endif %}
# practice:
#   the skill that fills a stage this project changes, one key each, such as
#   spec: brainstorming; a stage left out runs its default

risk:
  verifier: true
  paths:
    - .github/**
    - CODEOWNERS
    - docs/agents/gatekeeper.md
    - docs/agents/loop.md

# bot:
#   renovate:   # deps:renovate's routine group, run on your token: see § Approvals
#     branch: renovate/
#     paths:
#       - uv.lock
#       - package-lock.json
#       - pyproject.toml
#       - package.json
#       - mise.toml
#       - .github/workflows/*.yml

land:
{% if merge_queue %}  queue: github   # main's ruleset requires GitHub's merge queue: `loop:land` enqueues each landable PR
{% else %}  # No queue on main: `land` merges each landable PR itself, on the verifier's record of its head.
{% endif %}  # Batch keys, at their defaults: batch_wait_seconds (0), wait (2h), merge_commit_heads (none), where (both).
  # See the gatekeeper's policy.md for each.

select:
  # Checks whose pass is never reused, because they read what no record key covers (a live service,
  # a credential that rotates, the host itself): each a `gate_steps` step's `name` or `command`, or the
  # `gate` command. This project's merge check is `mise run check:all`, which reads only the tree.
  unkeyed: []
```
