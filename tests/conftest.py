"""Run under a git hook (pre-push in a linked worktree), git exports GIT_DIR and friends, and every
`git` these tests run in a fixture repo would act on the outer repository instead. Clear them once,
before any test copies the environment."""

import os

for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX", "GIT_COMMON_DIR"):
    os.environ.pop(name, None)
