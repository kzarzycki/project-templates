# Loop facts

The `engineering-loop` skill reads this file at every step but the gate.
Replace each prompt with this project's fact; keep the headings.

## Owner

Who owns this repository and answers the loop's questions (a GitHub handle).

## Proof on a branch

The commands that run this change where a person can see it working before
review, and where the result is (a URL, a file, a command's output).

## Acceptance references

What a new result is checked against, in order of preference: references the
code did not produce, such as the owner's evidence, an external source, a
recomputation or an invariant.

## Practice

The skill that fills each stage this project changes, one line each, such as
`Spec: <skill>`, or "Default".

## Approvals

Only people approve; the rest is this standing policy, which
`mise run loop:approvals` evaluates. `spec: auto unless risk` approves the spec
of a bug, a `Found while #<n>` follow-up, or a writer's sub-issue of an epic the
owner approved; any other spec waits for the owner. `merge: auto unless risk`
lands a PR on its gates unless it is high risk: `risk:high` on the PR or its
issue, a `risk:` rule below matches, or the verifier's cap was reached with a
blocker or major open. A high-risk merge waits for the owner's
`approved:merge` label, added after the head's push. A `risk:` condition reads
`always`, `size:L or larger`, `component <name>`, `category <name>` and
`path <glob>`, joined by `or`; a condition the gate can't read matches. The rule
below marks a change to CI, hooks, tasks, the agent pack or these files as high
risk; `risk: always` restores a label on every merge. A line `cap: <n>` changes
the verifier's pass cap from the skill's default, and a `plan: <condition>`
line asks for the owner's approval of a matching plan. Required reviews and code
owners go in branch protection and `CODEOWNERS`, which the loop obeys.

- spec: auto unless risk
- merge: auto unless risk
- risk: path .github/** or path .pre-commit-config.yaml or path mise.toml or path apm.yml or path docs/agents/** or path CODEOWNERS

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
