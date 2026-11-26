# Gatekeeper

The policy `approvals.py` reads. This repo's own: every merge is the owner's, at any risk level. The copy generated projects receive lives under `templates/` and is separate.

## Policy

```yaml
loop:
  # the whole root unittest suite CI runs (job `verify`): with no base the selector lists every tests.<name> module, as the nightly run does (tests/ has no __init__.py, so `unittest discover` finds nothing). The repo has no root mise.toml, so the default `mise run check:all` can't run
  gate: sh -c 'mise exec github:microsoft/apm@0.33.0 -- uv run --with PyYAML==6.0.3 -- python3 -m unittest $(python3 scripts/affected_tests.py)'

levels:
  low: {merge: owner}
  high: {merge: owner}
```
