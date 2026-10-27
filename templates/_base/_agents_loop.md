# Loop facts

The `engineering-loop` skill reads this file at every step but the gate.
Replace each prompt with this project's fact; keep the headings.

## Settings

`mise run loop:approvals` reads this block, the engineering loop's settings
(its SKILL.md § Settings has every key). It is YAML: `key: value` under a
section name, a list one item per line. Quote a value that starts with `*` or
reads as another type (`no`, `on`, `1.10`). A key or section the loop doesn't
know is refused, naming it. § Approvals says what the seed's settings do.

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
```

## Owner

Who owns this repository and answers the loop's questions (a GitHub handle).

## Proof on a branch

The commands that run this change where a person can see it working before
review, and where the result is (a URL, a file, a command's output).

## Acceptance references

What a new result is checked against, in order of preference: references the
code did not produce, such as the owner's evidence, an external source, a
recomputation or an invariant.

## Approvals

Only people approve; the rest is the standing policy in § Settings, which
`mise run loop:approvals` evaluates. `spec.auto` with `bug`, `follow-up` and
`sub-issue` approves the spec of a bug, a `Found while #<n>` follow-up, or a writer's sub-issue of an epic the
owner approved; any other spec waits for the owner. A PR lands on its gates
unless it is high risk: `risk:high` on the PR or its issue, the `risk` rule
matches, or the verifier's cap was reached with a blocker or major open. A
high-risk merge waits for the owner's `approved:merge` label, added after the
head's push.

The seed's `risk` rule lets the verifier judge every change and keeps a few
paths the owner's whatever it says. `verifier: true` holds when the verifier's
newest pass on the head says anything but `Risk: low`, so the owner sees only
what no check can settle. The paths hold on their own: CI's workflows and
rulesets under `.github/`, `CODEOWNERS`, and this file, since each decides what
the gates require and who approves. `risk` also takes `labels` (such as
`size:XL` or `area:<name>`, one per line) and `always: true`, which holds every
merge for the owner. `cap: <n>` under `loop` changes the verifier's pass cap
from the skill's default, and a `plan` section with `labels` asks for the
owner's approval of a matching plan. Required reviews go in branch protection,
which the loop obeys. The template ships no `CODEOWNERS`: GitHub would ask its
owners to review every PR the loop opens. Keep paths to a team with a push
ruleset instead, and ask someone for a review by name when it needs one.

Three settings the seed leaves out change this. `auto: true` under `spec`, in place of
the list, approves every spec by policy, epics included, except
one the `risk` rule matches or one opened by an account without write access,
which waits for the owner; the rule then holds the spec instead of the merge,
so that merge needs no `approved:merge`, but for its `verifier` term, which the
gate still judges at the merge. A `signoff` section, read as `risk` is, has
the owner sign off a matching change in use after it lands: its spec says
`Sign-off: owner` or `Sign-off: none`, and its PR links the issue with
`Implements #<n>`, which leaves it open for the sign-off. `opt_out: true` under
`loop` lets a developer whose personal instructions say
`Engineering loop: off` keep their PRs out of the loop: a PR with no loop trail
passes `loop:approvals`, its author merges it, and no risk rule holds it.
Renovate (`mise run deps:renovate`) labels `verify` the updates an agent
reviews: the template, the agent packages and every major. Its routine group
runs on the developer's token, so its PRs are the developer's and a verifier
reviews them too. The commented `bot.renovate` entry above exempts them
instead: it names Renovate by its `renovate/` branch, and holds only when every
commit is the developer's (set Renovate's `gitAuthor` to them) and every file
matches its `paths`. The `risk` rule still holds a match on its own paths, so
a workflow update keeps waiting for the owner until `.github/**` narrows to
what it means to keep, such as `.github/rulesets/**`.
{% if not include_ci %}
`ci: false` says this project has no CI: the merge proof is the local check
`uv run .agents/skills/engineering-loop/scripts/approvals.py local-ci <pr>`
records on the head. A check that reads environment variables names them in
`local_ci_env`, one per line.
{% endif %}
## Risk criteria

Optional. What makes a change risky here beyond the `risk` rule, in words,
which the verifier reads when it judges a change's risk.

## In use

Who and what uses this project, and so how a finding is judged: by what a user
or the pipeline hits in use, or also by what a hostile input could do.

## Worktree

The command that creates a worktree for a branch, and anything to run before
removing one.

## Ledger

The path of the file that lists known limitations, one line each.

## Verifier checklist

The path of any checks the verifier runs beyond the gate, or "None".
