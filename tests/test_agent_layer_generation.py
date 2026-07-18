from __future__ import annotations

import subprocess
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
                "include_fnox",
                "mise run agent-sync",
                "mise run agent-check",
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

    def test_agent_task_extension_seams_are_local_and_apm_selects_targets(self) -> None:
        apm = (ROOT / "templates/_base/_apm_yml.part").read_text()
        tasks = (ROOT / "templates/_base/_mise_agent_tasks.part").read_text()

        self.assertIn("Add each coding agent's APM mapping here", apm)
        self.assertIn("native-output validation", tasks)
        self.assertIn("stable CLI", tasks)
        self.assertNotIn("--target claude,codex", tasks)

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
            "jdx/mise-action@dad1bfd3df957f44999b559dd69dc1671cb4e9ea", workflow
        )
        self.assertIn(
            "mise exec terraform@1.15.8 tflint@0.63.1 --",
            workflow,
        )

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
        self.assertIn("apm: []", apm)
        self.assertIn("mcp: []", apm)

        mise = tomllib.loads((project / "mise.toml").read_text())
        self.assertEqual("0.25.0", mise["tools"].get("github:microsoft/apm"))
        self.assertEqual("1.30.0", mise["tools"]["fnox"])
        self.assertEqual(
            {"agent-sync", "agent-check", "agent-claude", "agent-codex"},
            set(mise["tasks"])
            & {
                "agent-sync",
                "agent-check",
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
            "error: apm 0.25.0 is required; run 'mise install'",
            "error: fnox 1.30.0 is required; run 'mise install'",
            "error: python3 is required; run 'mise install'",
            "error: claude is required; install Claude Code and add 'claude' to PATH",
            "error: codex is required; install Codex and add 'codex' to PATH",
        ):
            self.assertIn(remediation, (project / "mise.toml").read_text())

    def test_apm_version_has_one_template_source(self) -> None:
        partial = (ROOT / "templates/_base/_mise_agent_tasks.part").read_text()

        self.assertIn('{% set apm_version = "0.25.0" %}', partial)
        self.assertEqual(1, partial.count("0.25.0"))

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
