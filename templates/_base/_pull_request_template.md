{%- if include_mise and include_agent_layer and include_engineering_workflow %}
## Summary

<!-- The smallest view of the change: pseudocode, a call or file tree, a diagram or a shaped diff (the `pr` skill). `Closes #<issue>` for the issue it delivers. -->

## Evidence

<!-- Before and after: a screenshot, a demo video (the `demo` skill), or the test that failed and now passes.{% if loop_enabled %} The merge gate rejects a PR without this section.{% endif %} -->

## Merge Danger

**Door:** <!-- one-way or two-way: can the merge be walked back? -->

**Blast Radius:** <!-- one word: what the merge could affect -->
{%- else %}
## What & why

<!-- What does this change do, and why? Link any related issue. -->

## Checklist

- [ ] Commits follow Conventional Commits
- [ ] Checks pass locally (`pre-commit run --all-files`)
- [ ] Docs / ADR updated if behavior or a decision changed
{%- endif %}
