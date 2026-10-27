from __future__ import annotations

import hashlib
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
            'if [ "${1:-}" = "audit" ]; then exit "${FAKE_APM_AUDIT_EXIT:-0}"; fi\n'
            # A release deployed over an edited file, then the update fails or its caller dies.
            'if [ "${1:-}" = "update" ] && '
            '[ -n "${FAKE_APM_UPDATE_WRITES:-}" ]; then\n'
            '  printf "new release\\n" > "$FAKE_APM_UPDATE_WRITES"\n'
            '  if [ -n "${FAKE_APM_UPDATE_KILLS_CALLER:-}" ]; then kill -9 "$PPID"; fi\n'
            '  exit "${FAKE_APM_UPDATE_EXIT:-0}"\n'
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
        # The tasks run the pack's scripts with `uv run`; this one runs a fake script with python3, logging nothing.
        uv = self.bin / "uv"
        uv.write_text('#!/bin/sh\n[ "$1" = run ] || exit 2\nshift\nexec python3 "$@"\n')
        uv.chmod(0o755)
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
        result = self.run_task("agent-sync")  # the old name runs as an alias

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

        result = self.run_task("agent:sync")

        self.assertEqual(127, result.returncode)
        self.assertIn(
            "error: apm 0.33.0 is required; run 'mise install'",
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

        result = self.run_task("agent:sync")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"{self.bin}/apm install --target claude,codex,copilot",
            self.commands()[0],
        )

    def test_sync_refresh_re_resolves_before_convergence(self) -> None:
        result = self.run_task("agent:sync", "--refresh")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"{self.bin}/apm update --yes --target claude,codex",
            self.commands()[0],
        )

    def test_sync_frozen_checks_integrity_before_and_after_compile(self) -> None:
        (self.project / "apm.lock.yaml").touch()
        self.initialize_git()

        result = self.run_task("agent:sync", "--frozen")

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

        result = self.run_task("agent:sync", "--frozen")

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

        result = self.run_task("agent:sync", "--frozen")

        self.assertEqual(1, result.returncode)
        self.assertIn("frozen agent configuration changed", result.stderr)
        self.assertIn("src/AGENTS.md", result.stderr)

    def test_sync_rejects_unknown_or_combined_modes_without_running_apm(self) -> None:
        for arguments in (("--unknown",), ("--refresh", "--frozen")):
            with self.subTest(arguments=arguments):
                if self.log.exists():
                    self.log.unlink()

                result = self.run_task("agent:sync", *arguments)

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
        result = self.run_task("agent:claude", "--model", "test-model")

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
            [MISE, "run", "--skip-tools", "agent:codex", "--", "--help"],
            cwd=project,
            env={**self.env, "MISE_TRUSTED_CONFIG_PATHS": str(project)},
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"{self.bin}/codex --help", self.commands()[0])

    def test_check_agents_runs_the_frozen_sync_once_locked(self) -> None:
        (self.bin / "mise").symlink_to(MISE)

        before = self.run_task("check:agents")
        self.assertEqual(0, before.returncode, before.stderr)
        self.assertIn("no apm.lock.yaml yet", before.stderr)
        self.assertEqual([], self.commands())

        (self.project / "apm.lock.yaml").touch()
        self.initialize_git()
        locked = self.run_task("check:agents")
        self.assertEqual(0, locked.returncode, locked.stderr)
        self.assertEqual(f"{self.bin}/apm install --frozen --target claude,codex", self.commands()[0])

    def use_vendored_project(self) -> None:
        self.project = render(agent_layer_mode="vendored", include_fnox=False)
        self.env["MISE_TRUSTED_CONFIG_PATHS"] = str(self.project)
        # agent:sync runs agent:intake -- --check through mise.
        (self.bin / "mise").symlink_to(MISE)

    def drift(self, *paths: str) -> None:
        """A lock whose recorded hash of each path is the pack's copy, so the file on disk differs from it.

        Like APM's, it lists each file's directory too."""
        pristine = hashlib.sha256(b"pristine\n").hexdigest()
        (self.project / "apm.lock.yaml").write_text(
            "dependencies:\n- repo_url: test/engineering\n  deployed_files:\n"
            + "".join(f"  - {path}\n" for path in sorted({str(Path(path).parent) for path in paths} | set(paths)))
            + "  deployed_file_hashes:\n"
            + "".join(f"    {path}: sha256:{pristine}\n" for path in paths)
        )

    def test_vendored_sync_installs_and_prunes_without_compiling(self) -> None:
        self.use_vendored_project()

        result = self.run_task("agent:sync")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                f"{self.bin}/apm install --target claude,codex",
                f"{self.bin}/apm prune",
                f"{self.bin}/apm audit --ci --no-policy",
            ],
            self.commands(),
        )

    def test_vendored_sync_refuses_over_a_drifted_file_naming_it_and_intake(self) -> None:
        self.use_vendored_project()
        self.drift(".claude/skills/wayfinder/SKILL.md")

        for arguments in ((), ("--refresh",), ("--frozen",)):
            with self.subTest(arguments=arguments):
                self.log.unlink(missing_ok=True)

                result = self.run_task("agent:sync", *arguments)

                self.assertEqual(1, result.returncode, result.stderr)
                self.assertIn(".claude/skills/wayfinder/SKILL.md differs from the pack's copy", result.stderr)
                self.assertIn("mise run agent:intake", result.stderr)
                self.assertEqual([], self.commands())

    def test_vendored_sync_refuses_while_a_patch_is_unresolved(self) -> None:
        self.use_vendored_project()
        path = ".claude/skills/wayfinder/SKILL.md"
        self.drift(path)
        skill = self.project / path
        skill.parent.mkdir(parents=True)
        skill.write_text("edited\n")
        patch = self.project / ".agent-intake" / f"{path}.patch"
        patch.parent.mkdir(parents=True)
        patch.write_text("-pristine\n+edited\n")
        digest = hashlib.sha256(b"edited\n").hexdigest()
        (self.project / ".agent-intake/intaken").write_text(f"{digest}  {path}\n")

        refused = self.run_task("agent:sync")

        self.assertEqual(1, refused.returncode, refused.stderr)
        self.assertIn(f".agent-intake/{path}.patch is unresolved", refused.stderr)
        self.assertNotIn("differs from the pack's copy", refused.stderr)

        patch.unlink()  # dropped: the install restores the pack's copy
        self.log.unlink(missing_ok=True)
        dropped = self.run_task("agent:sync")

        self.assertEqual(0, dropped.returncode, dropped.stderr)
        self.assertIn(f"{self.bin}/apm install --target claude,codex", self.commands())
        self.assertFalse((self.project / ".agent-intake").exists())

    def test_vendored_sync_refuses_an_edit_made_after_intake(self) -> None:
        self.use_vendored_project()
        path = ".claude/skills/wayfinder/SKILL.md"
        self.drift(path)
        skill = self.project / path
        skill.parent.mkdir(parents=True)
        skill.write_text("edited again\n")
        (self.project / ".agent-intake").mkdir()
        digest = hashlib.sha256(b"edited\n").hexdigest()
        (self.project / ".agent-intake/intaken").write_text(f"{digest}  {path}\n")

        result = self.run_task("agent:sync")

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn(f"{path} differs from the pack's copy", result.stderr)

    def test_intake_refuses_a_lock_without_the_hash_its_drift_check_needs(self) -> None:
        self.use_vendored_project()
        path = ".claude/skills/wayfinder/SKILL.md"
        self.drift(path)
        lock = self.project / "apm.lock.yaml"
        lock.write_text(lock.read_text().split("  deployed_file_hashes:")[0])

        for task, arguments in (("agent:sync", ()), ("agent:intake", ()), ("agent:intake", ("--refresh",))):
            with self.subTest(task=task, arguments=arguments):
                self.log.unlink(missing_ok=True)

                result = self.run_task(task, *arguments)

                self.assertEqual(1, result.returncode, result.stderr)
                self.assertIn(f"apm.lock.yaml records no hash for .claude/skills/wayfinder, {path},", result.stderr)
                self.assertNotIn("no unresolved patch", result.stdout)
                self.assertEqual([], self.commands())

    def test_intake_refuses_a_lock_hash_line_it_cannot_read(self) -> None:
        self.use_vendored_project()
        self.drift(".claude/skills/wayfinder/SKILL.md")
        lock = self.project / "apm.lock.yaml"
        lock.write_text(lock.read_text().replace("sha256:", "md5:"))

        result = self.run_task("agent:intake")

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("apm.lock.yaml: cannot read the deployed file hash line", result.stderr)

    def dropped_edit(self, edit: bytes, on_disk: bytes) -> Path:
        """A dropped edit to a file the pack no longer ships: the ledger holds it, no patch, the lock omits it.

        The lock deploys one other skill, untouched, so .claude/skills is a skill root."""
        path = ".claude/skills/wayfinder/reference.md"
        other = ".claude/skills/other/SKILL.md"
        self.drift(other)
        (self.project / other).parent.mkdir(parents=True)
        (self.project / other).write_text("pristine\n")
        skill = self.project / path
        skill.parent.mkdir(parents=True)
        skill.write_bytes(on_disk)
        (self.project / ".agent-intake").mkdir()
        (self.project / ".agent-intake/intaken").write_text(f"{hashlib.sha256(edit).hexdigest()}  {path}\n")
        return skill

    def test_vendored_sync_refuses_to_remove_a_dropped_file_edited_again(self) -> None:
        self.use_vendored_project()
        skill = self.dropped_edit(b"edited\n", b"edited again\n")

        result = self.run_task("agent:sync")

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn(".claude/skills/wayfinder/reference.md changed after intake took in its dropped edit", result.stderr)
        self.assertEqual(b"edited again\n", skill.read_bytes())
        self.assertNotIn(f"{self.bin}/apm install --target claude,codex", self.commands())

    def test_vendored_sync_keeps_the_intake_state_until_its_audit_passes(self) -> None:
        self.use_vendored_project()
        skill = self.dropped_edit(b"edited\n", b"edited\n")
        self.env["FAKE_APM_AUDIT_EXIT"] = "1"

        failed = self.run_task("agent:sync")

        self.assertEqual(1, failed.returncode, failed.stderr)
        self.assertFalse(skill.parent.exists())
        self.assertTrue((self.project / ".agent-intake/intaken").is_file())

        del self.env["FAKE_APM_AUDIT_EXIT"]
        synced = self.run_task("agent:sync")

        self.assertEqual(0, synced.returncode, synced.stderr)
        self.assertFalse((self.project / ".agent-intake").exists())

    def test_vendored_sync_removes_nothing_for_a_ledger_path_outside_the_deployed_skills(self) -> None:
        self.use_vendored_project()
        dropped = self.dropped_edit(b"keep\n", b"keep\n")  # a valid removal, held back by the bad one
        outside = Path(tempfile.mkdtemp(prefix="agent-intake-outside-"))
        skills = self.project / ".claude/skills"
        intaken = self.project / ".agent-intake/intaken"
        valid = intaken.read_text()
        cases = {
            "unrelated path": "notes.txt",
            "traversal": ".claude/skills/../../notes.txt",
            "symlinked parent directory": ".claude/skills/old/notes.txt",
            "file symlink": ".claude/skills/linked/ref.md",
            "absolute path": str(outside / "abs.txt"),
        }
        for case, path in cases.items():
            with self.subTest(case=case):
                kept = (dropped, self.project / "notes.txt", outside / "notes.txt", outside / "abs.txt")
                for file in kept:
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_bytes(b"keep\n")
                if not os.path.lexists(skills / "old"):
                    (skills / "old").symlink_to(outside, target_is_directory=True)
                (skills / "linked").mkdir(exist_ok=True)
                if not os.path.lexists(skills / "linked/ref.md"):
                    (skills / "linked/ref.md").symlink_to(self.project / "notes.txt")
                intaken.parent.mkdir(exist_ok=True)
                intaken.write_text(valid + f"{hashlib.sha256(b'keep\n').hexdigest()}  {path}\n")
                self.log.unlink(missing_ok=True)

                result = self.run_task("agent:sync")

                self.assertEqual(1, result.returncode, result.stderr)
                self.assertIn(f"agent:sync: {path} is in .agent-intake/intaken but is not a file inside a deployed skill",
                              result.stderr)
                self.assertNotIn("removed", result.stdout)
                self.assertTrue(os.path.lexists(self.project / path))
                for file in kept:
                    self.assertEqual(b"keep\n", file.read_bytes())
                self.assertTrue(intaken.is_file())
                self.assertEqual([], [command for command in self.commands() if " install " in f"{command} "])

    def edited_skill(self) -> tuple[str, Path]:
        path = ".claude/skills/wayfinder/SKILL.md"
        self.drift(path)
        skill = self.project / path
        skill.parent.mkdir(parents=True)
        skill.write_text("edited\n")
        self.env["FAKE_APM_UPDATE_WRITES"] = str(skill)
        return path, skill

    def test_intake_refresh_puts_the_edits_back_when_the_update_fails_after_deploying(self) -> None:
        self.use_vendored_project()
        path, skill = self.edited_skill()
        self.env["FAKE_APM_UPDATE_EXIT"] = "7"

        result = self.run_task("agent:intake", "--refresh")

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("apm update failed; the edits are put back", result.stderr)
        self.assertEqual("edited\n", skill.read_text())
        self.assertFalse((self.project / ".agent-intake/saved.json").exists())
        self.assertIn(f"{path} differs from the pack's copy", self.run_task("agent:sync").stderr)

    def test_intake_refresh_puts_the_edits_back_over_the_release_it_deployed(self) -> None:
        self.use_vendored_project()
        path, skill = self.edited_skill()

        result = self.run_task("agent:intake", "--refresh")

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual("edited\n", skill.read_text())
        self.assertTrue((self.project / ".agent-intake" / f"{path}.patch").is_file())
        self.assertFalse((self.project / ".agent-intake/saved.json").exists())

    def interrupted_refresh(self) -> Path:
        self.env["FAKE_APM_UPDATE_KILLS_CALLER"] = "1"
        interrupted = self.run_task("agent:intake", "--refresh")
        del self.env["FAKE_APM_UPDATE_KILLS_CALLER"]
        saved = self.project / ".agent-intake/saved.json"
        self.assertNotEqual(0, interrupted.returncode)
        self.assertTrue(saved.is_file())
        return saved

    def test_intake_refresh_keeps_the_edits_on_disk_through_an_interrupted_update(self) -> None:
        self.use_vendored_project()
        path, skill = self.edited_skill()
        kept = self.project / ".agent-intake" / f"{path}.saved"
        saved = self.interrupted_refresh()
        self.assertEqual("new release\n", skill.read_text())

        self.log.unlink()
        refused = self.run_task("agent:sync")

        self.assertEqual(1, refused.returncode, refused.stderr)
        self.assertIn("interrupted 'agent:intake --refresh'", refused.stderr)
        self.assertEqual([], self.commands())
        self.assertTrue(saved.is_file())

        # The update never finished, so nothing shows the file still holds only what it deployed.
        for retry in ((), ("--refresh",)):
            with self.subTest(retry=retry):
                self.log.unlink(missing_ok=True)

                retried = self.run_task("agent:intake", *retry)

                self.assertEqual(1, retried.returncode, retried.stderr)
                self.assertIn(f"{path} changed after an interrupted --refresh", retried.stderr)
                self.assertIn(f".agent-intake/{path}.saved", retried.stderr)
                self.assertEqual("new release\n", skill.read_text())
                self.assertEqual("edited\n", kept.read_text())
                self.assertTrue(saved.is_file())
                self.assertEqual([], self.commands())

        kept.replace(skill)  # keep the saved edit
        resolved = self.run_task("agent:intake")

        self.assertEqual(1, resolved.returncode, resolved.stderr)
        self.assertEqual("edited\n", skill.read_text())
        self.assertTrue((self.project / ".agent-intake" / f"{path}.patch").is_file())
        self.assertFalse(saved.exists())

    def test_intake_keeps_an_edit_made_after_an_interrupted_refresh_beside_the_saved_one(self) -> None:
        self.use_vendored_project()
        path, skill = self.edited_skill()
        kept = self.project / ".agent-intake" / f"{path}.saved"
        saved = self.interrupted_refresh()
        skill.write_text("edited after the interruption\n")

        retried = self.run_task("agent:intake")

        self.assertEqual(1, retried.returncode, retried.stderr)
        self.assertIn(f"{path} changed after an interrupted --refresh", retried.stderr)
        self.assertEqual("edited after the interruption\n", skill.read_text())
        self.assertEqual("edited\n", kept.read_text())
        self.assertTrue(saved.is_file())
        self.assertEqual(1, self.run_task("agent:sync").returncode)

        kept.unlink()  # keep the newer edit
        resolved = self.run_task("agent:intake")

        self.assertEqual(1, resolved.returncode, resolved.stderr)
        self.assertEqual("edited after the interruption\n", skill.read_text())
        self.assertTrue((self.project / ".agent-intake" / f"{path}.patch").is_file())
        self.assertFalse(saved.exists())

    def test_intake_names_how_to_keep_a_saved_deletion_after_an_interrupted_refresh(self) -> None:
        self.use_vendored_project()
        path, skill = self.edited_skill()
        skill.unlink()  # the edit is a deletion
        kept = self.project / ".agent-intake" / f"{path}.saved"
        saved = self.interrupted_refresh()

        retried = self.run_task("agent:intake")

        self.assertEqual(1, retried.returncode, retried.stderr)
        self.assertIn(f"to keep the deletion, delete both {path} and the marker", retried.stderr)
        self.assertEqual("new release\n", skill.read_text())
        self.assertEqual(b"", kept.read_bytes())

        skill.unlink()  # keep the deletion, as the message says
        kept.unlink()
        self.run_task("agent:intake")

        self.assertFalse(skill.exists())
        self.assertFalse(saved.exists())

    def test_deps_renovate_refuses_a_gh_token_without_the_workflow_scope(self) -> None:
        gh = self.bin / "gh"
        gh.write_text(
            "#!/bin/sh\n"
            'case "$1 $2" in\n'
            '  "auth token") echo gho_test ;;\n'
            '  "api -i") printf "HTTP/2.0 200 OK\\r\\nX-Oauth-Scopes: read:org, repo\\r\\n\\r\\n{}\\n" ;;\n'
            "  *) exit 9 ;;\n"
            "esac\n"
        )
        gh.chmod(0o755)
        result = self.run_task("deps:renovate")
        self.assertEqual(1, result.returncode)
        self.assertIn("lacks the workflow scope", result.stderr)

    def test_deps_renovate_refuses_without_a_gh_login(self) -> None:
        gh = self.bin / "gh"
        gh.write_text("#!/bin/sh\nexit 1\n")
        gh.chmod(0o755)
        result = self.run_task("deps:renovate")
        self.assertEqual(1, result.returncode)
        self.assertIn("gh is not logged in", result.stderr)

    def test_check_unit_measures_changed_lines_against_the_commit_ci_passes(self) -> None:
        for name in ("uv",):
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

                result = self.run_task("check:unit")

                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(f"{self.bin}/uv run pytest --cov --cov-report=xml", self.commands()[0])
                diff_cover = [line for line in self.commands() if "diff-cover" in line]
                expected = [] if compared is None else [
                    f"{self.bin}/uv run diff-cover coverage.xml --compare-branch={compared} --fail-under=100"
                ]
                self.assertEqual(expected, diff_cover)

    def fake_github(self, rulesets: dict[str, dict] | None = None, allow_auto_merge: bool = False,
                    delete_branch_on_merge: bool = False, delete_404: bool = False, **extra: object) -> Path:
        """A gh that keeps one repo's rulesets (id -> body), settings, posted statuses and PR edits in a JSON file."""
        state = self.bin / "github.json"
        state.write_text(json.dumps({"rulesets": rulesets or {}, "allow_auto_merge": allow_auto_merge,
                                     "delete_branch_on_merge": delete_branch_on_merge, "delete_404": delete_404,
                                     "statuses": [], "edits": [], **extra}))
        gh = self.bin / "gh"
        gh.write_text(
            f"#!{sys.executable}\n"
            "import json, re, sys\n"
            "from pathlib import Path\n"
            f"state = Path({str(state)!r})\n"
            "data = json.loads(state.read_text())\n"
            "args = sys.argv[2:]\n"
            "if sys.argv[1] == 'pr':\n"
            "    if args[0] == 'view':\n"
            "        print('\\t'.join(data['pr']))\n"
            "    else:\n"
            "        data['edits'].append(args)\n"
            "    state.write_text(json.dumps(data))\n"
            "    sys.exit(data.get('merge_fails') if args[0] == 'merge' else None)\n"
            "method = args[args.index('-X') + 1] if '-X' in args else 'GET'\n"
            "path = next(a for a in args if a.startswith('repos/'))\n"
            "fields = dict(args[i + 1].split('=', 1) for i, a in enumerate(args) if a in ('-f', '-F'))\n"
            "rulesets = data['rulesets']\n"
            "if '/labels/' in path:\n"
            "    data['edits'].append([method, path])\n"
            "    state.write_text(json.dumps(data))\n"
            "    sys.exit({'404': 'gh: Label does not exist (HTTP 404)', '403': 'gh: Resource not accessible by integration (HTTP 403)'}.get(data.get('label_delete')))\n"
            "elif '/statuses/' in path:\n"
            "    data['statuses'].append({'sha': path.rsplit('/', 1)[1], **fields})\n"
            "elif '/rules/branches/' in path:\n"
            "    sys.exit({'free': 'gh: Upgrade to GitHub Pro or make this repository public to enable this feature. (HTTP 403)',\n"
            "              'denied': 'gh: Resource not accessible by integration (HTTP 403)'}.get(data.get('rules')))\n"
            "elif '/actions/runs/' in path:\n"
            "    print(''.join(f'{name}\\n' for name in data['failed_jobs']), end='')\n"
            "elif path.endswith('/rulesets') and method == 'GET':\n"
            "    name = re.search(r'\\.name == \"([^\"]+)\"', args[args.index('--jq') + 1]).group(1)\n"
            "    print(''.join(f'{i}\\n' for i, r in rulesets.items() if r['name'] == name), end='')\n"
            "elif method == 'POST':\n"
            "    rulesets['100'] = json.loads(Path(args[args.index('--input') + 1]).read_text())\n"
            "elif method == 'PUT':\n"
            "    rulesets[path.rsplit('/', 1)[1]] = json.loads(Path(args[args.index('--input') + 1]).read_text())\n"
            "elif method == 'DELETE':\n"
            "    if data['delete_404']:\n"
            "        sys.exit('gh: Not Found (HTTP 404)')\n"
            "    del rulesets[path.rsplit('/', 1)[1]]\n"
            "elif method == 'GET' and data.get('settings_read_fails'):\n"
            "    sys.exit('gh: Bad Gateway (HTTP 502)')\n"
            "elif method == 'PATCH':\n"
            "    data.update({key: value == 'true' for key, value in fields.items()})\n"
            "elif data.get('settings_read_fails'):\n"
            "    sys.exit('gh: Server Error (HTTP 500)')\n"
            "else:\n"
            "    print('\\n'.join(str(data[key.strip().lstrip('.')]).lower() for key in args[args.index('--jq') + 1].split(',')))\n"
            "state.write_text(json.dumps(data))\n"
        )
        gh.chmod(0o755)
        # the pack's labels.py, which setup:github only calls: it logs its arguments
        labels = self.project / ".agents/skills/engineering-loop/scripts/labels.py"
        labels.parent.mkdir(parents=True, exist_ok=True)
        labels.write_text(
            "import os, sys\n"
            "open(os.environ['COMMAND_LOG'], 'a').write(' '.join(['labels.py', *sys.argv[1:]]) + '\\n')\n"
            "print('labels synced')\n"
        )
        return state

    def applied(self) -> dict:
        return json.loads((self.project / ".github/rulesets/main.json").read_text())

    def test_setup_github_creates_its_ruleset_and_prints_the_settings_restore(self) -> None:
        state = self.fake_github(allow_auto_merge=False, delete_branch_on_merge=False)

        result = self.run_task("setup:github")

        self.assertEqual(0, result.returncode, result.stderr)
        github = json.loads(state.read_text())
        self.assertEqual({"100": self.applied()}, github["rulesets"])
        self.assertEqual("loop-merge-queue", self.applied()["name"])
        self.assertTrue(github["allow_auto_merge"])
        self.assertTrue(github["delete_branch_on_merge"])
        [restore] = [line.split("restore: ", 1)[1] for line in result.stdout.splitlines() if "restore: " in line]
        self.assertEqual(
            "gh api -X PATCH 'repos/{owner}/{repo}' -F allow_auto_merge=false -F delete_branch_on_merge=false", restore
        )
        self.assertIn("revert the ruleset: mise run setup:github --revert", result.stdout)
        self.assertNotIn("enforces nothing", result.stdout)
        subprocess.run(["sh", "-c", restore], env=self.env, check=True)
        github = json.loads(state.read_text())
        self.assertFalse(github["allow_auto_merge"])
        self.assertFalse(github["delete_branch_on_merge"])

    def test_setup_github_syncs_the_labels_with_the_packs_labels_py_after_the_ruleset(self) -> None:
        state = self.fake_github(allow_auto_merge=True)

        result = self.run_task("setup:github")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["labels.py"], self.commands())
        lines = result.stdout.splitlines()
        self.assertLess(lines.index("revert the ruleset: mise run setup:github --revert"), lines.index("labels synced"))

        # --dry-run passes through and writes nothing to GitHub: no ruleset, no settings
        self.log.unlink()
        state = self.fake_github(allow_auto_merge=False)
        dry = self.run_task("setup:github", "--dry-run")
        self.assertEqual(0, dry.returncode, dry.stderr)
        self.assertEqual(["labels.py --dry-run"], self.commands())
        github = json.loads(state.read_text())
        self.assertEqual(({}, False), (github["rulesets"], github["allow_auto_merge"]))

        refused = self.run_task("setup:github", "--dry-run", "--revert")
        self.assertEqual(2, refused.returncode)
        self.assertIn("cannot be combined", refused.stderr)

        # without the installed skill it stops before any write
        (self.project / ".agents/skills/engineering-loop/scripts/labels.py").unlink()
        missing = self.run_task("setup:github")
        self.assertEqual(1, missing.returncode)
        self.assertIn("run mise run agent:sync", missing.stderr)
        self.assertEqual({}, json.loads(state.read_text())["rulesets"])

    def test_setup_github_on_a_plan_without_rulesets_sets_squash_only_and_skips_ruleset_and_auto_merge(self) -> None:
        settings = {"allow_merge_commit": True, "allow_rebase_merge": True, "allow_squash_merge": False,
                    "delete_branch_on_merge": False}
        state = self.fake_github(rules="free", **settings)

        result = self.run_task("setup:github")

        self.assertEqual(0, result.returncode, result.stderr)
        github = json.loads(state.read_text())
        self.assertEqual(({}, False), (github["rulesets"], github["allow_auto_merge"]))
        self.assertEqual({"allow_merge_commit": False, "allow_rebase_merge": False, "allow_squash_merge": True,
                          "delete_branch_on_merge": True}, {key: github[key] for key in settings})
        self.assertIn("GitHub enforces nothing on main", result.stdout)
        self.assertNotIn("revert the ruleset", result.stdout)
        self.assertEqual(["labels.py"], self.commands())
        [restore] = [line.split("restore: ", 1)[1] for line in result.stdout.splitlines() if "restore: " in line]
        subprocess.run(["sh", "-c", restore], env=self.env, check=True)
        github = json.loads(state.read_text())
        self.assertEqual(settings, {key: github[key] for key in settings})

        # --dry-run writes nothing on this path either; --revert has no ruleset to delete
        self.log.unlink()
        dry = self.run_task("setup:github", "--dry-run")
        self.assertEqual(0, dry.returncode, dry.stderr)
        self.assertEqual(["labels.py --dry-run"], self.commands())
        self.assertEqual(settings, {key: json.loads(state.read_text())[key] for key in settings})
        revert = self.run_task("setup:github", "--revert")
        self.assertEqual(0, revert.returncode, revert.stderr)
        self.assertIn("nothing to revert", revert.stdout)

    def test_setup_github_on_a_plan_without_rulesets_stops_when_the_settings_read_fails(self) -> None:
        settings = {"allow_merge_commit": True, "allow_rebase_merge": True, "allow_squash_merge": False,
                    "delete_branch_on_merge": False}
        state = self.fake_github(rules="free", settings_read_fails=True, **settings)

        result = self.run_task("setup:github")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("HTTP 502", result.stderr)
        self.assertNotIn("restore: ", result.stdout)
        self.assertEqual(settings, {key: json.loads(state.read_text())[key] for key in settings})
        self.assertEqual([], self.commands())

    def test_setup_github_stops_on_any_other_rules_read_error_before_a_write(self) -> None:
        state = self.fake_github(rules="denied", allow_merge_commit=True)

        result = self.run_task("setup:github")

        self.assertEqual(1, result.returncode)
        self.assertIn("Resource not accessible by integration (HTTP 403)", result.stderr)
        github = json.loads(state.read_text())
        self.assertEqual(({}, False, True), (github["rulesets"], github["allow_auto_merge"], github["allow_merge_commit"]))
        self.assertEqual([], self.commands())

    def test_setup_github_updates_its_ruleset_found_by_name(self) -> None:
        state = self.fake_github({"5": {"name": "loop-merge-queue", "rules": []}}, allow_auto_merge=True)

        result = self.run_task("merge-queue")  # the old name runs as an alias

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"5": self.applied()}, json.loads(state.read_text())["rulesets"])

    def test_setup_github_updates_its_ruleset_by_name_without_a_merge_queue(self) -> None:
        self.project = render(merge_queue=False)
        self.env["MISE_TRUSTED_CONFIG_PATHS"] = str(self.project)
        state = self.fake_github({"5": {"name": "loop-merge-queue", "rules": [{"type": "merge_queue"}]}},
                                 allow_auto_merge=True)

        result = self.run_task("setup:github")

        self.assertEqual(0, result.returncode, result.stderr)
        [applied] = json.loads(state.read_text())["rulesets"].values()
        self.assertEqual(self.applied(), applied)
        self.assertNotIn("merge_queue", [rule["type"] for rule in applied["rules"]])

    def test_setup_github_leaves_another_main_ruleset_untouched(self) -> None:
        main = {"name": "main", "rules": [{"type": "pull_request",
                                           "parameters": {"required_approving_review_count": 2}}]}
        state = self.fake_github({"7": main}, allow_auto_merge=True)

        self.assertEqual(0, self.run_task("setup:github").returncode)
        self.assertEqual({"7": main, "100": self.applied()}, json.loads(state.read_text())["rulesets"])
        self.assertEqual(0, self.run_task("setup:github", "--revert").returncode)
        self.assertEqual({"7": main}, json.loads(state.read_text())["rulesets"])

    def test_setup_github_revert_deletes_its_ruleset_by_name_and_is_done_when_gone(self) -> None:
        state = self.fake_github({"5": {"name": "loop-merge-queue", "rules": []}}, allow_auto_merge=True)

        self.assertEqual(0, self.run_task("setup:github", "--revert").returncode)
        self.assertEqual({}, json.loads(state.read_text())["rulesets"])
        again = self.run_task("setup:github", "--revert")
        self.assertEqual(0, again.returncode, again.stderr)
        self.assertIn("nothing to revert", again.stdout)

        self.fake_github({"5": {"name": "loop-merge-queue", "rules": []}}, allow_auto_merge=True, delete_404=True)
        raced = self.run_task("setup:github", "--revert")  # another run deleted it between list and DELETE
        self.assertEqual(0, raced.returncode, raced.stderr)

    def test_ci_parts_lists_every_check_part_but_check_all_and_honours_path_filters(self) -> None:
        (self.bin / "mise").symlink_to(MISE)
        output = self.bin / "github-output"
        self.env["GITHUB_OUTPUT"] = str(output)
        everything = ["check:agents", "check:lint", "check:secrets", "check:unit"]

        result = self.run_task("ci:parts")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(everything, json.loads(result.stdout))
        self.assertEqual(f"parts={json.dumps(everything)}\n", output.read_text())

        (self.project / ".github/check-paths.yml").write_text('"check:unit":\n  - "src/**"\n')
        for changes, expected in (
            ("[]", ["check:agents", "check:lint", "check:secrets"]),
            ('["check:unit"]', everything),
            (None, everything),  # no CHANGES: run locally, a filtered part counts as matched
        ):
            with self.subTest(changes=changes):
                self.env.pop("CHANGES", None)
                if changes is not None:
                    self.env["CHANGES"] = changes
                result = self.run_task("ci:parts")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(expected, json.loads(result.stdout))

    def test_ci_parts_on_a_push_the_merge_queue_tested_lists_no_part(self) -> None:
        (self.bin / "mise").symlink_to(MISE)
        gh = self.bin / "gh"
        gh.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$COMMAND_LOG"\n[ -n "$GH_COUNT" ] || exit 1\necho "$GH_COUNT"\n')
        gh.chmod(0o755)
        self.env.update({"GITHUB_REPOSITORY": "o/r", "GITHUB_SHA": "abc",
                         "GITHUB_WORKFLOW_REF": "o/r/.github/workflows/ci.yml@refs/heads/main"})
        everything = ["check:agents", "check:lint", "check:secrets", "check:unit"]
        # A wrong skip leaves main untested, so anything but a found run, the lookup failing included, runs every part.
        for event, count, expected in (("push", "1", []), ("push", "0", everything), ("push", "", everything),
                                       ("merge_group", "1", everything), ("pull_request", "1", everything)):
            with self.subTest(event=event, count=count):
                self.env.update({"GITHUB_EVENT_NAME": event, "GH_COUNT": count})
                result = self.run_task("ci:parts")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(expected, json.loads(result.stdout))
        self.assertIn(
            "api repos/o/r/actions/workflows/ci.yml/runs?event=merge_group&status=success&head_sha=abc --jq .total_count",
            self.commands(),
        )

    def test_ci_parts_in_a_monorepo_root_lists_the_roots_own_parts_by_their_bare_names(self) -> None:
        (self.bin / "mise").symlink_to(MISE)
        config = self.project / "mise.toml"
        config.write_text("monorepo_root = true\n" + config.read_text() + '\n[monorepo]\nconfig_roots = ["sub"]\n')
        (self.project / "sub").mkdir()
        (self.project / "sub/mise.toml").write_text('[tasks."check:sub"]\nrun = "true"\n')

        result = self.run_task("ci:parts")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["check:agents", "check:lint", "check:secrets", "check:unit"], json.loads(result.stdout))

    def test_lint_json_skips_the_paths_lint_json_skip_names(self) -> None:
        fake_executable(self.bin, "check-json")
        for name in ("a.json", "modify_b.json"):
            (self.project / name).write_text("{}")
        self.env["LINT_JSON_SKIP"] = "(^|/)modify_"

        result = self.run_task("lint:json", "a.json", "modify_b.json")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([f"{self.bin}/check-json a.json"], self.commands())

    def test_ci_check_passes_only_when_plan_and_parts_passed_and_names_a_failed_part(self) -> None:
        self.fake_github(failed_jobs=["check:unit", "plan"])
        self.env.update({"GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1"})

        for plan, parts, planned, code in (("success", "success", '["check:unit"]', 0),
                                           ("success", "failure", '["check:unit"]', 1),
                                           ("success", "skipped", '["check:unit"]', 1),
                                           ("success", "skipped", "[]", 0),  # nothing to run: a queued commit's push
                                           ("failure", "skipped", "", 1)):
            with self.subTest(plan=plan, parts=parts, planned=planned):
                self.env.update({"PLAN": plan, "PARTS": parts, "PLANNED": planned})
                result = self.run_task("ci:check")
                self.assertEqual(code, result.returncode, result.stdout + result.stderr)
        self.assertIn("::error::check:unit failed; rerun it with: mise run check:unit", result.stdout)
        self.assertNotIn("plan failed", result.stdout)

    def approvals_run(self, code: int, **env: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        """ci:approvals against a fake approvals.py that prints one line and exits with code."""
        script = self.project / ".agents/skills/engineering-loop/scripts/approvals.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(f"import sys\nprint('approvals said {code}')\nsys.exit({code})\n")
        state = self.bin / "github.json"
        if not state.exists():
            self.fake_github(pr=["abc123", "false", "owner", "false"], allow_auto_merge=True)
        self.env.update({"GITHUB_REPOSITORY": "o/r", "EVENT": "pull_request", "ACTION": "labeled", "PR": "7",
                         "QUEUE_HEAD": "", "RUN_URL": "https://example.com/run", "APP_TOKEN": "true", **env})
        result = self.run_task("ci:approvals")
        return result, json.loads(state.read_text())

    def test_ci_approvals_posts_the_merge_result_as_the_loop_approvals_status(self) -> None:
        (self.bin / "mise").symlink_to(MISE)
        for code, state, exit_code in ((0, "success", 0), (3, "pending", 0), (2, "failure", 1)):
            with self.subTest(code=code):
                (self.bin / "github.json").unlink(missing_ok=True)
                result, github = self.approvals_run(code)
                self.assertEqual(exit_code, result.returncode, result.stdout + result.stderr)
                [status] = github["statuses"]
                self.assertEqual(
                    {"sha": "abc123", "state": state, "context": "loop:approvals",
                     "description": f"approvals said {code}", "target_url": "https://example.com/run"},
                    status,
                )
                # Only every proof holding turns auto-merge on; a wait or a missing proof leaves the PR alone.
                merges = [["merge", "7", "--auto", "--squash", "--match-head-commit", "abc123"]] if code == 0 else []
                self.assertEqual(merges, github["edits"])

    def test_ci_approvals_turns_auto_merge_on_only_for_a_ready_pr_without_a_request(self) -> None:
        (self.bin / "mise").symlink_to(MISE)
        self.fake_github(pr=["abc123", "false", "owner", "true"])  # loop:land's request is already there
        kept, github = self.approvals_run(0)
        self.assertEqual(0, kept.returncode, kept.stdout + kept.stderr)
        self.assertEqual(["success"], [status["state"] for status in github["statuses"]])
        self.assertEqual([], github["edits"])
        self.assertIn("already has auto-merge on", kept.stdout)

        self.fake_github(pr=["abc123", "true", "owner", "false"])  # a draft gets no status and no request
        draft, github = self.approvals_run(0)
        self.assertEqual(0, draft.returncode, draft.stderr)
        self.assertEqual(([], []), (github["statuses"], github["edits"]))

        self.fake_github(pr=["abc123", "false", "app/dependabot", "false"])  # no loop proofs, so no auto-merge
        _, github = self.approvals_run(0)
        self.assertEqual([], github["edits"])

        self.fake_github(pr=["abc123", "false", "owner", "false"], allow_auto_merge=True, merge_fails=1)
        refused, github = self.approvals_run(0)
        self.assertEqual(1, refused.returncode, refused.stdout + refused.stderr)
        self.assertEqual(["success"], [status["state"] for status in github["statuses"]])  # the gate stays green
        self.assertIn("could not turn on auto-merge for PR #7 at abc123", refused.stdout)

    def test_ci_approvals_turns_auto_merge_on_only_when_the_repo_allows_it(self) -> None:
        (self.bin / "mise").symlink_to(MISE)
        self.fake_github(pr=["abc123", "false", "owner", "false"], allow_auto_merge=True)
        allowed, github = self.approvals_run(0)
        self.assertEqual(0, allowed.returncode, allowed.stdout + allowed.stderr)
        self.assertEqual([["merge", "7", "--auto", "--squash", "--match-head-commit", "abc123"]], github["edits"])

        # Without the setting gh would merge at once with github.token, so the job stops at the status.
        self.fake_github(pr=["abc123", "false", "owner", "false"], allow_auto_merge=False)
        off, github = self.approvals_run(0)
        self.assertEqual(0, off.returncode, off.stdout + off.stderr)
        self.assertEqual(["success"], [status["state"] for status in github["statuses"]])
        self.assertEqual([], github["edits"])
        self.assertIn("the repo has no auto-merge, so mise run loop:land 7 lands PR #7", off.stdout)

        self.fake_github(pr=["abc123", "false", "owner", "false"], allow_auto_merge=True, settings_read_fails=True)
        unread, github = self.approvals_run(0)
        self.assertEqual(1, unread.returncode, unread.stdout + unread.stderr)
        self.assertEqual(["success"], [status["state"] for status in github["statuses"]])
        self.assertEqual([], github["edits"])
        self.assertIn("could not read the repo's auto-merge setting", unread.stdout)

    def test_ci_approvals_without_the_app_token_posts_the_status_only(self) -> None:
        # github.token starts no workflow for the merge, so a merge queue would wait for CI forever.
        (self.bin / "mise").symlink_to(MISE)
        self.fake_github(pr=["abc123", "false", "owner", "false"], allow_auto_merge=True)
        for app in ("false", ""):
            with self.subTest(app=app):
                result, github = self.approvals_run(0, APP_TOKEN=app)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual("success", github["statuses"][-1]["state"])
                self.assertEqual([], github["edits"])
                self.assertIn("no App token, so mise run loop:land 7 lands PR #7", result.stdout)

    def test_loop_land_runs_approvals_land_on_the_pr_and_keeps_its_exit(self) -> None:
        script = self.project / ".agents/skills/engineering-loop/scripts/approvals.py"
        missing = self.run_task("loop:land", "7")
        self.assertEqual(1, missing.returncode)
        self.assertIn("run mise run agent:sync", missing.stderr)

        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("import sys\nprint(' '.join(sys.argv[1:]))\nsys.exit(3)\n")
        waiting = self.run_task("loop:land", "7")
        self.assertEqual(3, waiting.returncode, waiting.stderr)
        self.assertEqual("land 7", waiting.stdout.strip())
        waited = self.run_task("loop:land", "7", "--wait")
        self.assertEqual(3, waited.returncode, waited.stderr)
        self.assertEqual("land 7 --wait", waited.stdout.strip())

    def test_ci_approvals_on_a_push_removes_the_merge_approval_first(self) -> None:
        (self.bin / "mise").symlink_to(MISE)
        for label_delete, code, states in ((None, 0, ["pending"]), ("404", 0, ["pending"]), ("403", 1, ["failure"])):
            with self.subTest(label_delete=label_delete):
                self.fake_github(pr=["abc123", "false", "owner", "false"], label_delete=label_delete)
                result, github = self.approvals_run(3, ACTION="synchronize")
                self.assertEqual(code, result.returncode, result.stdout + result.stderr)
                self.assertEqual([["DELETE", "repos/o/r/issues/7/labels/approved:merge"]], github["edits"])
                self.assertEqual(states, [status["state"] for status in github["statuses"]])
        # Only the label being absent is tolerated; any other failure is printed and fails the job.
        self.assertIn("could not remove approved:merge", result.stderr)
        self.assertIn("HTTP 403", result.stderr)

    def test_ci_approvals_passes_a_queue_commit_and_dependabot_and_skips_a_draft(self) -> None:
        (self.bin / "mise").symlink_to(MISE)
        _, queued = self.approvals_run(2, EVENT="merge_group", QUEUE_HEAD="q1", PR="")
        self.assertEqual([("q1", "success")], [(s["sha"], s["state"]) for s in queued["statuses"]])

        self.fake_github(pr=["abc123", "false", "app/dependabot", "false"])
        _, dependabot = self.approvals_run(2)
        self.assertEqual([("abc123", "success")], [(s["sha"], s["state"]) for s in dependabot["statuses"]])

        self.fake_github(pr=["abc123", "true", "owner", "false"])
        draft, github = self.approvals_run(2)
        self.assertEqual(0, draft.returncode, draft.stderr)
        self.assertEqual([], github["statuses"])

    def test_check_passes_in_a_generated_python_project_without_pre_commit(self) -> None:
        # Real toolchain: the project's mise tools, installed. pre-commit is hidden from mise and
        # a fake one that fails is first on PATH, so check:lint proves it never calls pre-commit.
        project = render()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=project, check=True)
        subprocess.run(["git", "add", "-A"], cwd=project, check=True)
        commit = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit"]
        subprocess.run([*commit, "--no-verify", "-qm", "chore: scaffold"], cwd=project, check=True)
        fake = Path(tempfile.mkdtemp(prefix="no-pre-commit-"))
        (fake / "pre-commit").write_text('#!/bin/sh\necho called >> "$0.log"\nexit 99\n')
        (fake / "pre-commit").chmod(0o755)
        env = {**os.environ, "MISE_TRUSTED_CONFIG_PATHS": str(project), "MISE_DISABLE_TOOLS": "pre-commit",
               "PATH": f"{fake}:{os.environ['PATH']}"}
        subprocess.run([MISE, "install"], cwd=project, env=env, check=True, capture_output=True)

        result = subprocess.run([MISE, "run", "check"], cwd=project, env=env, capture_output=True, text=True)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse((fake / "pre-commit.log").exists())
        self.assertIn("[lint:eof]", result.stderr)

        # A fixer hook fails the commit and leaves the file fixed.
        env.pop("MISE_DISABLE_TOOLS")
        env["PATH"] = os.environ["PATH"]
        subprocess.run([MISE, "exec", "--", "pre-commit", "install"], cwd=project, env=env, check=True,
                       capture_output=True)
        (project / "notes.txt").write_text("no final newline")
        subprocess.run(["git", "add", "notes.txt"], cwd=project, check=True)
        hooked = subprocess.run([*commit, "-qm", "docs: notes"], cwd=project, env=env, capture_output=True, text=True)
        self.assertNotEqual(0, hooked.returncode)
        self.assertIn("lint:eof", hooked.stdout + hooked.stderr)
        self.assertEqual("no final newline\n", (project / "notes.txt").read_text())



class TerraformMiseTasksTest(unittest.TestCase):
    """The Terraform tasks against a fake terraform that logs its data dir and arguments."""

    def setUp(self) -> None:
        self.project = render("infra/terraform", include_mise=True, include_agent_layer=False, include_fnox=False)
        for name in ("stacks/a/main.tf", "stacks/a/tests/a.tftest.hcl", "modules/m/main.tf",
                     "modules/m/m.tftest.hcl"):
            (self.project / name).parent.mkdir(parents=True, exist_ok=True)
            (self.project / name).write_text("")
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.project, check=True)
        self.bin = Path(tempfile.mkdtemp(prefix="terraform-task-bin-"))
        self.log = self.bin / "commands.log"
        (self.bin / "terraform").write_text('#!/bin/sh\necho "${TF_DATA_DIR:-} $*" >> "$COMMAND_LOG"\n')
        (self.bin / "terraform").chmod(0o755)
        # Its own mise dirs, so an installed terraform never shadows the fake one.
        self.env = {**os.environ, "COMMAND_LOG": str(self.log), "MISE_OFFLINE": "true",
                    "MISE_CACHE_DIR": str(self.bin / "mise-cache"), "MISE_DATA_DIR": str(self.bin / "mise-data"),
                    "MISE_STATE_DIR": str(self.bin / "mise-state"),
                    "MISE_TRUSTED_CONFIG_PATHS": str(self.project), "PATH": f"{self.bin}:/usr/bin:/bin"}

    def run_task(self, task: str, *arguments: str) -> list[str]:
        self.log.unlink(missing_ok=True)
        result = subprocess.run([MISE, "run", "--skip-tools", task, *arguments], cwd=self.project,
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_validate_runs_offline_in_every_root_module_outside_modules(self) -> None:
        offline = ".terraform/offline"
        self.assertEqual([f"{offline} -chdir=. init -backend=false -input=false", f"{offline} -chdir=. validate",
                          f"{offline} -chdir=stacks/a init -backend=false -input=false",
                          f"{offline} -chdir=stacks/a validate"],
                         self.run_task("lint:terraform-validate"))

        self.env["TF_ROOT_MODULES"] = "stacks/a"
        self.assertEqual([f"{offline} -chdir=stacks/a init -backend=false -input=false",
                          f"{offline} -chdir=stacks/a validate"],
                         self.run_task("lint:terraform-validate"))

    def test_test_fast_runs_terraform_test_in_each_module_with_tests(self) -> None:
        offline = ".terraform/offline"
        self.assertEqual([f"{offline} -chdir=modules/m init -backend=false -input=false",
                          f"{offline} -chdir=modules/m test",
                          f"{offline} -chdir=stacks/a init -backend=false -input=false",
                          f"{offline} -chdir=stacks/a test"],
                         self.run_task("test:fast"))

    def test_plan_and_apply_take_the_root_module_directory(self) -> None:
        self.assertEqual([" -chdir=. init -input=false", " -chdir=. plan"], self.run_task("plan"))
        self.assertEqual([" -chdir=stacks/a init -input=false", " -chdir=stacks/a apply"],
                         self.run_task("apply", "stacks/a"))


class FilesOrRepoTest(unittest.TestCase):
    """scripts/files-or-repo picks the files every lint: task hands its linter (#74)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.project = render("software/python")
        cls.script = cls.project / "scripts/files-or-repo"
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        (cls.project / "blob.bin").write_bytes(b"\0\1\2")
        (cls.project / "skipped.md").write_text("x\n")
        subprocess.run(["git", "init", "-q", "--template="], cwd=cls.project, env=env, check=True)
        subprocess.run(["git", "add", "-A"], cwd=cls.project, env=env, check=True)
        cls.tracked = set(subprocess.run(["git", "ls-files"], cwd=cls.project, env=env, check=True,
                                         capture_output=True, text=True).stdout.split())

    def picked(self, *args: str) -> list[str]:
        record = Path(tempfile.mkdtemp()) / "args"
        linter = f"printf '%s\\n' \"$@\" >> {record}"
        subprocess.run([str(self.script), *args, "sh", "-c", linter, "linter", "--"] + list(self.files),
                       cwd=self.project, check=True)
        return sorted(record.read_text().split()) if record.exists() else []

    def test_given_files_it_passes_those_filtered(self) -> None:
        self.files = ["README.md", "skipped.md", "pyproject.toml", "missing.md"]
        self.assertEqual(["README.md", "skipped.md"], self.picked("--only", r"\.md$"))
        self.assertEqual(["README.md"], self.picked("--only", r"\.md$", "--skip", "^skipped"))

    def test_given_none_it_passes_the_tracked_files(self) -> None:
        self.files = []
        self.assertEqual(sorted(self.tracked), self.picked())
        self.assertEqual(sorted(self.tracked - {"blob.bin"}), self.picked("--text"))

    def test_a_fixer_that_changes_a_file_fails(self) -> None:
        target = self.project / "skipped.md"
        before = target.read_text()
        self.addCleanup(target.write_text, before)
        changed = subprocess.run([str(self.script), "--fixer", "sh", "-c", 'echo y >> "$1"', "fixer", "--", "skipped.md"],
                                 cwd=self.project, capture_output=True, text=True)
        self.assertEqual(1, changed.returncode, changed.stderr)


if __name__ == "__main__":
    unittest.main()
