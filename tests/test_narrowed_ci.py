"""Generated CI narrows a PR's and a push's check to the affected tests and runs the full parts nightly."""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
import unittest

import yaml

from tests.test_agent_layer_generation import LEAVES, render

AFFECTED = ".agents/skills/engineering-loop/scripts/approvals.py affected-tests"
NIGHTLY = ".agents/skills/engineering-loop/scripts/nightly.py red"


def workflow(project_type: str, **answers: object) -> tuple[dict, str]:
    text = (render(project_type, **answers) / ".github/workflows/ci.yml").read_text()
    return yaml.safe_load(text), text


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

                # The narrowed run replaces the parts only when the project names a selector.
                plan = jobs["plan"]
                self.assertIn("narrowed", plan["outputs"])
                mode = next(step for step in plan["steps"] if step.get("id") == "mode")
                self.assertEqual("mise run ci:narrowed", mode["run"])
                self.assertIn("affected", jobs["check"]["needs"])

    def test_a_queue_entry_keeps_the_full_parts(self) -> None:
        ci, _ = workflow("software/python", merge_queue=True)
        mode = next(step for step in ci["jobs"]["plan"]["steps"] if step.get("id") == "mode")
        project = render("software/python", merge_queue=True)
        task = tomllib.loads((project / "mise.toml").read_text())["tasks"]["ci:narrowed"]["run"]
        self.assertIn("pull_request|push)", task)
        self.assertNotIn("merge_group", task)
        self.assertEqual("mise run ci:narrowed", mode["run"])
        self.assertIn("merge_group", ci[True])

    def test_narrowing_needs_a_selector_line_and_no_full_gate_and_a_pr_or_push(self) -> None:
        project = render("software/python")
        script = tomllib.loads((project / "mise.toml").read_text())["tasks"]["ci:narrowed"]["run"]
        loop = project / "docs/agents/loop.md"
        cases = (
            ("# Loop facts\n", "pull_request", "false"),  # the seed: no selector
            ("Affected tests: mise run check-fast\n", "pull_request", "true"),
            ("Affected tests: mise run check-fast\n", "push", "true"),
            ("Affected tests: mise run check-fast\n", "schedule", "false"),
            ("Affected tests: mise run check-fast\n", "merge_group", "false"),
            ("Affected tests: mise run check-fast\nGate: full\n", "pull_request", "false"),
        )
        for text, event, expected in cases:
            with self.subTest(event=event, text=text):
                loop.write_text(text)
                result = subprocess.run(["sh", "-c", script], cwd=project, capture_output=True, text=True,
                                        env={"PATH": os.environ["PATH"], "GITHUB_EVENT_NAME": event})
                self.assertEqual((0, f"narrowed={expected}\n"), (result.returncode, result.stdout))

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
        project = render("software/python", engineering_loop=False)
        self.assertNotIn("Affected tests", (project / "docs/agents/loop.md").read_text() if (project / "docs/agents/loop.md").exists() else "")

    def test_a_rendered_workflow_passes_actionlint(self) -> None:
        actionlint = shutil.which("actionlint")
        if actionlint is None:
            self.skipTest("actionlint is not installed")
        path = render("software/python") / ".github/workflows/ci.yml"
        result = subprocess.run([actionlint, str(path)], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
