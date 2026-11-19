"""Generated CI narrows a PR's and a push's check to the affected tests and runs the full parts nightly."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

import yaml

from tests.test_agent_layer_generation import LEAVES, MISE, render

AFFECTED = ".agents/skills/engineering-loop/scripts/approvals.py affected-tests"
NIGHTLY = ".agents/skills/engineering-loop/scripts/nightly.py red"
SCRIPTS = Path(".agents/skills/engineering-loop/scripts")

# The pack's reader of loop.md (gatekeeper.py at the pinned release: AFFECTED, FULL_GATE, narrowing), as far as
# ci:narrowed uses it; the tests run the task against it, so its grammar is the pack's, not the task's.
GATEKEEPER = '''\
#!/usr/bin/env -S uv run -q --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["PyYAML==6.0.3"]
# ///
import re
import sys

try:
    import yaml  # the real module's import-time dependency: a python3 without PyYAML exits here
except ImportError:
    sys.exit("gatekeeper.py needs PyYAML")

AFFECTED = re.compile(r"^Affected tests:[ \\t]*(.+?)[ \\t]*$", re.MULTILINE)
FULL_GATE = re.compile(r"^Gate:[ \\t]*`?full`?[ \\t]*$", re.MULTILINE)


def narrowing(text):
    found = AFFECTED.search(text)
    if found is None or FULL_GATE.search(text):
        return None
    return found.group(1).strip().strip("`")
'''


def workflow(project_type: str, **answers: object) -> tuple[dict, str]:
    text = (render(project_type, **answers) / ".github/workflows/ci.yml").read_text()
    return yaml.safe_load(text), text


_TASKS: dict[str, str] = {}


def task(project: Path, name: str) -> str:
    if name not in _TASKS:  # the rendered tasks are the same in every test
        _TASKS[name] = tomllib.loads((project / "mise.toml").read_text())["tasks"][name]["run"]
    return _TASKS[name]


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                            cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


# what a task needs from the caller's environment to run uv and reach its package index
KEEP = {"PATH", "HOME", "TMPDIR", "SSL_CERT_FILE", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "REQUESTS_CA_BUNDLE"}


def sh(script: str, cwd: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", "-c", script], cwd=cwd, capture_output=True, text=True,
                          env={**{k: v for k, v in os.environ.items() if k in KEEP or k.startswith("UV_")}, **env})


class NarrowedCiTest(unittest.TestCase):
    def test_every_leaf_narrows_a_pr_and_a_push_and_runs_the_full_parts_nightly(self) -> None:
        for project_type, answers in LEAVES:
            with self.subTest(project_type=project_type, **answers):
                ci, _ = workflow(project_type, **answers)
                jobs = ci["jobs"]
                runs = {step.get("name"): step for step in jobs["affected"]["steps"] if "name" in step}
                pull_request = runs["Affected tests (pull request)"]
                push = runs["Affected tests (push to main)"]
                self.assertEqual(f"uv run {AFFECTED} --base HEAD^1", pull_request["run"])
                self.assertEqual("${{ github.event_name == 'pull_request' }}", pull_request["if"])
                self.assertEqual("${{ github.event.before }}", push["env"]["BEFORE"])
                self.assertEqual(f'uv run {AFFECTED} --base "$BEFORE"', push["run"])
                checkout = jobs["affected"]["steps"][0]
                self.assertEqual(0, checkout["with"]["fetch-depth"])
                self.assertNotIn("pull_request.base.sha", yaml.safe_dump(jobs["affected"]))

                # PyYAML reads the bare key `on` as True.
                self.assertEqual([{"cron": "41 3 * * *"}], ci[True]["schedule"])
                nightly = jobs["nightly-red"]
                self.assertEqual("check", nightly["needs"])
                self.assertIn("github.event_name == 'schedule'", nightly["if"])
                self.assertIn("needs.check.result == 'failure'", nightly["if"])
                self.assertEqual("write", nightly["permissions"]["issues"])
                self.assertNotIn("issues", ci["permissions"])  # that job only
                script = "\n".join(step.get("run", "") for step in nightly["steps"])
                self.assertIn("mise run ci:last-green", script)
                self.assertIn(f'uv run {NIGHTLY} --last-green "$LAST_GREEN" --red "$RED" --run "$RUN_URL"', script)
                self.assertEqual(0, nightly["steps"][0]["with"]["fetch-depth"])

    def test_the_narrowed_run_replaces_the_parts_and_the_check_waits_for_it(self) -> None:
        for project_type, answers in LEAVES:
            with self.subTest(project_type=project_type, **answers):
                jobs = workflow(project_type, **answers)[0]["jobs"]
                plan = jobs["plan"]
                steps = plan["steps"]
                mode = next(index for index, step in enumerate(steps) if step.get("id") == "mode")
                parts = next(index for index, step in enumerate(steps) if step.get("id") == "parts")
                self.assertEqual("mise run ci:narrowed", steps[mode]["run"])
                # ci:narrowed runs the pack under uv.
                self.assertTrue([step for step in steps[:mode] if step.get("uses", "").startswith("astral-sh/setup-uv@")])
                self.assertLess(mode, parts)
                # A narrowed run lists no part: the step is skipped, and the output falls back to an empty
                # list, since part's fromJSON('') would fail on the unset output.
                self.assertEqual("${{ steps.mode.outputs.narrowed != 'true' }}", steps[parts]["if"])
                self.assertEqual("${{ steps.parts.outputs.parts || '[]' }}", plan["outputs"]["parts"])
                self.assertEqual("${{ steps.mode.outputs.narrowed }}", plan["outputs"]["narrowed"])
                self.assertIn("needs.plan.outputs.parts != '[]'", jobs["part"]["if"])
                self.assertIn("needs.plan.outputs.narrowed == 'true'", jobs["affected"]["if"])
                # check waits for the narrowed run and reads its result.
                self.assertIn("affected", jobs["check"]["needs"])
                env = next(step["env"] for step in jobs["check"]["steps"] if step.get("run") == "mise run ci:check")
                self.assertEqual("${{ needs.affected.result }}", env["AFFECTED"])

    def test_a_queue_entry_keeps_the_full_parts(self) -> None:
        ci, _ = workflow("software/python", merge_queue=True)
        self.assertIn("merge_group", ci[True])
        self.assertEqual("mise run ci:narrowed", next(s for s in ci["jobs"]["plan"]["steps"] if s.get("id") == "mode")["run"])

    def narrowed(self, event: str, base: str | None, head: str | None, pack: bool = True,
                 env: dict[str, str] | None = None) -> str:
        """`ci:narrowed`'s answer in a repository whose HEAD^1 holds loop.md `base` and whose HEAD holds `head`."""
        project = render("software/python") if "ci:narrowed" not in _TASKS else Path()
        repo = Path(tempfile.mkdtemp(prefix="narrowed-repo-"))
        self.addCleanup(shutil.rmtree, repo, True)
        git(repo, "init", "-q")
        (repo / SCRIPTS).mkdir(parents=True)
        if pack:
            (repo / SCRIPTS / "gatekeeper.py").write_text(GATEKEEPER)
        (repo / "docs/agents").mkdir(parents=True)
        for text in (base, head):
            if text is None:
                (repo / "docs/agents/loop.md").unlink(missing_ok=True)
            else:
                (repo / "docs/agents/loop.md").write_text(text)
            (repo / "touch").write_text(str(text))
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "--allow-empty", "-m", "x")
        result = sh(task(project, "ci:narrowed"), repo, GITHUB_EVENT_NAME=event, **(env or {}))
        self.assertEqual(0, result.returncode, result.stderr)
        self.last_stderr = result.stderr
        found = re.fullmatch(r"narrowed=(true|false)\n", result.stdout)
        self.assertIsNotNone(found, result.stdout)
        return found[1]

    def test_narrowing_is_the_packs_reading_of_loop_md_in_every_spelling(self) -> None:
        line = "Affected tests: mise run check-fast\n"
        cases = (
            ("# Loop facts\n", "false"),  # the seed: no selector
            (line, "true"),
            (line + "Gate: full\n", "false"),
            (line + "Gate: `full`\n", "false"),
            (line + "Gate:  full\n", "false"),  # two spaces
            (line + "Gate:\tfull\n", "false"),
            ("Affected tests:\n", "false"),  # no command
            ("  Affected tests: mise run check-fast\n", "false"),  # indented: the pack reads from the line's start
            (line + "Gate: full is not set\n", "true"),  # prose, not the opt-out line
        )
        for text, expected in cases:
            for event in ("pull_request", "push"):
                with self.subTest(event=event, text=text):
                    self.assertEqual(expected, self.narrowed(event, text, text))

    def test_a_pr_reads_loop_md_from_its_base_and_a_push_from_the_tree(self) -> None:
        line = "Affected tests: mise run check-fast\n"
        # A PR that adds the line, or drops the opt-out, does not loosen its own gate.
        self.assertEqual("false", self.narrowed("pull_request", "# Loop facts\n", line))
        self.assertEqual("false", self.narrowed("pull_request", None, line))  # the base has no loop.md
        self.assertEqual("false", self.narrowed("pull_request", line + "Gate: full\n", line))
        self.assertEqual("true", self.narrowed("pull_request", line, "# Loop facts\n"))
        self.assertEqual("true", self.narrowed("push", "# Loop facts\n", line))  # main's own tree
        self.assertEqual("false", self.narrowed("push", line, None))

    def test_only_a_pr_or_a_push_narrows_and_an_unreadable_pack_means_full(self) -> None:
        line = "Affected tests: mise run check-fast\n"
        for event in ("schedule", "merge_group", "workflow_dispatch"):
            with self.subTest(event=event):
                self.assertEqual("false", self.narrowed(event, line, line))
        self.assertEqual("false", self.narrowed("pull_request", line, line, pack=False))

    def test_a_python3_without_pyyaml_still_narrows_and_a_failing_pack_warns(self) -> None:
        line = "Affected tests: mise run check-fast\n"
        # The first python3 on PATH cannot import yaml, as on a runner image, a mise python or a clean venv.
        bin_dir = Path(tempfile.mkdtemp(prefix="no-yaml-"))
        self.addCleanup(shutil.rmtree, bin_dir, True)
        (bin_dir / "yaml.py").write_text("raise ImportError('no PyYAML here')\n")
        (bin_dir / "python3").write_text(f'#!/bin/sh\nPYTHONPATH="{bin_dir}" exec "{sys.executable}" "$@"\n')
        (bin_dir / "python3").chmod(0o755)
        path = f"{bin_dir}:{os.environ['PATH']}"
        probe = subprocess.run(["python3", "-c", "import yaml"], env={"PATH": path}, capture_output=True)
        self.assertNotEqual(0, probe.returncode)  # the premise
        for event in ("pull_request", "push"):
            with self.subTest(event=event):
                self.assertEqual("true", self.narrowed(event, line, line, env={"PATH": path}))
                self.assertNotIn("::warning::", self.last_stderr)
        # A pack that cannot answer runs the full check, and says why.
        self.assertEqual("false", self.narrowed("push", line, line, pack=False))
        self.assertIn("::warning::ci:narrowed ran the full check", self.last_stderr)

    def check(self, **env: str) -> subprocess.CompletedProcess[str]:
        run = task(render("software/python") if "ci:check" not in _TASKS else Path(), "ci:check")
        return sh(run, Path(tempfile.gettempdir()), **env)

    def test_check_fails_when_the_narrowed_run_failed_or_was_cancelled(self) -> None:
        for result in ("failure", "cancelled"):
            with self.subTest(result=result):
                done = self.check(PLAN="success", PARTS="skipped", PLANNED="[]", AFFECTED=result)
                self.assertNotEqual(0, done.returncode)
                self.assertIn(f"was {result}", done.stdout)

    def test_check_passes_on_the_narrowed_run_alone_and_says_so(self) -> None:
        done = self.check(PLAN="success", PARTS="skipped", PLANNED="[]", AFFECTED="success")
        self.assertEqual((0, "the narrowed run passed\n"), (done.returncode, done.stdout))
        # No narrowed run and no part: the plan listed none.
        done = self.check(PLAN="success", PARTS="skipped", PLANNED="[]", AFFECTED="skipped")
        self.assertEqual((0, "the plan listed no check: part\n"), (done.returncode, done.stdout))
        done = self.check(PLAN="success", PARTS="success", PLANNED='["check:unit"]', AFFECTED="skipped")
        self.assertEqual((0, "every check: part passed\n"), (done.returncode, done.stdout))

    def last_green(self, gh: str) -> subprocess.CompletedProcess[str]:
        """`ci:last-green` in a repository of two commits, with a `gh` that runs the shell text `gh`."""
        bin_dir = Path(tempfile.mkdtemp(prefix="stub-gh-"))
        repo = Path(tempfile.mkdtemp(prefix="last-green-repo-"))
        for directory in (bin_dir, repo):
            self.addCleanup(shutil.rmtree, directory, True)
        (bin_dir / "gh").write_text(f"#!/bin/sh\n{gh}\n")
        (bin_dir / "gh").chmod(0o755)
        git(repo, "init", "-q")
        for name in ("first", "second"):
            (repo / name).write_text(name)
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "--allow-empty", "-m", name)
        self.root_commit = git(repo, "rev-list", "--max-parents=0", "HEAD")
        run = task(render("software/python") if "ci:last-green" not in _TASKS else Path(), "ci:last-green")
        return sh(run, repo, **{"PATH": f"{bin_dir}:{os.environ['PATH']}"}, GITHUB_REPOSITORY="o/r",
                  GITHUB_WORKFLOW_REF="o/r/.github/workflows/ci.yml@refs/heads/main", GITHUB_SHA=git(repo, "rev-parse", "HEAD"))

    def test_last_green_is_the_newest_green_nightlys_commit_else_the_first_commit(self) -> None:
        green = "a" * 40
        found = self.last_green(f'echo "$@" >&2; echo {green}')
        self.assertEqual((0, green + "\n"), (found.returncode, found.stdout))
        # It asks for this workflow's successful scheduled runs.
        self.assertIn("repos/o/r/actions/workflows/ci.yml/runs?event=schedule&status=success", found.stderr)
        none = self.last_green("exit 0")  # no earlier green run: the jq filter prints nothing
        self.assertEqual((0, self.root_commit + "\n"), (none.returncode, none.stdout))

    def test_a_failed_lookup_fails_the_step_instead_of_listing_every_merge(self) -> None:
        failed = self.last_green("echo 'HTTP 502' >&2; exit 1")
        self.assertNotEqual(0, failed.returncode)
        self.assertIn("::error::", failed.stderr)
        self.assertEqual("", failed.stdout)

    def test_loop_md_says_ci_narrows_and_ships_no_selector(self) -> None:
        project = render("software/python")
        loop = (project / "docs/agents/loop.md").read_text()
        self.assertIn("`Affected tests: <command>`", loop)
        self.assertIn("`Gate: full`", loop)
        self.assertFalse([line for line in loop.splitlines() if line.startswith("Affected tests:")])

    def test_without_the_loop_ci_is_unchanged(self) -> None:
        for answers in ({"engineering_loop": False}, {"include_engineering_workflow": False}, {"include_agent_layer": False}):
            with self.subTest(**answers):
                ci, text = workflow("software/python", **answers)
                self.assertNotIn("affected", ci["jobs"])
                self.assertNotIn("nightly-red", ci["jobs"])
                self.assertNotIn("schedule", ci[True])
                self.assertNotIn("affected-tests", text)
                self.assertNotIn("nightly.py", text)

    def test_a_rendered_workflow_passes_actionlint_and_zizmor(self) -> None:
        project = render("software/python")
        tools = tomllib.loads((project / "mise.toml").read_text())["tools"]
        for linter, args in (("actionlint", ()), ("zizmor", ("--offline",))):
            with self.subTest(linter=linter):
                result = subprocess.run(
                    [MISE, "exec", f"{linter}@{tools[linter]}", "--", linter, *args, ".github/workflows/ci.yml"],
                    cwd=project, capture_output=True, text=True,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)


    def test_a_loop_off_workflow_of_every_template_passes_actionlint_and_zizmor(self) -> None:
        seen = set()
        for project_type, answers in LEAVES:
            project = render(project_type, engineering_loop=False, **answers)
            if not (project / ".github/workflows/ci.yml").exists():
                continue
            seen.add(project_type)
            tools = tomllib.loads((project / "mise.toml").read_text())["tools"]
            for linter, args in (("actionlint", ()), ("zizmor", ("--offline",))):
                with self.subTest(template=project_type, linter=linter):
                    result = subprocess.run(
                        [MISE, "exec", f"{linter}@{tools[linter]}", "--", linter, *args, ".github/workflows/ci.yml"],
                        cwd=project, capture_output=True, text=True,
                    )
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertGreaterEqual(len(seen), 3)


if __name__ == "__main__":
    unittest.main()
