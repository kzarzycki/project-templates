from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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

    def test_check_runs_tests_then_hooks_then_frozen_sync_once_locked(self) -> None:
        for name in ("uv", "pre-commit"):
            fake_executable(self.bin, name)
        (self.bin / "mise").symlink_to(MISE)
        (self.project / "apm.lock.yaml").touch()
        self.initialize_git()

        result = self.run_task("check")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                f"{self.bin}/uv run pytest --cov --cov-report=xml",
                f"{self.bin}/pre-commit run --all-files --show-diff-on-failure",
                f"{self.bin}/apm install --frozen --target claude,codex",
            ],
            self.commands()[:3],
        )

    def test_check_measures_changed_lines_against_the_commit_ci_passes(self) -> None:
        for name in ("uv", "pre-commit"):
            fake_executable(self.bin, name)
        (self.bin / "mise").symlink_to(MISE)
        self.initialize_git()
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.project, check=True, capture_output=True, text=True
        ).stdout.strip()

        for ref, compared in ((base, base), ("0" * 40, None), ("main", None)):
            with self.subTest(ref=ref):
                self.log.unlink(missing_ok=True)
                self.env["BASE_REF"] = ref

                result = self.run_task("check")

                self.assertEqual(0, result.returncode, result.stderr)
                diff_cover = [line for line in self.commands() if "diff-cover" in line]
                expected = [] if compared is None else [
                    f"{self.bin}/uv run diff-cover coverage.xml --compare-branch={compared} --fail-under=100"
                ]
                self.assertEqual(expected, diff_cover)

    def fake_github(self, ruleset: dict | None, allow_auto_merge: bool) -> Path:
        """A gh that keeps one repo's `main` ruleset and allow_auto_merge in a JSON file."""
        state = self.bin / "github.json"
        state.write_text(json.dumps({"ruleset": ruleset, "allow_auto_merge": allow_auto_merge}))
        gh = self.bin / "gh"
        gh.write_text(
            f"#!{sys.executable}\n"
            "import json, sys\n"
            "from pathlib import Path\n"
            f"state = Path({str(state)!r})\n"
            "data = json.loads(state.read_text())\n"
            "args = sys.argv[2:]\n"
            "method = args[args.index('-X') + 1] if '-X' in args else 'GET'\n"
            "path = next(a for a in args if a.startswith('repos/'))\n"
            "if path.endswith('/rulesets') and method == 'GET':\n"
            "    print(42 if data['ruleset'] else '')\n"
            "elif '/rulesets' in path and method == 'GET':\n"
            "    print(json.dumps(data['ruleset']))\n"
            "elif method in ('PUT', 'POST'):\n"
            "    data['ruleset'] = json.loads(Path(args[args.index('--input') + 1]).read_text())\n"
            "    print(42)\n"
            "elif method == 'DELETE':\n"
            "    data['ruleset'] = None\n"
            "elif method == 'PATCH':\n"
            "    data['allow_auto_merge'] = args[args.index('-F') + 1].split('=')[1] == 'true'\n"
            "else:\n"
            "    print(str(data['allow_auto_merge']).lower())\n"
            "state.write_text(json.dumps(data))\n"
        )
        gh.chmod(0o755)
        self.initialize_git()
        return state

    def restore(self) -> None:
        subprocess.run(["sh", ".git/merge-queue/restore.sh"], cwd=self.project, env=self.env, check=True)

    def test_merge_queue_restore_puts_back_the_ruleset_it_overwrote(self) -> None:
        original = {"name": "main", "rules": [{"type": "pull_request",
                                               "parameters": {"required_approving_review_count": 2}}]}
        state = self.fake_github(original, allow_auto_merge=False)

        for _ in range(2):  # a rerun keeps the first save
            result = self.run_task("merge-queue")
            self.assertEqual(0, result.returncode, result.stderr)
        applied = json.loads(state.read_text())
        self.assertNotEqual(original, applied["ruleset"])
        self.assertTrue(applied["allow_auto_merge"])

        self.restore()

        self.assertEqual({"ruleset": original, "allow_auto_merge": False}, json.loads(state.read_text()))

    def fail_once(self, condition: str) -> None:
        """The fake gh exits 1 the first time `condition` holds."""
        gh = self.bin / "gh"
        marker = self.bin / "failed-once"
        gh.write_text(gh.read_text().replace(
            "if path.endswith('/rulesets') and method == 'GET':",
            f"if ({condition}) and not Path({str(marker)!r}).exists():\n"
            f"    Path({str(marker)!r}).touch()\n"
            "    sys.exit('simulated HTTP 503')\n"
            "if path.endswith('/rulesets') and method == 'GET':",
        ))

    def test_merge_queue_failed_snapshot_read_is_retaken_on_retry(self) -> None:
        original = {"name": "main", "rules": [{"type": "pull_request",
                                               "parameters": {"required_approving_review_count": 2}}]}
        for condition in ("method == 'GET' and path.endswith('/rulesets/42')",
                          "method == 'GET' and path.endswith('{repo}')"):
            with self.subTest(failed_read=condition):
                (self.bin / "failed-once").unlink(missing_ok=True)
                shutil.rmtree(self.project / ".git", ignore_errors=True)
                state = self.fake_github(original, allow_auto_merge=True)
                self.fail_once(condition)

                self.assertNotEqual(0, self.run_task("merge-queue").returncode)
                retry = self.run_task("merge-queue")
                self.assertEqual(0, retry.returncode, retry.stderr)
                self.restore()

                self.assertEqual({"ruleset": original, "allow_auto_merge": True}, json.loads(state.read_text()))

    def test_merge_queue_restore_deletes_only_the_ruleset_it_created(self) -> None:
        state = self.fake_github(None, allow_auto_merge=True)

        for _ in range(2):
            result = self.run_task("merge-queue")
            self.assertEqual(0, result.returncode, result.stderr)
        self.assertIsNotNone(json.loads(state.read_text())["ruleset"])

        self.restore()

        self.assertEqual({"ruleset": None, "allow_auto_merge": True}, json.loads(state.read_text()))

    def test_check_passes_in_a_generated_python_project(self) -> None:
        # Real toolchain: uv, pre-commit and network for the hook repos.
        project = render()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=project, check=True)
        subprocess.run(["git", "add", "-A"], cwd=project, check=True)
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
                "scaffold",
            ],
            cwd=project,
            check=True,
        )

        result = subprocess.run(
            [MISE, "run", "--skip-tools", "check"],
            cwd=project,
            env={**os.environ, "MISE_TRUSTED_CONFIG_PATHS": str(project)},
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("no apm.lock.yaml yet", result.stderr)


if __name__ == "__main__":
    unittest.main()
