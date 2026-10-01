# Loop facts

The `engineering-loop` skill reads this file at Proof, Verify, Land, Accept and
Clean up. Replace each prompt with this project's fact; keep the headings.

## Owner

Who owns this repository and answers the loop's questions (a GitHub handle).

## Proof on a branch

The commands that run this change where a person can see it working before
review, and where the result is (a URL, a file, a command's output).

## Acceptance references

What a new result is checked against, in order of preference: references the
code did not produce, such as the owner's evidence, an external source, a
recomputation or an invariant.

## Landing exceptions

Changes that wait for the owner's go-ahead on the PR instead of landing on a
green gate and a clear verifier. "None" is an answer.

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
