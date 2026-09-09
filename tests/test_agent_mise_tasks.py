from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_agent_layer_generation import render


MISE = shutil.which("mise")
assert MISE is not None


def fake_executable(directory: Path, name: str) -> None:
    path = directory / name
    script = (
        "#!/bin/sh\n"
        'printf "%s" "$0" >> "$COMMAND_LOG"\n'
        'printf " %s" "$@" >> "$COMMAND_LOG"\n'
        'printf "\\n" >> "$COMMAND_LOG"\n'
    )
    if name == "apm":
        script += (
            'if [ "${1:-}" = "compile" ] && '
            '[ -n "${FAKE_APM_COMPILED_PATH:-}" ]; then\n'
            '  printf "changed by compile\\n" > "$FAKE_APM_COMPILED_PATH"\n'
            "fi\n"
            'if [ "${1:-}" = "compile" ] && '
            '[ -n "${FAKE_APM_ORPHAN_PATH:-}" ]; then\n'
            '  rm -f "$FAKE_APM_ORPHAN_PATH"\n'
            "fi\n"
        )
    path.write_text(script)
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
                "PATH": f"{self.bin}:/usr/bin:/bin",
            }
        )

    def run_task(self, task: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [MISE, "run", "--skip-tools", task, "--", *arguments],
            cwd=self.project,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def commands(self) -> list[str]:
        if not self.log.exists():
            return []
        return self.log.read_text().splitlines()

    def initialize_git(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
        subprocess.run(["git", "add", "."], cwd=self.project, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "--no-verify",
                "-qm",
                "fixture",
            ],
            cwd=self.project,
            check=True,
        )

    def test_sync_default_converges_and_validates(self) -> None:
        result = self.run_task("agent-sync")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                f"{self.bin}/apm install --target claude,codex",
                f"{self.bin}/apm compile --clean",
                f"{self.bin}/apm compile --validate",
                f"{self.bin}/apm audit --ci --no-policy",
                f"{self.bin}/fnox check --all --non-interactive --if-missing error",
            ],
            self.commands(),
        )

    def test_sync_missing_apm_explains_how_to_install_it(self) -> None:
        (self.bin / "apm").unlink()

        result = self.run_task("agent-sync")

        self.assertEqual(127, result.returncode)
        self.assertIn(
            "error: apm 0.30.0 is required; run 'mise install'",
            result.stderr,
        )

    def test_sync_targets_manifest_without_agent_clis(self) -> None:
        (self.bin / "claude").unlink()
        (self.bin / "codex").unlink()
        manifest = self.project / "apm.yml"
        manifest.write_text(
            manifest.read_text().replace(
                "targets:\n- claude\n- codex\n",
                "targets:\n  # Keep this list independent of installed CLIs.\n"
                "  - claude\n"
                "\n"
                "  - codex  # Existing adapter.\n"
                "  - copilot\n",
            )
        )

        result = self.run_task("agent-sync")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"{self.bin}/apm install --target claude,codex,copilot",
            self.commands()[0],
        )

    def test_sync_refresh_re_resolves_before_convergence(self) -> None:
        result = self.run_task("agent-sync", "--refresh")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"{self.bin}/apm update --yes --target claude,codex",
            self.commands()[0],
        )

    def test_sync_frozen_checks_integrity_before_and_after_compile(self) -> None:
        (self.project / "apm.lock.yaml").touch()
        self.initialize_git()

        result = self.run_task("agent-sync", "--frozen")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                f"{self.bin}/apm install --frozen --target claude,codex",
                f"{self.bin}/apm audit --ci --no-policy",
                f"{self.bin}/apm compile --clean",
                f"{self.bin}/apm compile --validate",
                f"{self.bin}/apm audit --ci --no-policy",
                f"{self.bin}/fnox check --all --non-interactive --if-missing error",
            ],
            self.commands(),
        )

    def test_sync_frozen_rejects_compilation_changes(self) -> None:
        (self.project / "apm.lock.yaml").touch()
        compiled = self.project / "src/AGENTS.md"
        compiled.parent.mkdir(parents=True, exist_ok=True)
        compiled.write_text('model = "before"\n')
        self.initialize_git()
        self.env["FAKE_APM_COMPILED_PATH"] = str(compiled)

        result = self.run_task("agent-sync", "--frozen")

        self.assertEqual(1, result.returncode)
        self.assertIn("frozen agent configuration changed", result.stderr)
        self.assertIn("src/AGENTS.md", result.stderr)

    def test_sync_frozen_rejects_removed_nested_orphan(self) -> None:
        (self.project / "apm.lock.yaml").touch()
        orphan = self.project / "src/AGENTS.md"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_text("generated before source removal\n")
        self.initialize_git()
        self.env["FAKE_APM_ORPHAN_PATH"] = str(orphan)

        result = self.run_task("agent-sync", "--frozen")

        self.assertEqual(1, result.returncode)
        self.assertIn("frozen agent configuration changed", result.stderr)
        self.assertIn("src/AGENTS.md", result.stderr)

    def test_sync_rejects_unknown_or_combined_modes_without_running_apm(self) -> None:
        for arguments in (("--unknown",), ("--refresh", "--frozen")):
            with self.subTest(arguments=arguments):
                if self.log.exists():
                    self.log.unlink()

                result = self.run_task("agent-sync", *arguments)

                self.assertNotEqual(0, result.returncode)
                if arguments == ("--unknown",):
                    self.assertIn("unexpected word: --unknown", result.stderr)
                else:
                    self.assertIn(
                        "error: --refresh and --frozen cannot be combined",
                        result.stderr,
                    )
                self.assertEqual([], self.commands())

    def test_launch_forwards_arguments_through_fnox(self) -> None:
        result = self.run_task("agent-claude", "--model", "test-model")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"{self.bin}/fnox exec --non-interactive --if-missing error -- "
            "claude --model test-model",
            self.commands()[0],
        )

    def test_launch_without_fnox_calls_agent_directly(self) -> None:
        project = render(
            include_mise=True,
            include_agent_layer=True,
            include_fnox=False,
        )

        result = subprocess.run(
            [MISE, "run", "--skip-tools", "agent-codex", "--", "--help"],
            cwd=project,
            env={**self.env, "MISE_TRUSTED_CONFIG_PATHS": str(project)},
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"{self.bin}/codex --help", self.commands()[0])


if __name__ == "__main__":
    unittest.main()
