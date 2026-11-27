"""The engineering loop is one question: what turning it on or off changes in a project (#164)."""

from __future__ import annotations

import atexit
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.test_agent_layer_generation import LEAVES, ROOT, render

GIT = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com"]
SKIP = {".git", "tmp", "apm_modules", "__pycache__", "_out", ".pytest_cache"}
IGNORE = shutil.ignore_patterns(*SKIP)
# main as it was before the loop became one folder: the latest release of the template, for the migration test.
BEFORE = "83ad6114e69b6f353cf8fb670c9e2427779ce2fa"
LOOP_TEXT = re.compile(r"engineering[- ]loop|gatekeeper|approvals|\bloop:|loop\.md|\bthe loop\b|docs/agents|\bloop-check\b", re.I)
# The files the loop owns: nothing of these paths is in a project made with the loop off.
LOOP_PATHS = (
    "docs/agents", ".github/rulesets", ".github/workflows/approvals.yml", ".github/workflows/approvals_relay.yml",
    ".github/workflows/loop-ci.yml", ".mise", ".apm/instructions/loop.instructions.md",
)
# scripts/gate-slot is the host gate every project has; it honors the loop's slot variable when the loop sets it.
NOT_SCANNED = {".copier-answers.yml", "scripts/gate-slot", "Scripts/gate-slot", "gradlew"}


def files(project: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(project)): path.read_bytes()
        for path in sorted(project.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(project).parts
    }


def loop_files(project: Path) -> set[str]:
    return {name for name in files(project) if name.startswith(LOOP_PATHS)}


def required_checks(project: Path) -> list[str]:
    ruleset = json.loads((project / ".github/rulesets/main.json").read_text())
    rule = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
    return [check["context"] for check in rule["parameters"]["required_status_checks"]]


def publish(source: Path, destination: Path, tag: str) -> Path:
    """A template folder as a tagged git repository: copier update reads its tags."""
    shutil.copytree(source, destination, ignore=IGNORE)
    subprocess.run(["git", "init", "-q"], cwd=destination, check=True)
    subprocess.run(["git", "add", "-A"], cwd=destination, check=True)
    subprocess.run([*GIT, "commit", "--no-verify", "-qm", tag], cwd=destination, check=True)
    subprocess.run(["git", "tag", tag], cwd=destination, check=True)
    return destination


def copier(*arguments: str, cwd: Path | None = None) -> None:
    subprocess.run(["copier", *arguments], cwd=cwd, check=True, capture_output=True, text=True)


def commit(project: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    subprocess.run([*GIT, "commit", "--no-verify", "-qm", message, "--allow-empty"], cwd=project, check=True)


def scratch() -> Path:
    path = Path(tempfile.mkdtemp(prefix="loop-switch-"))
    atexit.register(shutil.rmtree, path, True)
    return path


class LoopOffTest(unittest.TestCase):
    def test_a_project_with_the_loop_off_has_no_loop_files_and_no_loop_text(self) -> None:
        for project_type, answers in LEAVES:
            with self.subTest(project_type=project_type, **answers):
                project = render(project_type, loop=False, **answers)
                self.assertEqual(set(), loop_files(project))
                self.assertIn("loop: false", (project / ".copier-answers.yml").read_text())
                for name, data in files(project).items():
                    if name in NOT_SCANNED:
                        continue
                    self.assertIsNone(LOOP_TEXT.search(data.decode(errors="replace")), f"loop text in {name}")

    def test_the_loop_is_on_by_default_and_owns_the_same_files_in_every_template(self) -> None:
        owned = None
        for project_type, answers in LEAVES:
            with self.subTest(project_type=project_type, **answers):
                project = render(project_type, **answers)
                found = loop_files(project)
                self.assertIn(".github/workflows/loop-ci.yml", found)
                self.assertIn("loop: true", (project / ".copier-answers.yml").read_text())
                owned = found if owned is None else owned
                self.assertEqual(owned, found)

    def test_every_template_reaches_the_one_loop_folder_and_none_holds_a_copy(self) -> None:
        folder = ROOT / "templates/_loop"
        for template in sorted(path.parent for path in (ROOT / "templates").glob("*/*/mise.toml.jinja")):
            links = [path for path in template.rglob("*") if path.is_symlink() and "{% if loop" in path.name]
            with self.subTest(template=str(template.relative_to(ROOT))):
                self.assertTrue(links)
                self.assertTrue(all(folder in path.resolve().parents for path in links))
        copies = [path for path in (ROOT / "templates").rglob("*") if not path.is_symlink() and path.is_file()
                  and re.search(r"approvals|loop\.md|issue-tracker|gatekeeper|loop-ci", path.name)
                  and folder not in path.parents]
        self.assertEqual([], copies)


class LoopSwitchTest(unittest.TestCase):
    """One plain copier update, with -d loop=..., turns the loop on or off."""

    OWN_README = "\nOur own paragraph, written after the project was made.\n"

    def setUp(self) -> None:
        self.dir = scratch()
        self.template = publish(ROOT, self.dir / "template", "v1.0.0")
        self.project = self.dir / "project"

    def make(self, loop: bool) -> None:
        copier("copy", "--trust", "--defaults", "--skip-tasks", "-d", "project_name=switch",
               "-d", "project_type=software/python", "-d", f"loop={str(loop).lower()}", str(self.template), str(self.project))
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
        commit(self.project, "generated")
        with (self.project / "README.md").open("a") as readme:
            readme.write(self.OWN_README)
        commit(self.project, "our own edit")

    def fresh(self, loop: bool) -> Path:
        project = self.dir / f"fresh-{loop}"
        copier("copy", "--trust", "--defaults", "--skip-tasks", "-d", "project_name=switch",
               "-d", "project_type=software/python", "-d", f"loop={str(loop).lower()}", str(self.template), str(project))
        return project

    def update(self, loop: bool) -> None:
        copier("update", "--trust", "--defaults", "--skip-tasks", "-d", f"loop={str(loop).lower()}", cwd=self.project)

    def changed(self) -> set[str]:
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=self.project,
                                capture_output=True, text=True, check=True).stdout
        return {line[3:] for line in status.splitlines()}

    def test_turning_the_loop_on_adds_exactly_its_files_and_lines_and_keeps_our_edit(self) -> None:
        self.make(loop=False)
        before = files(self.project)
        self.update(loop=True)
        after = files(self.project)
        expected = loop_files(render("software/python"))
        self.assertEqual(expected | {".copier-answers.yml"}, self.changed())
        self.assertEqual(expected, set(after) - set(before))
        self.assertEqual([".copier-answers.yml"], sorted(name for name in before if before[name] != after.get(name)))
        self.assertIs(True, yaml.safe_load((self.project / ".copier-answers.yml").read_text())["loop"])
        self.assertTrue(after["README.md"].decode().endswith(self.OWN_README))  # the project's own edit is kept
        fresh = files(self.fresh(loop=True))
        skip = {"README.md", ".copier-answers.yml"}
        self.assertEqual({n: d for n, d in fresh.items() if n not in skip}, {n: d for n, d in after.items() if n not in skip})

    def test_turning_the_loop_off_removes_exactly_its_files_and_lines_and_keeps_our_edit(self) -> None:
        self.make(loop=True)
        before = files(self.project)
        self.update(loop=False)
        after = files(self.project)
        removed = set(before) - set(after)
        self.assertEqual(loop_files(render("software/python")), removed)
        self.assertEqual(removed | {".copier-answers.yml"}, self.changed())
        self.assertEqual([".copier-answers.yml"], sorted(name for name in after if before[name] != after[name]))
        self.assertIs(False, yaml.safe_load((self.project / ".copier-answers.yml").read_text())["loop"])
        self.assertTrue(after["README.md"].decode().endswith(self.OWN_README))
        self.assertEqual(set(), loop_files(self.project))

    def test_the_loop_switches_on_and_off_again_to_where_it_began(self) -> None:
        self.make(loop=False)
        start = files(self.project)
        self.update(loop=True)
        commit(self.project, "loop on")
        self.update(loop=False)
        self.assertEqual(start, files(self.project))


class MigrationTest(unittest.TestCase):
    """A project made from the template before this change moves with one plain copier update."""

    NEW = {".github/workflows/loop-ci.yml", ".mise/conf.d/loop.toml", ".apm/instructions/loop.instructions.md"}

    def setUp(self) -> None:
        self.dir = scratch()
        old = self.dir / "old"
        old.mkdir()
        try:
            archive = subprocess.run(["git", "archive", BEFORE], cwd=ROOT, check=True, capture_output=True).stdout
        except subprocess.CalledProcessError:
            self.skipTest(f"{BEFORE[:7]} is not in this clone's history (a shallow checkout)")
        subprocess.run(["tar", "x", "-C", str(old)], input=archive, check=True)
        self.template = publish(old, self.dir / "template", "v1.0.0")

    def migrate(self, **answers: str) -> tuple[Path, Path]:
        """A project from the old release, then the template moved to this tree and one plain update."""
        project = self.dir / "project"
        copier("copy", "--trust", "--defaults", "--skip-tasks", "-d", "project_name=migrate", "-d", "project_type=software/python",
               *[arg for key, value in answers.items() for arg in ("-d", f"{key}={value}")], str(self.template), str(project))
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        commit(project, "generated from the old release")
        old_project = self.dir / "as-generated"
        shutil.copytree(project, old_project, ignore=IGNORE)
        for entry in self.template.iterdir():
            if entry.name != ".git":
                shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
        for entry in ROOT.iterdir():
            if entry.name not in SKIP:
                if entry.is_dir():
                    shutil.copytree(entry, self.template / entry.name, ignore=IGNORE)
                else:
                    shutil.copy2(entry, self.template / entry.name)
        subprocess.run(["git", "add", "-A"], cwd=self.template, check=True)
        subprocess.run([*GIT, "commit", "--no-verify", "-qm", "v2"], cwd=self.template, check=True)
        subprocess.run(["git", "tag", "v2.0.0"], cwd=self.template, check=True)
        copier("update", "--trust", "--defaults", "--skip-tasks", cwd=project)
        return old_project, project

    def test_a_loop_on_project_keeps_its_loop_files_and_checks_and_gains_loop_check(self) -> None:
        old, project = self.migrate()
        answers = yaml.safe_load((project / ".copier-answers.yml").read_text())
        self.assertEqual("v2.0.0", answers["_commit"])
        self.assertIs(True, answers["loop"])
        self.assertNotIn("engineering_loop", answers)
        before = loop_files(old)
        self.assertIn("docs/agents/loop.md", before)
        self.assertEqual(before | self.NEW, loop_files(project))
        for name in sorted(n for n in before if n.startswith("docs/agents/")):
            self.assertEqual((old / name).read_bytes(), (project / name).read_bytes(), name)
        self.assertEqual([*required_checks(old)[:2], "loop-check", "loop:approvals"], required_checks(project))

    def test_a_loop_off_project_stays_off(self) -> None:
        old, project = self.migrate(engineering_loop="false")
        self.assertEqual(set(), loop_files(old))
        self.assertEqual(set(), loop_files(project))
        answers = yaml.safe_load((project / ".copier-answers.yml").read_text())
        self.assertIs(False, answers["loop"])
        self.assertNotIn("engineering_loop", answers)


if __name__ == "__main__":
    unittest.main()
