"""Every workflow, the template's own and the generated ones, caps its jobs' time, cancels superseded runs and
filters push like pull_request, and ghalint enforces the time limit."""

from __future__ import annotations

import subprocess
import tomllib
import unittest
from pathlib import Path

import yaml

from tests.test_agent_layer_generation import mise_config, LEAVES, MISE, ROOT, render

GHALINT = "aqua:suzuki-shunsuke/ghalint@1.6.0"
# A release or deploy workflow must not cancel in progress: a run stopped halfway leaves things half-published.
RELEASE_WORDS = ("release", "deploy", "publish")


def workflows(project: Path) -> list[Path]:
    return sorted((project / ".github/workflows").glob("*.y*ml"))


def own_workflows() -> list[Path]:
    return workflows(ROOT) + workflows(ROOT / "examples/agent-layer-mvp")


def generated_workflows() -> list[tuple[str, Path]]:
    found = []
    for project_type, answers in LEAVES:
        for loop in (True, False):
            project = render(project_type, loop=loop, **answers)
            found += [(f"{project_type} loop={loop}", path) for path in workflows(project)]
    return found


def load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    data["on"] = data.pop(True, data.get("on"))  # YAML reads a bare `on` as true
    return data


def ghalint(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([MISE, "exec", GHALINT, "--", "ghalint", "run", *args], cwd=cwd, capture_output=True, text=True)


class WorkflowPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = generated_workflows()

    def every_workflow(self):
        yield from ((str(path), path) for path in own_workflows())
        yield from ((f"{label}: {path.name}", path) for label, path in self.generated)

    def test_every_job_sets_timeout_minutes(self) -> None:
        for label, path in self.every_workflow():
            for name, job in load(path)["jobs"].items():
                with self.subTest(workflow=label, job=name):
                    self.assertIsInstance(job.get("timeout-minutes"), int)

    def test_every_workflow_cancels_superseded_runs_except_release_and_deploy(self) -> None:
        for label, path in self.every_workflow():
            data = load(path)
            with self.subTest(workflow=label):
                if any(word in path.stem.lower() or word in str(data.get("name", "")).lower() for word in RELEASE_WORDS):
                    continue
                self.assertIn("cancel-in-progress", data.get("concurrency", {}))

    def test_generated_ci_cancels_only_a_prs_older_run(self) -> None:
        for label, path in self.generated:
            if path.name != "ci.yml":
                continue
            with self.subTest(workflow=label):
                concurrency = load(path)["concurrency"]
                self.assertEqual("${{ github.event_name == 'pull_request' }}", concurrency["cancel-in-progress"])
                self.assertIn("github.sha", concurrency["group"])  # a push to main keeps its own run

    def test_a_push_trigger_filters_paths_as_its_pull_request_trigger_does(self) -> None:
        for label, path in self.every_workflow():
            on = load(path)["on"]
            if not isinstance(on, dict):
                continue
            with self.subTest(workflow=label):
                for key in ("paths", "paths-ignore"):
                    pr = (on.get("pull_request") or {}).get(key)
                    push = (on.get("push") or {}).get(key)
                    if "pull_request" in on and "push" in on:
                        self.assertEqual(pr, push, key)

    def test_ghalint_passes_on_the_template_own_workflows(self) -> None:
        for directory in (ROOT, ROOT / "examples/agent-layer-mvp"):
            with self.subTest(directory=directory.name):
                result = ghalint(directory)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_ghalint_passes_on_a_generated_project_of_every_template(self) -> None:
        seen = set()
        for project_type, answers in LEAVES:
            for loop in (True, False):
                project = render(project_type, loop=loop, **answers)
                seen.add(project_type)
                with self.subTest(template=project_type, loop=loop):
                    result = ghalint(project)
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual({t for t, _ in LEAVES}, seen)

    def test_the_generated_check_fails_on_a_job_without_timeout_minutes(self) -> None:
        project = render("software/python")
        git = lambda *args: subprocess.run(["git", *args], cwd=project, check=True, capture_output=True, text=True)
        git("init", "-q")
        git("add", "-A")
        ci = project / ".github/workflows/ci.yml"
        task = lambda: subprocess.run([MISE, "run", "check:lint"], cwd=project, capture_output=True, text=True)
        subprocess.run([MISE, "trust", "-q"], cwd=project, check=True, capture_output=True)
        subprocess.run([MISE, "install"], cwd=project, check=True, capture_output=True)

        ci.write_text(ci.read_text().replace("    timeout-minutes: 10\n", "", 1))
        git("add", "-A")
        failed = task()
        self.assertNotEqual(0, failed.returncode)
        self.assertIn("job_timeout_minutes_is_required", failed.stdout + failed.stderr)

    def test_the_generated_project_pins_ghalint_and_runs_it_in_check_lint(self) -> None:
        project = render("software/python")
        tools = mise_config(project)
        self.assertEqual("1.6.0", tools["tools"]["ghalint"])
        self.assertIn("ghalint run", tools["tasks"]["lint:ghalint"]["run"])
        self.assertIn("lint:ghalint", (project / ".pre-commit-config.yaml").read_text())

    def test_the_readme_gives_the_adopter_step(self) -> None:
        readme = (ROOT / "README.md").read_text()
        self.assertIn("timeout-minutes", readme)
        self.assertIn("gh run list --workflow ci.yml", readme)


if __name__ == "__main__":
    unittest.main()
