"""The claude-cloud setup script: mise comes from npm, a failed step is logged and never fails the script."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_agent_layer_generation import LEAVES, render

SCRIPT = ".claude/claude-cloud-setup.sh"


class CloudSetupTest(unittest.TestCase):
    def run_script(self, script: Path, *, npm_ok: bool, mise_ok: bool) -> subprocess.CompletedProcess[str]:
        home = Path(tempfile.mkdtemp(prefix="cloud-setup-test-"))
        self.addCleanup(shutil.rmtree, home, True)
        bin_dir = home / "bin"
        bin_dir.mkdir()
        for name, ok in (("npm", npm_ok), ("mise", mise_ok)):
            stub = bin_dir / name
            stub.write_text(f"#!/bin/sh\necho \"{name} $*\" >> '{home}/calls'\nexit {0 if ok else 1}\n")
            stub.chmod(0o755)
        env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin"}
        return subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=60)

    def test_every_template_installs_mise_from_npm_and_never_fails(self) -> None:
        for project_type, answers in LEAVES:
            with self.subTest(project_type=project_type, **answers):
                script = render(project_type, **answers) / SCRIPT
                text = script.read_text()
                self.assertNotIn("mise.run", text)
                self.assertIn("npm install -g -s @jdxcode/mise", text)
                self.assertLess(text.index("prefer_offline true"), text.index("mise install"))
                self.assertIn("kzarzycki/agent-skills#962", text)
                self.assertEqual(subprocess.run(["bash", "-n", str(script)]).returncode, 0)

    def test_failed_steps_are_logged_and_the_script_exits_zero(self) -> None:
        script = render("software/python") / SCRIPT
        out = self.run_script(script, npm_ok=False, mise_ok=False)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("FAILED: mise install", out.stdout)

    def test_succeeding_stubs_log_no_failure(self) -> None:
        script = render("software/python") / SCRIPT
        out = self.run_script(script, npm_ok=True, mise_ok=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("FAILED", out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
