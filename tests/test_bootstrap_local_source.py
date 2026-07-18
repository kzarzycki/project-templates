from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BootstrapLocalSourceTest(unittest.TestCase):
    def test_skill_and_wrapper_advertise_every_copier_project_type(self) -> None:
        copier = (ROOT / "copier.yml").read_text()
        skill = (ROOT / "skills/bootstrap-project/SKILL.md").read_text()
        wrapper = (ROOT / "skills/bootstrap-project/scripts/bootstrap.sh").read_text()
        project_types = (
            "software/python",
            "software/node",
            "software/java",
            "data/dbt",
            "authoring/content",
            "ai/skills",
            "ai/mcp",
            "infra/terraform",
        )

        for project_type in project_types:
            self.assertIn(project_type, copier)
            self.assertIn(project_type, skill)
            self.assertIn(project_type, wrapper)
        self.assertIn("terraform_version", skill)
        self.assertIn("terraform_version", wrapper)

    def test_local_source_uses_current_head(self) -> None:
        scratch = Path(tempfile.mkdtemp(prefix="bootstrap-source-test-"))
        fake_bin = scratch / "bin"
        fake_bin.mkdir()
        argument_log = scratch / "arguments.txt"
        copier = fake_bin / "copier"
        copier.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$COPIER_ARGUMENT_LOG"\n')
        copier.chmod(0o755)
        env = os.environ.copy()
        env.update(
            {
                "BOOTSTRAP_TEMPLATE_SRC": str(ROOT),
                "COPIER_ARGUMENT_LOG": str(argument_log),
                "PATH": f"{fake_bin}:{env['PATH']}",
            }
        )

        result = subprocess.run(
            [
                str(ROOT / "skills/bootstrap-project/scripts/bootstrap.sh"),
                "--name",
                "source-test",
                "--type",
                "software/python",
                "--dest",
                str(scratch / "out"),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        arguments = argument_log.read_text().splitlines()
        self.assertIn("--vcs-ref=HEAD", arguments)
        self.assertLess(arguments.index("--vcs-ref=HEAD"), arguments.index(str(ROOT)))


if __name__ == "__main__":
    unittest.main()
