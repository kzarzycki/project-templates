#!/usr/bin/env python3
"""Print the root test modules a change touches, one dotted name per line.

Usage: affected_tests.py [BASE_SHA]

Needs only git and the standard library. With no BASE_SHA, or when git can't
diff against it, every test module is selected: the run can't tell what changed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# A change here can alter any test's result, so every module runs.
ALL = (
    "scripts/affected_tests.py", ".github/", "tests/conftest.py", "tests/fixtures/",
    "tests/test_agent_layer_generation.py",  # its render() helper is imported by the other tests
    "copier.yml", "_post_gen.sh", "templates/", "skills/",
    "README.md", "examples/",  # test_agent_layer_generation asserts on both
)
# The tests that read these files; nothing else in the suite looks at them.
CHEAP = ("docs/", ".claude-plugin/", ".gitignore")


def all_modules() -> list[str]:
    return sorted(f"tests.{p.stem}" for p in (ROOT / "tests").glob("test_*.py"))


def select(changed: list[str]) -> list[str]:
    modules: set[str] = set()
    for path in changed:
        if path.startswith(ALL):
            return all_modules()
        if path.startswith("tests/test_") and path.endswith(".py"):
            modules.add("tests." + Path(path).stem)
        elif path.startswith(CHEAP):
            modules.add("tests.test_version_contract")
        else:
            return all_modules()
    return sorted(m for m in modules if (ROOT / m.replace(".", "/")).with_suffix(".py").exists()) \
        or ["tests.test_version_contract"]


def changed_files(base: str) -> list[str] | None:
    # Two-dot (endpoints), so a rollback or force push shows what changed; --no-renames lists
    # both paths of a move, so a template moved into docs/ still selects every module.
    done = subprocess.run(["git", "-C", str(ROOT), "diff", "--name-only", "--no-renames", base, "HEAD"],
                          capture_output=True, text=True)
    return done.stdout.split() if done.returncode == 0 else None


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else ""
    changed = changed_files(base) if base.strip("0") else None
    print("\n".join(all_modules() if changed is None else select(changed)))
