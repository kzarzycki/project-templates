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

The gates are the merge approval: a PR whose proofs hold merges with no
person's label. Where a person must approve too: one rule per line as
`- <point>: <condition>`, where the point is spec, plan or merge. A merge rule
asks for the owner's `approved:merge` label on the PR; a push removes it.
`mise run loop:approvals` reads `always`, `size:L or larger`, `component <name>`,
`category <name>` and `path <glob>` (read from the PR's files), joined by `or`;
the loop judges any other words, and a merge condition the gate can't read asks
for the label. The person approves by adding the `approved:<point>` label. The
rule below asks for it on a change to CI, hooks, tasks, the agent pack or these
files; replacing it with `- merge: always` restores a label on every merge.
Required reviews and code owners go in branch protection and `CODEOWNERS`, which
the loop obeys. "None" is an answer.

- merge: path .github/** or path .pre-commit-config.yaml or path mise.toml or path apm.yml or path docs/agents/** or path CODEOWNERS

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
