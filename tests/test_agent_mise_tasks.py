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
            "elif method == 'PATCH':\n"
            "    data.update({key: value == 'true' for key, value in fields.items()})\n"
            "else:\n"
            "    print(str(data[args[args.index('--jq') + 1].lstrip('.')]).lower())\n"
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

    def test_setup_github_updates_its_ruleset_found_by_name(self) -> None:
        state = self.fake_github({"5": {"name": "loop-merge-queue", "rules": []}}, allow_auto_merge=True)

        result = self.run_task("merge-queue")  # the old name runs as an alias

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"5": self.applied()}, json.loads(state.read_text())["rulesets"])

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

    def test_ci_check_passes_only_when_plan_and_parts_passed_and_names_a_failed_part(self) -> None:
        self.fake_github(failed_jobs=["check:unit", "plan"])
        self.env.update({"GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1"})

        for plan, parts, code in (("success", "success", 0), ("success", "failure", 1),
                                  ("success", "skipped", 1), ("failure", "skipped", 1)):
            with self.subTest(plan=plan, parts=parts):
                self.env.update({"PLAN": plan, "PARTS": parts})
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
            self.fake_github(pr=["abc123", "false", "owner", "false"])
        self.env.update({"GITHUB_REPOSITORY": "o/r", "EVENT": "pull_request", "ACTION": "labeled", "PR": "7",
                         "QUEUE_HEAD": "", "RUN_URL": "https://example.com/run", **env})
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

        self.fake_github(pr=["abc123", "false", "owner", "false"], merge_fails=1)
        refused, github = self.approvals_run(0)
        self.assertEqual(1, refused.returncode, refused.stdout + refused.stderr)
        self.assertEqual(["success"], [status["state"] for status in github["statuses"]])  # the gate stays green
        self.assertIn("could not turn on auto-merge for PR #7 at abc123", refused.stdout)

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


if __name__ == "__main__":
    unittest.main()
