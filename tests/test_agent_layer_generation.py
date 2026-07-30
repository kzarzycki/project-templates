from __future__ import annotations

import os
import subprocess
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
MISE = shutil.which("mise")
assert MISE is not None


def render(project_type: str = "software/python", **answers: object) -> Path:
    scratch = Path(tempfile.mkdtemp(prefix="project-template-test-"))
    template = scratch / "template"
    shutil.copytree(
        ROOT,
        template,
        ignore=shutil.ignore_patterns(
            ".git",
            ".superpowers",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "__pycache__",
            "_out",
            "apm_modules",
            "node_modules",
        ),
    )
    destination = scratch / "project"
    command = [
        "copier",
        "copy",
        "--trust",
        "--defaults",
        "--skip-tasks",
        "--data",
        "project_name=agent-layer-test",
        "--data",
        f"project_type={project_type}",
    ]
    for key, value in answers.items():
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        command.extend(("--data", f"{key}={rendered}"))
    command.extend((str(template), str(destination)))
    subprocess.run(command, check=True, capture_output=True, text=True)
    return destination


class AgentLayerGenerationTest(unittest.TestCase):
    def test_public_docs_explain_agent_layer_scaffold_and_activation(self) -> None:
        readme = (ROOT / "README.md").read_text()
        skill = (ROOT / "skills/bootstrap-project/SKILL.md").read_text()
        wrapper = (ROOT / "skills/bootstrap-project/scripts/bootstrap.sh").read_text()

        for document in (readme, skill):
            for expected in (
                "include_agent_layer",
                "include_engineering_workflow",
                "include_fnox",
                "mise run agent-sync",
                "mise run agent-sync -- --refresh",
                "mise run agent-sync -- --frozen",
                "mise run agent-claude",
                "mise run agent-codex",
            ):
                self.assertIn(expected, document)
            self.assertIn("project-owned", document)
            self.assertIn("mise install", document)
            self.assertIn("trusted", document.lower())

        self.assertNotIn("apm install", wrapper)
        self.assertNotIn("fnox check", wrapper)

    def test_coding_agent_copy_describes_current_and_planned_integrations(self) -> None:
        readme = (ROOT / "README.md").read_text()
        copier = (ROOT / "copier.yml").read_text()
        skill = (ROOT / "skills/bootstrap-project/SKILL.md").read_text()
        instruction = (
            ROOT / "templates/_base/_project_instructions.md.jinja"
        ).read_text()
        readme_flat = " ".join(readme.split())

        self.assertIn(
            "Claude Code and Codex are the only coding agents currently implemented "
            "and acceptance-tested.",
            readme_flat,
        )
        self.assertIn(
            "GitHub Copilot and Cursor are planned integrations, not supported coding agents.",
            readme_flat,
        )
        for extension_step in (
            "APM mapping",
            "native-output validation",
            "stable CLI",
            "acceptance fixture",
            "product-specific setup docs",
        ):
            self.assertIn(extension_step, readme)

        self.assertIn("coding agent configuration", copier)
        self.assertNotIn(
            "Add the APM source and mise tasks for Claude Code and Codex?",
            copier,
        )
        self.assertIn("coding-agent integration", skill)
        self.assertIn("coding agent instructions", instruction)
        self.assertNotIn("shared by Claude Code and Codex", instruction)

    def test_update_docs_state_legacy_agent_answers_are_breaking(self) -> None:
        readme = (ROOT / "README.md").read_text()
        readme_flat = " ".join(readme.split())

        self.assertNotIn("copier update --trust", readme)
        for answer in (
            "shared_apm",
            "toolkit_stack",
            "include_agent_layer",
            "include_engineering_workflow",
            "include_fnox",
        ):
            self.assertIn(answer, readme)
        self.assertIn("not automatically compatible", readme_flat)
        self.assertIn("resolve or replace old coding agent files", readme_flat)

    def test_agent_task_extension_seams_are_local_and_apm_selects_targets(self) -> None:
        apm = (ROOT / "templates/_base/_apm_yml.part").read_text()
        example_apm = (ROOT / "examples/agent-layer-mvp/apm.yml").read_text()
        tasks = (ROOT / "templates/_base/_mise_agent_tasks.part").read_text()
        mapping_comment = (
            "# Add each coding agent's APM mapping here. Claude Code and Codex are the\n"
            "# currently implemented and acceptance-tested integrations."
        )

        self.assertIn(mapping_comment, apm)
        self.assertIn(mapping_comment, example_apm)
        self.assertIn("native-output validation", tasks)
        self.assertIn("stable CLI", tasks)
        self.assertNotIn("--target claude,codex", tasks)

    def test_generated_state_comment_uses_coding_agent_term(self) -> None:
        gitignore = (ROOT / "templates/_base/_gitignore.part").read_text()

        self.assertIn("# Coding-agent generated/cache state", gitignore)
        self.assertNotIn("# Agent layer generated/cache state", gitignore)

    def test_ci_covers_every_leaf_and_agent_layer_contract(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        for project_type in (
            "software/python",
            "software/node",
            "software/java",
            "data/dbt",
            "authoring/content",
            "ai/skills",
            "ai/mcp",
            "infra/terraform",
        ):
            self.assertIn(f"type: {project_type}", workflow)
        self.assertIn("{ type: ai/mcp, language: python }", workflow)
        self.assertIn("{ type: ai/mcp, language: node }", workflow)
        self.assertIn("include_agent_layer=true", workflow)
        self.assertIn("include_fnox=true", workflow)
        self.assertIn("test -f apm.yml", workflow)
        self.assertIn("test -f fnox.toml", workflow)
        self.assertIn("test ! -e .agents-toolkit", workflow)
        self.assertIn(
            "jdx/mise-action@9e7f7633ff6f6d6048a9418a68d48f288f50eb14", workflow
        )
        self.assertIn(
            "mise exec terraform@1.15.8 tflint@0.63.1 --",
            workflow,
        )
        self.assertIn("verify:", workflow)
        for command in (
            "python3 -m unittest",
            "tests.test_agent_layer_generation",
            "tests.test_agent_mise_tasks",
            "tests.test_bootstrap_local_source",
            "tests.test_version_contract",
            "working-directory: examples/agent-layer-mvp",
            "mise run agent-sync -- --frozen",
            "mise run test",
        ):
            self.assertIn(command, workflow)

    def test_enabled_layer_generates_framework_without_project_policy(self) -> None:
        project = render(
            include_mise=True,
            include_agent_layer=True,
            include_fnox=True,
        )

        self.assertTrue((project / "apm.yml").is_file())
        self.assertTrue((project / "fnox.toml").is_file())
        self.assertTrue(
            (project / ".apm/instructions/project.instructions.md").is_file()
        )
        instruction = (
            project / ".apm/instructions/project.instructions.md"
        ).read_text()
        self.assertIn("description: Project-wide instructions", instruction)
        self.assertIn('applyTo: "**"', instruction)
        self.assertFalse((project / ".agents-toolkit").exists())
        self.assertFalse((project / "scripts/agent-layer").exists())

        apm = (project / "apm.yml").read_text()
        self.assertIn("- claude", apm)
        self.assertIn("- codex", apm)
        self.assertEqual(
            [
                {
                    "git": "kzarzycki/agent-skills/engineering",
                    "ref": "^0.2.0",
                }
            ],
            yaml.safe_load(apm)["dependencies"]["apm"],
        )
        self.assertIn("mcp: []", apm)

        mise = tomllib.loads((project / "mise.toml").read_text())
        self.assertEqual("0.26.0", mise["tools"].get("github:microsoft/apm"))
        self.assertEqual("1.30.0", mise["tools"]["fnox"])
        self.assertEqual(
            {"agent-sync", "agent-claude", "agent-codex"},
            set(mise["tasks"])
            & {
                "agent-sync",
                "agent-claude",
                "agent-codex",
            },
        )
        rendered = "\n".join(
            path.read_text(errors="ignore")
            for path in project.rglob("*")
            if path.is_file()
        ).lower()
        for forbidden in (
            ".agents-toolkit",
            "dotagents",
            "1password",
            "github_token",
        ):
            self.assertNotIn(forbidden, rendered)
        for remediation in (
            "error: apm 0.26.0 is required; run 'mise install'",
            "error: fnox 1.30.0 is required; run 'mise install'",
            "error: python3 is required; run 'mise install'",
            "error: claude is required; install Claude Code and add 'claude' to PATH",
            "error: codex is required; install Codex and add 'codex' to PATH",
        ):
            self.assertIn(remediation, (project / "mise.toml").read_text())

    def test_engineering_workflow_is_enabled_by_default(self) -> None:
        project = render(
            include_mise=True,
            include_agent_layer=True,
            include_fnox=False,
        )

        manifest = (project / "apm.yml").read_text()
        answers = (project / ".copier-answers.yml").read_text()
        self.assertEqual(1, manifest.count("git: kzarzycki/agent-skills/engineering"))
        self.assertIn("ref: ^0.2.0", manifest)
        self.assertIn("include_engineering_workflow: true", answers)
        self.assertNotIn("engineering_capability_source", answers)
        self.assertNotIn("engineering_capability_ref", answers)

    def test_engineering_workflow_can_be_disabled(self) -> None:
        project = render(
            include_mise=True,
            include_agent_layer=True,
            include_engineering_workflow=False,
            include_fnox=False,
        )

        manifest = (project / "apm.yml").read_text()
        answers = (project / ".copier-answers.yml").read_text()
        self.assertIn("apm: []", manifest)
        self.assertNotIn("agent-skills/engineering", manifest)
        self.assertIn("include_engineering_workflow: false", answers)

    def test_engineering_workflow_converges_offline_for_claude_and_codex(self) -> None:
        fixture = Path(tempfile.mkdtemp(prefix="engineering-fixture-"))
        shutil.copytree(
            ROOT / "tests/fixtures/engineering",
            fixture,
            dirs_exist_ok=True,
        )
        subprocess.run(["git", "init", "-q"], cwd=fixture, check=True)
        subprocess.run(["git", "add", "."], cwd=fixture, check=True)
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
                "engineering 0.2.0",
            ],
            cwd=fixture,
            check=True,
        )
        subprocess.run(
            ["git", "tag", "engineering-v0.2.0"],
            cwd=fixture,
            check=True,
        )
        project = render(
            include_mise=True,
            include_agent_layer=True,
            include_engineering_workflow=True,
            engineering_capability_source="https://fixture.invalid/test/engineering.git",
            engineering_capability_ref="^0.2.0",
            include_fnox=False,
        )
        isolated_home = Path(tempfile.mkdtemp(prefix="agent-sync-home-"))
        for directory in (
            "xdg-cache",
            "xdg-config",
            "xdg-data",
            "xdg-state",
            "mise-cache",
            "mise-config",
            "mise-data",
            "mise-state",
            "claude",
            "codex",
        ):
            (isolated_home / directory).mkdir()
        git_config = isolated_home / "gitconfig"
        git_config.write_text(
            f'[url "file://{fixture}"]\n'
            "  insteadOf = https://fixture.invalid/test/engineering.git\n"
        )
        env = {
            key: os.environ[key]
            for key in ("LANG", "LC_ALL", "PATH", "SHELL", "TERM", "TMPDIR")
            if key in os.environ
        }
        env.update(
            {
                "HOME": str(isolated_home),
                "XDG_CACHE_HOME": str(isolated_home / "xdg-cache"),
                "XDG_CONFIG_HOME": str(isolated_home / "xdg-config"),
                "XDG_DATA_HOME": str(isolated_home / "xdg-data"),
                "XDG_STATE_HOME": str(isolated_home / "xdg-state"),
                "MISE_CACHE_DIR": str(isolated_home / "mise-cache"),
                "MISE_CONFIG_DIR": str(isolated_home / "mise-config"),
                "MISE_DATA_DIR": str(isolated_home / "mise-data"),
                "MISE_OFFLINE": "true",
                "MISE_STATE_DIR": str(isolated_home / "mise-state"),
                "MISE_TRUSTED_CONFIG_PATHS": str(project),
                "APM_NO_CACHE": "1",
                "CLAUDE_CONFIG_DIR": str(isolated_home / "claude"),
                "CODEX_HOME": str(isolated_home / "codex"),
                "GIT_CONFIG_GLOBAL": str(git_config),
                "GIT_CONFIG_NOSYSTEM": "1",
                "NO_COLOR": "1",
            }
        )

        scoped_instruction = project / ".apm/instructions/source.instructions.md"
        scoped_instruction.write_text(
            "---\n"
            "description: Source-tree instructions\n"
            'applyTo: "src/**"\n'
            "---\n\n"
            "Read the source tree before editing it.\n"
        )

        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        subprocess.run(["git", "add", "."], cwd=project, check=True)
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
                "render",
            ],
            cwd=project,
            check=True,
        )

        first = subprocess.run(
            [MISE, "run", "--skip-tools", "agent-sync"],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        expected_v020 = (fixture / "skills/wayfinder/SKILL.md").read_text()
        for installed in (
            ".claude/skills/wayfinder/SKILL.md",
            ".agents/skills/wayfinder/SKILL.md",
        ):
            self.assertEqual(expected_v020, (project / installed).read_text())
        self.assertTrue((project / "apm.lock.yaml").is_file())
        nested_agents = next((project / "src").rglob("AGENTS.md"))
        self.assertTrue(nested_agents.is_file())
        self.assertIn(
            "engineering-v0.2.0",
            (project / "apm.lock.yaml").read_text(),
        )

        subprocess.run(["git", "add", "."], cwd=project, check=True)
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
                "converge",
            ],
            cwd=project,
            check=True,
        )

        scoped_instruction.unlink()
        cleanup = subprocess.run(
            [MISE, "run", "--skip-tools", "agent-sync"],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, cleanup.returncode, cleanup.stdout + cleanup.stderr)
        self.assertFalse(nested_agents.exists())
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
                "remove scoped instructions",
            ],
            cwd=project,
            check=True,
        )

        second = subprocess.run(
            [MISE, "run", "--skip-tools", "agent-sync"],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        self.assertEqual(
            "",
            subprocess.run(
                ["git", "status", "--porcelain=v1", "--untracked-files=all"],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
            ).stdout,
        )

        source_skill = fixture / "skills/wayfinder/SKILL.md"
        source_skill.write_text(source_skill.read_text() + "\nUpdated fixture.\n")
        subprocess.run(["git", "add", "."], cwd=fixture, check=True)
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
                "engineering 0.2.1",
            ],
            cwd=fixture,
            check=True,
        )
        subprocess.run(
            ["git", "tag", "engineering-v0.2.1"],
            cwd=fixture,
            check=True,
        )
        refresh = subprocess.run(
            [MISE, "run", "--skip-tools", "agent-sync", "--", "--refresh"],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, refresh.returncode, refresh.stdout + refresh.stderr)
        expected_v021 = source_skill.read_text()
        for installed in (
            ".claude/skills/wayfinder/SKILL.md",
            ".agents/skills/wayfinder/SKILL.md",
        ):
            self.assertEqual(expected_v021, (project / installed).read_text())
        self.assertIn(
            "engineering-v0.2.1",
            (project / "apm.lock.yaml").read_text(),
        )
        subprocess.run(["git", "add", "."], cwd=project, check=True)
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
                "refresh",
            ],
            cwd=project,
            check=True,
        )

        frozen = subprocess.run(
            [MISE, "run", "--skip-tools", "agent-sync", "--", "--frozen"],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, frozen.returncode, frozen.stdout + frozen.stderr)

        installed_skill = project / ".agents/skills/wayfinder/SKILL.md"
        installed_skill.write_text(installed_skill.read_text() + "\nstale\n")
        stale = subprocess.run(
            [MISE, "run", "--skip-tools", "agent-sync", "--", "--frozen"],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(0, stale.returncode)
        self.assertIn("frozen agent configuration changed", stale.stderr)

    def test_apm_version_has_one_template_source(self) -> None:
        partial = (ROOT / "templates/_base/_mise_agent_tasks.part").read_text()

        self.assertIn('{% set apm_version = "0.26.0" %}', partial)
        self.assertEqual(1, partial.count("0.26.0"))

    def test_disabled_layer_leaves_no_agent_framework(self) -> None:
        project = render(include_mise=True, include_agent_layer=False)

        self.assertFalse((project / "apm.yml").exists())
        self.assertFalse((project / "fnox.toml").exists())
        self.assertFalse((project / ".apm").exists())
        self.assertFalse((project / ".agents-toolkit").exists())
        self.assertNotIn("agent-sync", (project / "mise.toml").read_text())

    def test_agent_layer_pins_python_when_leaf_does_not(self) -> None:
        project = render(
            "software/node",
            include_mise=True,
            include_agent_layer=True,
            include_fnox=False,
        )

        mise = tomllib.loads((project / "mise.toml").read_text())
        self.assertEqual("3.14", mise["tools"].get("python"))

    def test_task_descriptions_do_not_claim_fnox_when_it_is_disabled(self) -> None:
        project = render(
            include_mise=True,
            include_agent_layer=True,
            include_fnox=False,
        )

        tasks = tomllib.loads((project / "mise.toml").read_text())["tasks"]
        self.assertEqual(
            "Converge project-owned coding agent configuration.",
            tasks["agent-sync"]["description"],
        )
        self.assertEqual("Launch Claude Code.", tasks["agent-claude"]["description"])
        self.assertEqual("Launch Codex.", tasks["agent-codex"]["description"])
        for task in ("agent-claude", "agent-codex"):
            description = tasks[task]["description"].lower()
            self.assertNotIn("fnox", description)
            self.assertNotIn("machine bindings", description)

    def test_agent_layer_is_disabled_without_mise(self) -> None:
        project = render(
            include_mise=False,
            include_agent_layer=True,
            include_fnox=True,
        )

        self.assertFalse((project / "mise.toml").exists())
        self.assertFalse((project / "apm.yml").exists())
        self.assertFalse((project / "fnox.toml").exists())
        self.assertFalse((project / ".apm").exists())

    def test_disabled_layer_is_absent_from_every_leaf(self) -> None:
        leaves = (
            ("software/python", {}),
            ("software/node", {}),
            ("software/java", {}),
            ("data/dbt", {}),
            ("authoring/content", {}),
            ("ai/skills", {}),
            ("ai/mcp", {"language": "python"}),
            ("infra/terraform", {"include_example": False}),
        )
        for project_type, extra in leaves:
            with self.subTest(project_type=project_type):
                project = render(
                    project_type,
                    include_mise=True,
                    include_agent_layer=False,
                    **extra,
                )
                self.assertFalse((project / "apm.yml").exists())
                self.assertFalse((project / "fnox.toml").exists())
                self.assertFalse((project / ".apm").exists())
                self.assertFalse((project / ".agents-toolkit").exists())
                self.assertNotIn("agent-sync", (project / "mise.toml").read_text())


if __name__ == "__main__":
    unittest.main()
