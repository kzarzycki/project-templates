from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_agent_layer_generation import render


def fake_executable(directory: Path, name: str) -> None:
    path = directory / name
    path.write_text(
        "#!/bin/sh\n"
        'printf "%s" "$0" >> "$COMMAND_LOG"\n'
        'printf " %s" "$@" >> "$COMMAND_LOG"\n'
        'printf "\\n" >> "$COMMAND_LOG"\n'
    )
    path.chmod(0o755)


class AgentMiseTasksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = render(
            include_mise=True,
            include_agent_layer=True,
            include_fnox=True,
        )
        self.bin = Path(tempfile.mkdtemp(prefix="agent-task-bin-"))
        self.log = self.bin / "commands.log"
        for name in ("apm", "fnox", "claude", "codex"):
            fake_executable(self.bin, name)
        self.env = os.environ.copy()
        self.env.update(
            {
                "COMMAND_LOG": str(self.log),
                "MISE_CACHE_DIR": str(self.bin / "mise-cache"),
                "MISE_DATA_DIR": str(self.bin / "mise-data"),
                "MISE_OFFLINE": "true",
                "MISE_STATE_DIR": str(self.bin / "mise-state"),
                "MISE_TRUSTED_CONFIG_PATHS": str(self.project),
                "PATH": f"{self.bin}:{self.env['PATH']}",
            }
        )

    def run_task(self, task: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["mise", "run", "--skip-tools", task, "--", *arguments],
            cwd=self.project,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def commands(self) -> list[str]:
        return self.log.read_text().splitlines()

    def test_sync_uses_unfrozen_install_before_first_lock(self) -> None:
        result = self.run_task("agent-sync")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                f"{self.bin}/apm install --target claude,codex",
                f"{self.bin}/apm compile --target claude,codex",
            ],
            self.commands(),
        )

    def test_sync_uses_frozen_install_when_lock_exists(self) -> None:
        (self.project / "apm.lock.yaml").touch()

        result = self.run_task("agent-sync")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"{self.bin}/apm install --frozen --target claude,codex",
            self.commands()[0],
        )

    def test_launch_forwards_arguments_through_fnox(self) -> None:
        result = self.run_task("agent-claude", "--model", "test-model")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"{self.bin}/fnox exec --non-interactive --if-missing error -- "
            "claude --model test-model",
            self.commands()[0],
        )

    def test_check_calls_qualified_apm_and_fnox_commands(self) -> None:
        result = self.run_task("agent-check")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                f"{self.bin}/apm compile --validate --target claude,codex",
                f"{self.bin}/apm audit --ci --no-policy",
                f"{self.bin}/fnox check --all --non-interactive --if-missing error",
            ],
            self.commands(),
        )

    def test_launch_without_fnox_calls_agent_directly(self) -> None:
        project = render(
            include_mise=True,
            include_agent_layer=True,
            include_fnox=False,
        )

        result = subprocess.run(
            ["mise", "run", "--skip-tools", "agent-codex", "--", "--help"],
            cwd=project,
            env={**self.env, "MISE_TRUSTED_CONFIG_PATHS": str(project)},
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"{self.bin}/codex --help", self.commands()[0])


if __name__ == "__main__":
    unittest.main()
