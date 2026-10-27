from __future__ import annotations

import atexit
import json
import os
import re
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


def settings(text: str) -> dict:
    """A docs/agents/ file's ```yaml settings block as the pack's approvals.py reads it, with safe_load."""
    found = re.search(r"^## Settings\n.*?^```yaml[ \t]*\n(.*?)^```[ \t]*$", text, re.DOTALL | re.MULTILINE)
    assert found, "no ```yaml block under ## Settings"
    return yaml.safe_load(found[1])


def evaluate(expression: str, github: dict) -> object:
    """A GitHub Actions expression (`${{ }}` optional) over a `github` context, for the operators and
    functions the rendered workflows use. Like Actions, && and || return an operand and startsWith ignores
    case; unlike Actions, == compares strings by case."""
    functions = {
        "ctx": lambda path: _lookup(github, path),
        "startsWith": lambda text, prefix: str(text or "").lower().startswith(str(prefix).lower()),
        "fromJSON": json.loads,
        "format": lambda pattern, *args: pattern.format(*args),
    }
    parts = re.split(r"('(?:[^']|'')*')", expression.strip().removeprefix("${{").removesuffix("}}"))
    parts[1::2] = ["r" + literal for literal in parts[1::2]]  # Actions strings have no backslash escapes
    for index in range(0, len(parts), 2):  # outside string literals
        code = re.sub(r"\bgithub(?:\.\w+)+", lambda match: f"ctx({match.group()!r})", parts[index])
        parts[index] = code.replace("&&", " and ").replace("||", " or ").replace("!=", "\0").replace("!", " not ").replace("\0", "!=")
    return eval("(" + "".join(parts) + ")", {"__builtins__": {}}, functions)


def _lookup(github: dict, path: str) -> object:
    value: object = github
    for key in path.split(".")[1:]:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def render(project_type: str = "software/python", existing: dict[str, bytes] | None = None, **answers: object) -> Path:
    scratch = Path(tempfile.mkdtemp(prefix="project-template-test-"))
    atexit.register(shutil.rmtree, scratch, True)
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
            "tmp",
            "apm_modules",
            "node_modules",
        ),
    )
    destination = scratch / "project"
    for name, content in (existing or {}).items():  # the repo's own files, there before the render
        (destination / name).parent.mkdir(parents=True, exist_ok=True)
        (destination / name).write_bytes(content)
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


def isolated_agent_env(project: Path) -> dict[str, str]:
    home = Path(tempfile.mkdtemp(prefix="agent-sync-home-"))
    directories = {
        name: home / name
        for name in (
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
        )
    }
    for directory in directories.values():
        directory.mkdir()
    env = {
        key: os.environ[key]
        for key in ("LANG", "LC_ALL", "PATH", "SHELL", "TERM", "TMPDIR")
        if key in os.environ
    }
    env.update(
        {
            "HOME": str(home),
            "XDG_CACHE_HOME": str(directories["xdg-cache"]),
            "XDG_CONFIG_HOME": str(directories["xdg-config"]),
            "XDG_DATA_HOME": str(directories["xdg-data"]),
            "XDG_STATE_HOME": str(directories["xdg-state"]),
            "MISE_CACHE_DIR": str(directories["mise-cache"]),
            "MISE_CONFIG_DIR": str(directories["mise-config"]),
            "MISE_DATA_DIR": str(directories["mise-data"]),
            "MISE_OFFLINE": "true",
            "MISE_STATE_DIR": str(directories["mise-state"]),
            "MISE_TRUSTED_CONFIG_PATHS": str(project),
            "APM_NO_CACHE": "1",
            "CLAUDE_CONFIG_DIR": str(directories["claude"]),
            "CODEX_HOME": str(directories["codex"]),
            "GIT_CONFIG_NOSYSTEM": "1",
            "NO_COLOR": "1",
        }
    )
    return env


def commit_project(project: Path, message: str) -> None:
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
            message,
        ],
        cwd=project,
        check=True,
    )


def run_agent_sync(
    project: Path, env: dict[str, str], *arguments: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [MISE, "run", "--skip-tools", "agent:sync", "--", *arguments],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
    )


def tag_fixture_release(fixture: Path, version: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=fixture, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "commit", "--no-verify", "-qm", f"engineering {version}"],
        cwd=fixture,
        check=True,
    )
    subprocess.run(["git", "tag", f"engineering-v{version}"], cwd=fixture, check=True)


def fixture_pack_env(project: Path) -> tuple[Path, dict[str, str]]:
    """The offline fixture pack as a git repo tagged engineering-v0.2.0, and an env that resolves it."""
    fixture = Path(tempfile.mkdtemp(prefix="engineering-fixture-"))
    shutil.copytree(ROOT / "tests/fixtures/engineering", fixture, dirs_exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=fixture, check=True)
    tag_fixture_release(fixture, "0.2.0")
    env = isolated_agent_env(project)
    git_config = Path(env["HOME"]) / "gitconfig"
    git_config.write_text(
        f'[url "file://{fixture}"]\n'
        "  insteadOf = https://fixture.invalid/test/engineering.git\n"
    )
    env["GIT_CONFIG_GLOBAL"] = str(git_config)
    return fixture, env


def run_mise_task(project: Path, env: dict[str, str], task: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [MISE, "run", "--skip-tools", task, "--", *arguments],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
    )


LEAVES = (
    ("software/python", {}),
    ("software/node", {}),
    ("software/java", {}),
    ("data/dbt", {}),
    ("authoring/content", {}),
    ("ai/skills", {}),
    ("ai/mcp", {"language": "python"}),
    ("ai/mcp", {"language": "node"}),
    ("infra/terraform", {}),
    ("apple/xcode", {}),
)


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
                "mise run agent:sync",
                "mise run agent:sync -- --refresh",
                "mise run agent:sync -- --frozen",
                "mise run agent:claude",
                "mise run agent:codex",
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
            "apple/xcode",
        ):
            self.assertIn(f"type: {project_type}", workflow)
        self.assertIn("{ type: apple/xcode, os: macos-latest }", workflow)  # its gate needs Xcode
        self.assertIn("runs-on: ${{ matrix.os || 'ubuntu-latest' }}", workflow)
        self.assertIn("{ type: ai/mcp, language: python }", workflow)
        self.assertIn("{ type: ai/mcp, language: node }", workflow)
        self.assertIn("include_agent_layer=true", workflow)
        self.assertIn("include_fnox=true", workflow)
        self.assertIn("test -f apm.yml", workflow)
        self.assertIn("test -f fnox.toml", workflow)
        self.assertIn("test ! -e .agents-toolkit", workflow)
        self.assertIn("engineering_loop=true", workflow)
        self.assertIn("grep -q '^\\[tasks.check\\]$' mise.toml", workflow)
        self.assertIn("run: mise run check:all", workflow)
        self.assertIn("run: mise run ci:parts", workflow)
        self.assertIn("test -f docs/agents/loop.md", workflow)
        self.assertIn(
            "jdx/mise-action@c2a87611a18de5b3828c5652fe268e992400cb5c", workflow
        )
        self.assertIn(
            "mise exec terraform@1.15.8 tflint@0.63.1 --",
            workflow,
        )
        self.assertIn("verify:", workflow)
        for command in (
            "PyYAML==6.0.3",
            "github:microsoft/apm@0.33.0",
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
                    "ref": "engineering-v0.24.1",
                }
            ],
            yaml.safe_load(apm)["dependencies"]["apm"],
        )
        self.assertIn("mcp: []", apm)

        mise = tomllib.loads((project / "mise.toml").read_text())
        self.assertEqual("0.33.0", mise["tools"].get("github:microsoft/apm"))
        self.assertEqual("1.30.0", mise["tools"]["fnox"])
        self.assertEqual(
            {"agent:sync": "agent-sync", "agent:claude": "agent-claude", "agent:codex": "agent-codex"},
            {name: mise["tasks"][name].get("alias") for name in ("agent:sync", "agent:claude", "agent:codex")},
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
            "error: apm 0.33.0 is required; run 'mise install'",
            "error: fnox 1.30.0 is required; run 'mise install'",
            "error: python3 is required; run 'mise install'",
            "error: claude is required; install Claude Code and add 'claude' to PATH",
            "error: codex is required; install Codex and add 'codex' to PATH",
        ):
            self.assertIn(remediation, (project / "mise.toml").read_text())

    def test_description_and_author_with_colon_render_valid_apm_yml(self) -> None:
        description, author = "Infra: server, network and DNS", "Doe: Jr"
        project = render("infra/terraform", description=description, author=author)
        manifest = yaml.safe_load((project / "apm.yml").read_text())
        self.assertEqual((description, author), (manifest["description"], manifest["author"]))

    def test_engineering_workflow_is_enabled_by_default(self) -> None:
        project = render(
            include_mise=True,
            include_agent_layer=True,
            include_fnox=False,
        )

        manifest = (project / "apm.yml").read_text()
        answers = (project / ".copier-answers.yml").read_text()
        self.assertEqual(1, manifest.count("git: kzarzycki/agent-skills/engineering"))
        self.assertIn("ref: engineering-v0.24.1", manifest)
        self.assertIn("include_engineering_workflow: true", answers)
        self.assertNotIn("engineering_capability_source", answers)
        self.assertNotIn("engineering_capability_ref", answers)
        template = (project / ".github/PULL_REQUEST_TEMPLATE.md").read_text()
        self.assertEqual(
            ["## Summary", "## Evidence", "## Merge Danger"],
            [line for line in template.splitlines() if line.startswith("## ")],
        )
        self.assertIn("`loop:approvals` rejects a PR without this section.", template)

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
        template = (project / ".github/PULL_REQUEST_TEMPLATE.md").read_text()
        self.assertIn("## What & why", template)
        self.assertNotIn("Merge Danger", template)

    def test_disabled_engineering_workflow_converges_and_freezes(self) -> None:
        project = render(
            include_mise=True,
            include_agent_layer=True,
            include_engineering_workflow=False,
            include_fnox=False,
        )
        env = isolated_agent_env(project)
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        commit_project(project, "render disabled workflow")

        first = run_agent_sync(project, env)
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        commit_project(project, "converge disabled workflow")

        second = run_agent_sync(project, env)
        frozen = run_agent_sync(project, env, "--frozen")
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        self.assertEqual(0, frozen.returncode, frozen.stdout + frozen.stderr)
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

    def test_additional_agent_adapter_preserves_payload_and_dependency(self) -> None:
        fixture = Path(tempfile.mkdtemp(prefix="engineering-adapter-fixture-"))
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
            engineering_capability_source=(
                "https://fixture.invalid/test/engineering.git"
            ),
            engineering_capability_ref="^0.2.0",
            include_fnox=False,
        )
        manifest_path = project / "apm.yml"
        manifest = yaml.safe_load(manifest_path.read_text())
        dependency = manifest["dependencies"]["apm"]
        fixture_before = {
            path.relative_to(fixture).as_posix(): path.read_bytes()
            for path in fixture.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(fixture).parts
        }
        manifest["targets"].append("copilot")
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
        env = isolated_agent_env(project)
        git_config = Path(env["HOME"]) / "gitconfig"
        git_config.write_text(
            f'[url "file://{fixture}"]\n'
            "  insteadOf = https://fixture.invalid/test/engineering.git\n"
        )
        env["GIT_CONFIG_GLOBAL"] = str(git_config)
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        commit_project(project, "add synthetic adapter")

        result = run_agent_sync(project, env)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(
            dependency, yaml.safe_load(manifest_path.read_text())["dependencies"]["apm"]
        )
        self.assertEqual(
            fixture_before,
            {
                path.relative_to(fixture).as_posix(): path.read_bytes()
                for path in fixture.rglob("*")
                if path.is_file() and ".git" not in path.relative_to(fixture).parts
            },
        )
        expected_skill = (fixture / "skills/wayfinder/SKILL.md").read_bytes()
        for installed in (
            ".claude/skills/wayfinder/SKILL.md",
            ".agents/skills/wayfinder/SKILL.md",
        ):
            self.assertEqual(expected_skill, (project / installed).read_bytes())
        self.assertTrue(
            any((project / ".github/instructions").glob("*.instructions.md"))
        )

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
        env = isolated_agent_env(project)
        git_config = Path(env["HOME"]) / "gitconfig"
        git_config.write_text(
            f'[url "file://{fixture}"]\n'
            "  insteadOf = https://fixture.invalid/test/engineering.git\n"
        )
        env["GIT_CONFIG_GLOBAL"] = str(git_config)

        scoped_instruction = project / ".apm/instructions/source.instructions.md"
        scoped_instruction.write_text(
            "---\n"
            "description: Source-tree instructions\n"
            'applyTo: "src/**"\n'
            "---\n\n"
            "Read the source tree before editing it.\n"
        )

        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        commit_project(project, "render")

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

        manifest_path = project / "apm.yml"
        manifest_current = manifest_path.read_text()
        manifest_path.write_text(manifest_current.replace("^0.2.0", "^0.4.0"))
        commit_project(project, "stale manifest")
        stale_manifest = subprocess.run(
            [MISE, "run", "--skip-tools", "agent-sync", "--", "--frozen"],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(0, stale_manifest.returncode)
        self.assertNotIn("frozen agent configuration changed", stale_manifest.stderr)
        manifest_path.write_text(manifest_current)
        commit_project(project, "restore manifest")

        lock_path = project / "apm.lock.yaml"
        lock_current = lock_path.read_text()
        lock_path.write_text("not: [valid\n")
        commit_project(project, "stale lock")
        stale_lock = subprocess.run(
            [MISE, "run", "--skip-tools", "agent-sync", "--", "--frozen"],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(0, stale_lock.returncode)
        self.assertNotIn("frozen agent configuration changed", stale_lock.stderr)
        lock_path.write_text(lock_current)
        commit_project(project, "restore lock")

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

    def test_vendored_layer_takes_a_local_skill_edit_through_intake_offline(self) -> None:
        project = render(
            agent_layer_mode="vendored",
            engineering_capability_source="https://fixture.invalid/test/engineering.git",
            engineering_capability_ref="^0.2.0",
            include_fnox=False,
        )
        fixture, env = fixture_pack_env(project)
        root_files = {name: (project / name).read_bytes() for name in ("CLAUDE.md", "AGENTS.md")}
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        commit_project(project, "render")

        first = run_agent_sync(project, env)
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        self.assertEqual(root_files, {name: (project / name).read_bytes() for name in root_files})
        commit_project(project, "sync")

        # 1. An edited skill file, committed: sync refuses and leaves the edit.
        skill = project / ".claude/skills/wayfinder/SKILL.md"
        edited = skill.read_text() + "\nLocal edit.\n"
        skill.write_text(edited)
        commit_project(project, "edit a skill")
        refused = run_agent_sync(project, env)
        self.assertEqual(1, refused.returncode, refused.stdout + refused.stderr)
        self.assertIn(".claude/skills/wayfinder/SKILL.md", refused.stderr)
        self.assertIn("mise run agent:intake", refused.stderr)
        self.assertEqual(edited, skill.read_text())

        # 2. Intake writes one patch, the plain diff of the pack's copy and the edit.
        intake = run_mise_task(project, env, "agent:intake")
        self.assertEqual(1, intake.returncode, intake.stdout + intake.stderr)
        patches = sorted(path.relative_to(project).as_posix() for path in (project / ".agent-intake").rglob("*.patch"))
        self.assertEqual([".agent-intake/.claude/skills/wayfinder/SKILL.md.patch"], patches)
        self.assertIn(patches[0], intake.stdout)
        pristine = project / "apm_modules/test/engineering/skills/wayfinder/SKILL.md"
        plain = subprocess.run(["diff", "-u", str(pristine), str(skill)], capture_output=True, text=True).stdout

        def hunks(diff: str) -> str:
            return diff[diff.index("@@"):]

        self.assertEqual(hunks(plain), hunks((project / patches[0]).read_text()))
        self.assertEqual("", subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=project, check=True, capture_output=True, text=True,
        ).stdout)  # the intake directory is ignored and the tree untouched
        self.assertEqual(1, run_agent_sync(project, env).returncode)  # still unresolved

        # 3. The pack ports the edit and releases it: refresh resolves the patch.
        release = fixture / "skills/wayfinder/SKILL.md"
        release.write_text(
            "---\n"
            "name: wayfinder\n"
            "description: Orient in a repository by reading project evidence before acting.\n"
            "---\n"
            "\n"
            "# Wayfinder\n"
            "\n"
            "Read the repository's instructions and representative project files before\n"
            "proposing changes.\n"
            "\n"
            "Local edit.\n"
        )
        tag_fixture_release(fixture, "0.2.1")
        refresh = run_mise_task(project, env, "agent:intake", "--refresh")
        self.assertEqual(0, refresh.returncode, refresh.stdout + refresh.stderr)
        self.assertIn("resolved", refresh.stdout)
        self.assertFalse((project / patches[0]).exists())
        self.assertIn("engineering-v0.2.1", (project / "apm.lock.yaml").read_text())
        self.assertEqual(release.read_text(), skill.read_text())

        synced = run_agent_sync(project, env)
        self.assertEqual(0, synced.returncode, synced.stdout + synced.stderr)
        commit_project(project, "take engineering 0.2.1")

        # A dropped patch: delete it, and sync restores the pack's copy.
        codex_skill = project / ".agents/skills/wayfinder/SKILL.md"
        codex_skill.write_text(codex_skill.read_text() + "\nA dropped edit.\n")
        commit_project(project, "edit the codex copy")
        self.assertEqual(1, run_mise_task(project, env, "agent:intake").returncode)
        (project / ".agent-intake/.agents/skills/wayfinder/SKILL.md.patch").unlink()
        dropped = run_agent_sync(project, env)
        self.assertEqual(0, dropped.returncode, dropped.stdout + dropped.stderr)
        self.assertEqual(release.read_text(), codex_skill.read_text())
        self.assertFalse((project / ".agent-intake").exists())
        self.assertEqual(root_files, {name: (project / name).read_bytes() for name in root_files})
        commit_project(project, "drop the codex edit")

        again = run_agent_sync(project, env)
        frozen = run_agent_sync(project, env, "--frozen")
        self.assertEqual(0, again.returncode, again.stdout + again.stderr)
        self.assertEqual(0, frozen.returncode, frozen.stdout + frozen.stderr)
        self.assertEqual("", subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=project, check=True, capture_output=True, text=True,
        ).stdout)

    def test_vendored_intake_sees_the_edits_once_apm_yml_ref_is_ahead_of_the_lock(self) -> None:
        project = render(
            agent_layer_mode="vendored",
            engineering_capability_source="https://fixture.invalid/test/engineering.git",
            engineering_capability_ref="^0.2.0",
            include_fnox=False,
        )
        fixture, env = fixture_pack_env(project)
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        commit_project(project, "render")
        first = run_agent_sync(project, env)
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        commit_project(project, "sync")

        # The pack's next minor carries one copy's edit and not the other's.
        release = fixture / "skills/wayfinder/SKILL.md"
        release.write_text(release.read_text() + "\nA line the pack released.\n")
        tag_fixture_release(fixture, "0.3.0")
        kept, carried = project / ".claude/skills/wayfinder/SKILL.md", project / ".agents/skills/wayfinder/SKILL.md"
        edit = kept.read_text() + "\nA local edit the pack never took.\n"
        kept.write_text(edit)
        carried.write_text(release.read_text())
        commit_project(project, "edit both skill copies")

        # ^0.2.0 excludes 0.3.0, so the bump edits the ref first; a fresh clone has no install cache.
        manifest = project / "apm.yml"
        manifest.write_text(manifest.read_text().replace("^0.2.0", "^0.3.0"))
        commit_project(project, "take engineering 0.3")
        shutil.rmtree(project / "apm_modules")
        audit = subprocess.run(["apm", "audit", "--ci", "--no-policy", "-f", "json"],
                               cwd=project, env=env, capture_output=True, text=True)
        self.assertEqual([], json.loads(audit.stdout)["drift"]["drift"])  # apm's own drift check cannot run here

        refused = run_agent_sync(project, env)
        self.assertEqual(1, refused.returncode, refused.stdout + refused.stderr)
        for path in (".claude/skills/wayfinder/SKILL.md", ".agents/skills/wayfinder/SKILL.md"):
            self.assertIn(f"{path} differs from the pack's copy", refused.stderr)
        intake = run_mise_task(project, env, "agent:intake")
        self.assertEqual(1, intake.returncode, intake.stdout + intake.stderr)
        self.assertIn("mise run agent:intake -- --refresh", intake.stderr)
        self.assertEqual(edit, kept.read_text())

        refresh = run_mise_task(project, env, "agent:intake", "--refresh")
        self.assertEqual(1, refresh.returncode, refresh.stdout + refresh.stderr)
        self.assertIn("engineering-v0.3.0", (project / "apm.lock.yaml").read_text())
        self.assertIn("resolved: the release carries the edit to .agents/skills/wayfinder/SKILL.md", refresh.stdout)
        self.assertEqual(release.read_text(), carried.read_text())
        self.assertEqual(edit, kept.read_text())
        patches = sorted(path.relative_to(project).as_posix() for path in (project / ".agent-intake").rglob("*.patch"))
        self.assertEqual([".agent-intake/.claude/skills/wayfinder/SKILL.md.patch"], patches)
        against_release = subprocess.run(["diff", "-u", str(release), str(kept)], capture_output=True, text=True).stdout
        patch = (project / patches[0]).read_text()
        self.assertEqual(against_release[against_release.index("@@"):], patch[patch.index("@@"):])

    def test_vendored_refresh_keeps_an_edit_to_a_file_the_release_removes_as_a_patch_from_dev_null(self) -> None:
        project = render(
            agent_layer_mode="vendored",
            engineering_capability_source="https://fixture.invalid/test/engineering.git",
            engineering_capability_ref="^0.2.0",
            include_fnox=False,
        )
        fixture, env = fixture_pack_env(project)
        for name in ("reference.md", "notes.md"):
            (fixture / "skills/wayfinder" / name).write_text(f"The pack's {name}.\n")
        tag_fixture_release(fixture, "0.2.1")
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        commit_project(project, "render")
        first = run_agent_sync(project, env)
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        commit_project(project, "sync")

        # One file edited, one deleted; the next minor removes both.
        edited, deleted = project / ".claude/skills/wayfinder/reference.md", project / ".claude/skills/wayfinder/notes.md"
        edited.write_text("A local reference.\n")
        deleted.unlink()
        commit_project(project, "edit the references")
        for name in ("reference.md", "notes.md"):
            (fixture / "skills/wayfinder" / name).unlink()
        tag_fixture_release(fixture, "0.3.0")
        manifest = project / "apm.yml"
        manifest.write_text(manifest.read_text().replace("^0.2.0", "^0.3.0"))
        commit_project(project, "take engineering 0.3")

        refresh = run_mise_task(project, env, "agent:intake", "--refresh")
        self.assertEqual(1, refresh.returncode, refresh.stdout + refresh.stderr)
        self.assertNotIn("reference.md", (project / "apm.lock.yaml").read_text())
        self.assertIn("resolved: the release carries the edit to .claude/skills/wayfinder/notes.md", refresh.stdout)
        self.assertFalse(deleted.exists())
        self.assertEqual("A local reference.\n", edited.read_text())
        patches = sorted(path.relative_to(project).as_posix() for path in (project / ".agent-intake").rglob("*.patch"))
        self.assertEqual([".agent-intake/.claude/skills/wayfinder/reference.md.patch"], patches)
        patch = (project / patches[0]).read_text()
        self.assertEqual("@@ -0,0 +1 @@\n+A local reference.\n", patch[patch.index("@@"):])

        # The patch keeps the guard up through sync and a plain intake, until it is dropped.
        refused = run_agent_sync(project, env)
        self.assertEqual(1, refused.returncode, refused.stdout + refused.stderr)
        self.assertIn(f"{patches[0]} is unresolved", refused.stderr)
        again = run_mise_task(project, env, "agent:intake")
        self.assertEqual(1, again.returncode, again.stdout + again.stderr)
        self.assertTrue((project / patches[0]).is_file())
        self.assertEqual("A local reference.\n", edited.read_text())

        (project / patches[0]).unlink()
        dropped = run_agent_sync(project, env)
        self.assertEqual(0, dropped.returncode, dropped.stdout + dropped.stderr)
        self.assertFalse(edited.exists())
        self.assertFalse((project / ".agent-intake").exists())

    def skill_the_release_removes(self) -> tuple[Path, dict[str, str], Path, str]:
        """An edited skill, taken in, that the next minor replaces with another skill; refreshed onto it."""
        project = render(
            agent_layer_mode="vendored",
            engineering_capability_source="https://fixture.invalid/test/engineering.git",
            engineering_capability_ref="^0.2.0",
            include_fnox=False,
        )
        fixture, env = fixture_pack_env(project)
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        commit_project(project, "render")
        first = run_agent_sync(project, env)
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        commit_project(project, "sync")
        skill = project / ".claude/skills/wayfinder/SKILL.md"
        skill.write_text(skill.read_text() + "\nA local edit.\n")
        commit_project(project, "edit wayfinder")
        self.assertEqual(1, run_mise_task(project, env, "agent:intake").returncode)

        shutil.copytree(fixture / "skills/wayfinder", fixture / "skills/other")
        shutil.rmtree(fixture / "skills/wayfinder")
        tag_fixture_release(fixture, "0.3.0")
        manifest = project / "apm.yml"
        manifest.write_text(manifest.read_text().replace("^0.2.0", "^0.3.0"))
        commit_project(project, "take engineering 0.3")
        refresh = run_mise_task(project, env, "agent:intake", "--refresh")
        self.assertEqual(1, refresh.returncode, refresh.stdout + refresh.stderr)
        self.assertTrue(skill.is_file())
        patch = project / ".agent-intake/.claude/skills/wayfinder/SKILL.md.patch"
        self.assertTrue(patch.is_file())
        patch.unlink()  # drop the edit
        return project, env, skill, refresh.stdout

    def test_vendored_sync_removes_a_dropped_edit_to_a_skill_the_release_removes(self) -> None:
        project, env, skill, refreshed = self.skill_the_release_removes()

        dropped = run_agent_sync(project, env)

        self.assertEqual(0, dropped.returncode, dropped.stdout + dropped.stderr)
        self.assertIn("removed .claude/skills/wayfinder/SKILL.md", dropped.stdout)
        self.assertFalse(skill.parent.exists())
        self.assertNotIn("wayfinder", (project / "apm.lock.yaml").read_text())
        self.assertTrue((project / ".claude/skills/other/SKILL.md").is_file())
        self.assertFalse((project / ".agent-intake").exists())
        commit_project(project, "drop the wayfinder edit")
        frozen = run_agent_sync(project, env, "--frozen")
        self.assertEqual(0, frozen.returncode, frozen.stdout + frozen.stderr)
        self.assertNotIn("resolved:", refreshed)  # APM kept the edited file; the release does not carry it

    def test_vendored_sync_keeps_a_newer_edit_to_a_skill_the_release_removes(self) -> None:
        project, env, skill, _ = self.skill_the_release_removes()
        newer = skill.read_text() + "\nA newer edit.\n"
        skill.write_text(newer)

        refused = run_agent_sync(project, env)

        self.assertEqual(1, refused.returncode, refused.stdout + refused.stderr)
        self.assertIn(".claude/skills/wayfinder/SKILL.md", refused.stderr)
        self.assertEqual(newer, skill.read_text())
        self.assertTrue((project / ".agent-intake/intaken").is_file())

        # Intake takes the newer edit in; dropping it removes the skill.
        self.assertEqual(1, run_mise_task(project, env, "agent:intake").returncode)
        (project / ".agent-intake/.claude/skills/wayfinder/SKILL.md.patch").unlink()
        dropped = run_agent_sync(project, env)
        self.assertEqual(0, dropped.returncode, dropped.stdout + dropped.stderr)
        self.assertFalse(skill.parent.exists())

    def test_vendored_render_keeps_hand_written_root_files_and_compiles_nothing(self) -> None:
        for project_type, answers in LEAVES:
            with self.subTest(project_type=project_type, **answers):
                project = render(project_type, agent_layer_mode="vendored", **answers)

                self.assertFalse((project / ".apm").exists())
                tasks = tomllib.loads((project / "mise.toml").read_text())["tasks"]
                self.assertNotIn("check:agents", tasks)
                self.assertIn("agent:intake", tasks)
                self.assertNotIn("apm compile", tasks["agent:sync"]["run"])
                self.assertIn("apm prune", tasks["agent:sync"]["run"])
                self.assertIn("`CLAUDE.md`", (project / "AGENTS.md").read_text())
                self.assertIn(
                    "Every change that lands as a PR runs the `engineering-loop` skill, unless your personal instructions say `Engineering loop: off`",
                    (project / "CLAUDE.md").read_text(),
                )
                self.assertIn(".agent-intake/", (project / ".gitignore").read_text().splitlines())
                managed = re.compile(tomllib.loads((project / "mise.toml").read_text())["env"]["APM_MANAGED"])
                for path in (".agents/skills/wayfinder/SKILL.md", ".claude/skills/wayfinder/SKILL.md", ".codex/config.toml"):
                    self.assertRegex(path, managed)
                for path in ("CLAUDE.md", "AGENTS.md", ".github/instructions/project.instructions.md"):
                    self.assertNotRegex(path, managed)

        no_loop = render(agent_layer_mode="vendored", engineering_loop=False)
        self.assertNotIn("engineering-loop", (no_loop / "CLAUDE.md").read_text())
        compiled = render()
        self.assertFalse((compiled / "AGENTS.md").exists())  # apm compile writes it
        self.assertNotIn(".agent-intake/", (compiled / ".gitignore").read_text())

    def test_copier_update_leaves_a_vendored_projects_own_root_files_byte_identical(self) -> None:
        scratch = Path(tempfile.mkdtemp(prefix="vendored-update-"))
        atexit.register(shutil.rmtree, scratch, True)
        template = scratch / "template"
        shutil.copytree(ROOT, template, ignore=shutil.ignore_patterns(".git", "tmp", "apm_modules", "__pycache__", "_out"))
        git = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com"]
        subprocess.run(["git", "init", "-q"], cwd=template, check=True)
        subprocess.run(["git", "add", "-A"], cwd=template, check=True)
        subprocess.run([*git, "commit", "--no-verify", "-qm", "v1"], cwd=template, check=True)
        subprocess.run(["git", "tag", "v1.0.0"], cwd=template, check=True)

        # An existing repo with its own CLAUDE.md adopts the template.
        project = scratch / "project"
        project.mkdir()
        own = {"CLAUDE.md": b"# Our project\n\nHand-written instructions.\n", "AGENTS.md": b"Read CLAUDE.md.\n"}
        for name, data in own.items():
            (project / name).write_bytes(data)
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        subprocess.run(["git", "add", "-A"], cwd=project, check=True)
        subprocess.run([*git, "commit", "--no-verify", "-qm", "own"], cwd=project, check=True)
        subprocess.run(
            ["copier", "copy", "--trust", "--defaults", "--skip-tasks", "--overwrite",
             "--data", "project_name=agent-layer-test", "--data", "project_type=software/python",
             "--data", "agent_layer_mode=vendored", str(template), str(project)],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(own, {name: (project / name).read_bytes() for name in own})
        subprocess.run(["git", "add", "-A"], cwd=project, check=True)
        subprocess.run([*git, "commit", "--no-verify", "-qm", "adopt"], cwd=project, check=True)

        conventions = template / "templates/_base/_claude_conventions.md.jinja"
        conventions.write_text(conventions.read_text() + "- **New:** a template change.\n")
        subprocess.run(["git", "add", "-A"], cwd=template, check=True)
        subprocess.run([*git, "commit", "--no-verify", "-qm", "v2"], cwd=template, check=True)
        subprocess.run(["git", "tag", "v2.0.0"], cwd=template, check=True)
        subprocess.run(
            ["copier", "update", "--trust", "--defaults", "--skip-tasks"],
            cwd=project, check=True, capture_output=True, text=True,
        )

        self.assertIn("_commit: v2.0.0", (project / ".copier-answers.yml").read_text())
        self.assertEqual(own, {name: (project / name).read_bytes() for name in own})

    def test_loop_render_seeds_approvals_ci_skeletons_and_loop_line(self) -> None:
        project = render()

        mise = tomllib.loads((project / "mise.toml").read_text())
        tasks = mise["tasks"]
        self.assertEqual(["check:lint", "check:unit"], tasks["check"]["depends"])
        self.assertEqual(["check:*"], tasks["check:all"]["depends"])
        self.assertIn("mise run --skip-tools agent:sync -- --frozen", tasks["check:agents"]["run"])
        self.assertEqual("mise run --skip-tools --jobs 1 --continue-on-error 'lint:*'", tasks["check:lint"]["run"])
        workflow = (project / ".github/workflows/ci.yml").read_text()
        self.assertEqual(["plan", "part", "check"], list(yaml.safe_load(workflow)["jobs"]))
        self.assertNotIn("pytest", workflow)
        approvals_run = tasks["loop:approvals"]["run"]
        self.assertEqual("gate", tasks["loop:approvals"]["alias"])
        self.assertIn("mise run agent:sync", approvals_run[0])
        self.assertEqual(
            'uv run .agents/skills/engineering-loop/scripts/approvals.py check "${usage_point}" ${usage_pr:-}',
            approvals_run[-1],
        )
        self.assertEqual(
            'uv run .agents/skills/engineering-loop/scripts/approvals.py land "${usage_pr}" $([ "${usage_wait:-false}" = true ] && echo --wait)',
            tasks["loop:land"]["run"][-1],
        )
        self.assertFalse((project / ".github/workflows/gate.yml").exists())
        approvals = yaml.safe_load((project / ".github/workflows/approvals.yml").read_text())
        [(job_name, job)] = approvals["jobs"].items()
        self.assertEqual("approvals", job_name)  # not loop:approvals: its check run must not stand in for the status
        self.assertEqual("mise run ci:approvals", job["steps"][-1]["run"])
        self.assertEqual({"install_args": "uv"}, job["steps"][-2]["with"])  # uv runs approvals.py with its PyYAML
        self.assertEqual("write", job["permissions"]["statuses"])  # posts loop:approvals
        # The least that turns auto-merge on: write on contents and pull requests, read on the rest.
        self.assertEqual(
            {
                "contents": "write",
                "issues": "write",
                "pull-requests": "write",
                "checks": "read",
                "actions": "read",
                "statuses": "write",
            },
            job["permissions"],
        )
        self.assertEqual({}, approvals["permissions"])
        # Auto-merge is pinned to the head the proofs covered, and only after a success, never on a request.
        approvals_task = tasks["ci:approvals"]["run"]
        self.assertIn('gh pr merge "$PR" --auto --squash --match-head-commit "$head"', approvals_task)
        self.assertLess(approvals_task.index('post "$head" success "${first'), approvals_task.index("gh pr merge"))
        self.assertLess(approvals_task.index("autoMergeRequest"), approvals_task.index("gh pr merge"))
        on = approvals[True]  # PyYAML reads `on` as True
        self.assertIn("labeled", on["pull_request"]["types"])
        self.assertIn("synchronize", on["pull_request"]["types"])
        self.assertIn("merge_group", on)
        self.assertEqual({"types": ["submitted", "dismissed"]}, on["pull_request_review"])  # the verdict is a review
        # A review event, like a PR event, never runs on a draft or for dependabot.
        self.assertIn(
            "((github.event_name == 'pull_request' || github.event_name == 'pull_request_review')"
            " && !github.event.pull_request.draft && github.actor != 'dependabot[bot]')",
            job["if"],
        )
        # The token is github.token unless the repo names a GitHub App, whose token gets this job's permissions.
        app = next(step for step in job["steps"] if step.get("id") == "app")
        self.assertEqual("${{ vars.APPROVALS_APP_CLIENT_ID != '' }}", app["if"])
        self.assertEqual("${{ secrets.APPROVALS_APP_PRIVATE_KEY }}", app["with"]["private-key"])
        self.assertEqual(
            {name.removeprefix("permission-"): value for name, value in app["with"].items() if name.startswith("permission-")},
            job["permissions"],
        )
        self.assertEqual("${{ steps.app.outputs.token || github.token }}", job["steps"][-1]["env"]["GH_TOKEN"])
        self.assertEqual("${{ steps.app.outputs.token != '' }}", job["steps"][-1]["env"]["APP_TOKEN"])
        self.assertIn("actions/variables/APPROVALS_APP_CLIENT_ID", tasks["setup:github"]["run"])
        self.assertIn("actions/secrets/APPROVALS_APP_PRIVATE_KEY", tasks["setup:github"]["run"])
        ci_name = yaml.safe_load(workflow)["name"]
        self.assertEqual({"workflows": [ci_name], "types": ["completed"]}, on["workflow_run"])
        self.assertIn("context=loop:approvals", tasks["ci:approvals"]["run"])
        self.assertIn("issues/$PR/labels/approved:merge", tasks["ci:approvals"]["run"])
        self.assertEqual("merge-queue", tasks["setup:github"]["alias"])
        self.assertIn("-F allow_auto_merge=true -F delete_branch_on_merge=true", tasks["setup:github"]["run"])
        self.assertIn("labels=.agents/skills/engineering-loop/scripts/labels.py", tasks["setup:github"]["run"])
        self.assertIn(".worktrees/", (project / ".gitignore").read_text().splitlines())
        hooks = {
            hook["id"]: hook
            for repo in yaml.safe_load((project / ".pre-commit-config.yaml").read_text())["repos"]
            for hook in repo["hooks"]
        }
        for name in ("test:changed", "check:secrets"):
            self.assertEqual(
                {"id": name, "name": name, "entry": f"mise run {name}", "language": "system",
                 "pass_filenames": False, "always_run": True, "stages": ["pre-push"]},
                hooks[name],
            )
        approvals_seed = (project / "docs/agents/loop.md").read_text()
        self.assertIn("Only people approve", approvals_seed)
        # The seed's policy as the pack reads it: the verifier judges risk, CI, CODEOWNERS and loop.md stay the owner's.
        # Only the old line form is gone; the alternatives are documented, not switched on.
        self.assertEqual(
            {
                "spec": {"auto": ["bug", "follow-up", "sub-issue"]},
                "risk": {"verifier": True, "paths": [".github/**", "CODEOWNERS", "docs/agents/loop.md"]},
            },
            settings(approvals_seed),
        )
        self.assertNotRegex(approvals_seed, re.compile(r"^[ \t]*[-*] +(?:spec|plan|merge|risk|bot|signoff):", re.MULTILINE))
        for line in ("`auto: true`", "`signoff`", "`opt_out: true`", "`Engineering loop: off`", "`always: true`"):
            self.assertIn(line, approvals_seed)
        # board maps each loop column to the board column of its own name, as the pack's board.py reads it.
        loop_columns = ["Intent", "Needs owner", "Ready", "Build", "Verify", "Sign-off", "Done"]
        tracker = settings((project / "docs/agents/issue-tracker.md").read_text())
        self.assertEqual({column: column for column in loop_columns}, tracker["board"])
        self.assertEqual(["components", "board"], list(tracker))  # categories, labels and renames are commented out
        for name, headings in (
            (
                "loop.md",
                (
                    "Settings",
                    "Owner",
                    "Proof on a branch",
                    "Acceptance references",
                    "Approvals",
                    "Risk criteria",
                    "In use",
                    "Worktree",
                    "Ledger",
                    "Verifier checklist",
                ),
            ),
            (
                "issue-tracker.md",
                ("Settings", "Never on GitHub"),
            ),
            ("coding-standards.md", ("Domain facts",)),
        ):
            text = (project / "docs/agents" / name).read_text()
            self.assertNotIn("Landing exceptions", text)
            if name == "issue-tracker.md":
                self.assertTrue(
                    text.startswith("Tracker: GitHub (engineering-loop's github.md)\n")
                )
            self.assertEqual(
                [f"## {heading}" for heading in headings],
                re.findall(r"^## .*", text, re.MULTILINE),
            )
        self.assertIn(
            "Every change that lands as a PR runs the `engineering-loop` skill, unless your personal instructions say `Engineering loop: off`",
            (project / ".apm/instructions/project.instructions.md").read_text(),
        )

    def test_every_leaf_lands_through_a_merge_queue_requiring_its_own_jobs(self) -> None:
        contract = {
            "check", "check:all", "check:lint", "check:unit", "check:secrets", "check:agents",
            "test:fast", "test:unit", "test:changed", "ci:parts", "ci:check", "ci:approvals",
            "loop:approvals", "loop:land", "setup:dev", "setup:github", "agent:sync", "agent:claude", "agent:codex",
        }
        aliases = {
            "check:lint": ["lint", "fmt"], "test:fast": "test", "setup:dev": "bootstrap",
            "loop:approvals": "gate", "setup:github": "merge-queue", "agent:sync": "agent-sync",
            "agent:claude": "agent-claude", "agent:codex": "agent-codex",
        }
        for project_type, answers in LEAVES:
            with self.subTest(project_type=project_type, **answers):
                project = render(project_type, **answers)
                # No CODEOWNERS: its automatic review requests notify the owners on every loop PR.
                self.assertEqual([], [path for path in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS") if (project / path).exists()])

                tasks = tomllib.loads((project / "mise.toml").read_text())["tasks"]
                self.assertEqual(set(), contract - set(tasks))
                expected = {**aliases, "test:fast": {"ai/skills": ["test", "validate"], "data/dbt": None}.get(project_type, "test")}
                self.assertEqual(expected, {name: tasks[name].get("alias") for name in aliases})  # dbt's test is dbt test
                self.assertTrue([name for name in tasks if name.startswith("lint:")])

                ci = yaml.safe_load((project / ".github/workflows/ci.yml").read_text())
                self.assertIn("ready_for_review", ci[True]["pull_request"]["types"])
                self.assertIn("merge_group", ci[True])
                self.assertEqual(
                    "ci-${{ github.event_name == 'pull_request' && github.ref || github.sha }}",
                    ci["concurrency"]["group"],
                )
                self.assertEqual("${{ github.event_name == 'pull_request' }}", ci["concurrency"]["cancel-in-progress"])
                jobs = ci["jobs"]
                self.assertEqual(["plan", "part", "check"], list(jobs))
                # Only the parts run the project's checks; an Apple project's need Xcode.
                runners = {"plan": "ubuntu-latest", "check": "ubuntu-latest",
                           "part": "macos-latest" if project_type == "apple/xcode" else "ubuntu-latest"}
                self.assertEqual(runners, {name: job["runs-on"] for name, job in jobs.items()})
                self.assertEqual("${{ !github.event.pull_request.draft }}", jobs["plan"]["if"])
                self.assertEqual("${{ always() && !github.event.pull_request.draft }}", jobs["check"]["if"])
                self.assertEqual(["plan", "part"], jobs["check"]["needs"])
                self.assertEqual("${{ fromJSON(needs.plan.outputs.parts) }}", jobs["part"]["strategy"]["matrix"]["part"])
                self.assertEqual("${{ matrix.part }}", jobs["part"]["name"])
                # a stale uv.lock fails the part rather than being rewritten by setup:dev (#29)
                self.assertEqual("1", jobs["part"]["env"]["UV_LOCKED"])
                self.assertEqual(
                    "${{ github.base_ref || github.event.merge_group.base_sha || github.event.before }}",
                    jobs["part"]["steps"][-1]["env"]["BASE_REF"],
                )
                yaml.safe_load((project / ".github/check-paths.yml").read_text())  # paths-filter reads it

                # The tracker's components as the pack's labels.py reads them: each an `area:` label with its text.
                tracker = settings((project / "docs/agents/issue-tracker.md").read_text())
                components = tracker["components"]
                self.assertGreater(len(components), 2)  # the leaf's own parts, then tooling and docs
                self.assertEqual([], [name for name, text in components.items() if not name.startswith("area:") or not text])
                self.assertIs(True, settings((project / "docs/agents/loop.md").read_text())["risk"]["verifier"])

                # Every step that runs a command runs a mise task: the task is the check's one definition.
                for workflow in (project / ".github/workflows").glob("*.yml"):
                    for job_name, job in yaml.safe_load(workflow.read_text())["jobs"].items():
                        for step in job["steps"]:
                            if "run" in step:
                                self.assertRegex(step["run"], r"^mise run \S+$", f"{workflow.name} {job_name}")

                # The ruleset's two names: CI's aggregate job and the status the approvals step posts.
                ruleset = json.loads((project / ".github/rulesets/main.json").read_text())
                rules = {rule["type"]: rule.get("parameters") for rule in ruleset["rules"]}
                required = [check["context"] for check in rules["required_status_checks"]["required_status_checks"]]
                self.assertEqual(["check", "loop:approvals"], required)
                self.assertEqual("check", jobs["check"].get("name", "check"))  # the check run's name, not just the key
                self.assertEqual(15368, rules["required_status_checks"]["required_status_checks"][0]["integration_id"])  # GitHub Actions
                self.assertIn("context=loop:approvals", tasks["ci:approvals"]["run"])
                self.assertEqual("SQUASH", rules["merge_queue"]["merge_method"])
                self.assertEqual("ALLGREEN", rules["merge_queue"]["grouping_strategy"])
                self.assertEqual(["squash"], rules["pull_request"]["allowed_merge_methods"])
                self.assertTrue(rules["pull_request"]["required_review_thread_resolution"])  # an open thread blocks the merge
                self.assertEqual([], ruleset["bypass_actors"])

                # Hooks: one local repo, no rev; each commit hook calls its own lint: task.
                config = yaml.safe_load((project / ".pre-commit-config.yaml").read_text())
                self.assertEqual(["local"], [repo["repo"] for repo in config["repos"]])
                self.assertNotIn("rev", config["repos"][0])
                for hook in config["repos"][0]["hooks"]:
                    self.assertEqual("system", hook["language"], hook["id"])
                    if hook.get("stages") == ["pre-push"]:
                        self.assertEqual(f"mise run {hook['id']}", hook["entry"])
                    else:
                        self.assertTrue(hook["id"].startswith("lint:"), hook["id"])
                        self.assertEqual(f"mise run {hook['id']} --", hook["entry"])
                        self.assertIn(hook["id"], tasks)
                # The tasks' helper scripts exist at the path they call, in the case they call it.
                scripts = (project / tasks["lint:symlinks"]["run"]).parent
                self.assertIn(scripts.name, {path.name for path in project.iterdir()})
                self.assertTrue(os.access(scripts / "files-or-repo", os.X_OK))
                self.assertTrue(os.access(scripts / "check-symlinks.sh", os.X_OK))
                self.assertIn(f"run = '{scripts.name}/files-or-repo ", (project / "mise.toml").read_text())

    def test_without_a_merge_queue_the_ruleset_keeps_every_other_rule(self) -> None:
        # GitHub offers merge queues only on organization-owned repos; every leaf includes the one ruleset template.
        queued = json.loads((render() / ".github/rulesets/main.json").read_text())
        ruleset = json.loads((render(merge_queue=False) / ".github/rulesets/main.json").read_text())

        self.assertEqual("loop-merge-queue", ruleset["name"])  # setup:github finds its ruleset by this name
        self.assertEqual(
            {**queued, "rules": [rule for rule in queued["rules"] if rule["type"] != "merge_queue"]}, ruleset
        )
        self.assertEqual(["deletion", "non_fast_forward", "pull_request", "required_status_checks"],
                         [rule["type"] for rule in ruleset["rules"]])

    def test_node_coverage_gate_compares_against_the_commit_ci_passes(self) -> None:
        project = render("software/node")
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        commit_project(project, "scaffold")
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project, check=True,
                              capture_output=True, text=True).stdout.strip()
        (project / "src/index.ts").write_text((project / "src/index.ts").read_text() + "export const added = 1;\n")
        commit_project(project, "change")

        def gate(ref: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(["node", "scripts/check-coverage.mjs"], cwd=project,
                                  env={**os.environ, "BASE_REF": ref}, capture_output=True, text=True)

        compared = gate(base)  # the change is seen, so the gate wants its coverage
        self.assertEqual(1, compared.returncode)
        self.assertIn("coverage/coverage-final.json not found", compared.stderr)
        missing = gate("0" * 40)  # a push that created the branch: no commit before it
        self.assertEqual(0, missing.returncode, missing.stderr)
        self.assertIn("no commits to compare against", missing.stdout)

    def test_without_the_example_an_adopted_repo_gets_no_starter_code(self) -> None:
        project = render(include_example=False)
        self.assertFalse((project / "src").exists())
        self.assertFalse((project / "tests/test_smoke.py").exists())
        self.assertTrue((project / "mise.toml").exists())

    def test_without_the_example_an_mcp_repo_runs_no_starter_smoke_check(self) -> None:
        for language in ("python", "node"):
            with self.subTest(language=language):
                project = render("ai/mcp", language=language, include_example=False)

                self.assertEqual([], list(project.glob("scripts/smoke*")))
                for name in ("mise.toml", ".github/workflows/ci.yml", "package.json"):
                    if (project / name).exists():
                        self.assertNotIn("smoke", (project / name).read_text())

    def test_loop_off_renders_no_loop_files(self) -> None:
        for answers in ({"engineering_loop": False}, {"include_engineering_workflow": False}):
            with self.subTest(**answers):
                project = render(**answers)

                tasks = tomllib.loads((project / "mise.toml").read_text())["tasks"]
                self.assertFalse((project / "docs/agents").exists())
                self.assertEqual(set(), {"loop:approvals", "loop:land", "ci:approvals", "setup:github"} & set(tasks))
                self.assertFalse((project / ".github/workflows/approvals.yml").exists())
                self.assertFalse((project / ".github/workflows/gate.yml").exists())
                self.assertFalse((project / ".github/rulesets").exists())
                self.assertNotIn(
                    "engineering-loop",
                    (project / ".apm/instructions/project.instructions.md").read_text(),
                )

    def test_without_ci_only_approvals_is_written_and_merges_wait_for_it_alone(self) -> None:
        ship = b"name: Ship\non: workflow_dispatch\njobs: {}\n"  # the repo's own workflow, not valid for any linter
        project = render(existing={".github/workflows/ship.yml": ship}, include_ci=False)

        self.assertEqual(ship, (project / ".github/workflows/ship.yml").read_bytes())
        self.assertEqual(["approvals.yml", "ship.yml"], sorted(path.name for path in (project / ".github/workflows").iterdir()))
        self.assertFalse((project / ".github/check-paths.yml").exists())
        self.assertTrue((project / "renovate.json").exists())  # not CI
        tasks = tomllib.loads((project / "mise.toml").read_text())["tasks"]
        self.assertEqual(set(), {"ci:parts", "ci:check"} & set(tasks))
        self.assertIn("ci:approvals", tasks)

        ruleset = json.loads((project / ".github/rulesets/main.json").read_text())
        [checks] = [rule["parameters"] for rule in ruleset["rules"] if rule["type"] == "required_status_checks"]
        self.assertEqual([{"context": "loop:approvals"}], checks["required_status_checks"])
        # The pack's approvals.py reads `ci: false` as no CI and then wants its local-ci record.
        self.assertEqual({"ci": False}, settings((project / "docs/agents/loop.md").read_text())["loop"])

        # The approvals workflow reruns on local-ci's record, a PR comment, instead of on CI's completion.
        text = (project / ".github/workflows/approvals.yml").read_text()
        approvals = yaml.safe_load(text)
        on = approvals[True]  # PyYAML reads `on` as True
        self.assertNotIn("workflow_run", on)
        self.assertEqual({"types": ["created"]}, on["issue_comment"])
        job = approvals["jobs"]["approvals"]
        # The job runs on a PR comment whose first line is local-ci's record, and on no other comment.
        for body, runs in [
            ("Local check passed\nHead: abc\nCommand: mise run check:all\n", True),
            ("Local check passed\r\nHead: abc", True),
            ("Local check passed", True),
            ("Local check passedXYZ\nHead: abc", False),
            ("Thanks, checking this now", False),
        ]:
            with self.subTest(body=body):
                comment = {"event_name": "issue_comment", "event": {"issue": {"number": 17, "pull_request": {"url": "x"}}, "comment": {"body": body}}}
                self.assertEqual(runs, bool(evaluate(job["if"], comment)))
        issue = {"event_name": "issue_comment", "event": {"issue": {"number": 17}, "comment": {"body": "Local check passed"}}}
        self.assertFalse(evaluate(job["if"], issue))
        self.assertEqual("${{ github.event.pull_request.number || github.event.issue.number }}", job["steps"][-1]["env"]["PR"])
        # A run the job skips never cancels one that posts the status: only runs that post share a PR's group.
        pr = {"number": 17, "draft": False}
        events = {
            "local-ci record": ({"event_name": "issue_comment", "event": {"issue": {"number": 17, "pull_request": {"url": "x"}}, "comment": {"body": "Local check passed\nHead: abc"}}}, True),
            "label": ({"event_name": "pull_request", "actor": "owner", "event": {"pull_request": pr}}, True),
            "review": ({"event_name": "pull_request_review", "actor": "verifier", "event": {"pull_request": pr}}, True),
            "other comment": ({"event_name": "issue_comment", "event": {"issue": {"number": 17, "pull_request": {"url": "x"}}, "comment": {"body": "Thanks, checking this now"}}}, False),
            "draft label": ({"event_name": "pull_request", "actor": "owner", "event": {"pull_request": {"number": 17, "draft": True}}}, False),
            "dependabot label": ({"event_name": "pull_request", "actor": "dependabot[bot]", "event": {"pull_request": pr}}, False),
        }
        for name, (github, runs) in events.items():
            with self.subTest(event=name):
                self.assertEqual(runs, bool(evaluate(job["if"], github)))
                group = evaluate(approvals["concurrency"]["group"], {**github, "run_id": name})
                self.assertEqual("approvals-17" if runs else f"approvals-skipped-{name}", group)
        self.assertNotIn("workflow_run", text)

        # The project's own workflow linters, at its pinned versions, pass the rendered workflow.
        tools = tomllib.loads((project / "mise.toml").read_text())["tools"]
        for linter in ("actionlint", "zizmor"):
            with self.subTest(linter=linter):
                result = subprocess.run(
                    [MISE, "exec", f"{linter}@{tools[linter]}", "--", linter, ".github/workflows/approvals.yml"],
                    cwd=project, capture_output=True, text=True,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_regeneration_keeps_filled_docs_agents_files(self) -> None:
        project = render()
        filled = "Tracker: GitHub\n\n## Components\n\n- `api`: the service.\n"
        for name in ("loop.md", "issue-tracker.md", "coding-standards.md"):
            (project / "docs/agents" / name).write_text(filled)

        subprocess.run(
            ["copier", "copy", "--trust", "--defaults", "--skip-tasks", "--overwrite",
             "--data", "project_name=agent-layer-test", "--data", "project_type=software/python",
             str(project.parent / "template"), str(project)],
            check=True, capture_output=True, text=True,
        )

        for name in ("loop.md", "issue-tracker.md", "coding-standards.md"):
            self.assertEqual(filled, (project / "docs/agents" / name).read_text())

    def test_content_leaf_gate_is_only_mise_run_check(self) -> None:
        project = render("authoring/content")

        mise = tomllib.loads((project / "mise.toml").read_text())
        self.assertIn("aqua:lycheeverse/lychee", mise["tools"])
        self.assertEqual("lychee --no-progress --extensions md .", mise["tasks"]["test:fast"]["run"])
        self.assertEqual(["test:unit"], mise["tasks"]["check:unit"]["depends"])
        self.assertNotIn("lychee", (project / ".github/workflows/ci.yml").read_text())

        off = render("authoring/content", include_mise=False)
        self.assertIn("lychee-action", (off / ".github/workflows/ci.yml").read_text())

    def test_ci_without_mise_keeps_the_per_step_gate(self) -> None:
        project = render(include_mise=False)
        workflow = (project / ".github/workflows/ci.yml").read_text()

        self.assertNotIn("mise run", workflow)
        self.assertFalse((project / "scripts/files-or-repo").exists())
        self.assertFalse((project / ".github/check-paths.yml").exists())
        self.assertIn("rev: v6.0.0", (project / ".pre-commit-config.yaml").read_text())
        self.assertIn("pipx run pre-commit run --all-files", workflow)
        self.assertIn("uv run pytest --cov", workflow)
        # a stale uv.lock fails CI rather than being rewritten (#31)
        for leaf in (project, render("data/dbt", include_mise=False)):
            steps = [step["run"] for job in yaml.safe_load((leaf / ".github/workflows/ci.yml").read_text())["jobs"].values()
                     for step in job["steps"] if step.get("run", "").startswith("uv sync")]
            self.assertEqual(["uv sync --locked"], steps, leaf)

    def test_post_gen_locks_a_uv_project_outside_the_python_leaves(self) -> None:
        # dbt resolves no language, so post-gen's uv sync skips it; CI's `uv sync --locked` needs the lock
        project = render("data/dbt", include_mise=False)
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["bash", str(ROOT / "_post_gen.sh"), "data/dbt", "python"], cwd=project, env=env, check=True, capture_output=True)
        self.assertTrue((project / "uv.lock").exists())

    def test_setup_dev_hooks_skip_a_worktree_without_the_config(self) -> None:
        # .git/hooks is shared by every worktree; a branch without .pre-commit-config.yaml must still commit (#14)
        project = render("authoring/content")
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        git = lambda *args, cwd=project: subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)
        git("init", "-q", "--template=", "-b", "main")
        git("commit", "-q", "--allow-empty", "-m", "root")
        other = project.parent / "other"
        git("worktree", "add", "-q", "-b", "bare-branch", str(other))
        git("add", "-A")
        git("commit", "-q", "--no-verify", "-m", "adopt")
        setup = tomllib.loads((project / "mise.toml").read_text())["tasks"]["setup:dev"]["run"]
        subprocess.run(["sh", "-c", setup], cwd=project, env=env, check=True, capture_output=True)
        (other / "note.txt").write_text("x\n")
        git("add", "note.txt", cwd=other)
        committed = subprocess.run(["git", "commit", "-q", "-m", "note"], cwd=other, env=env, capture_output=True, text=True)
        self.assertEqual(0, committed.returncode, committed.stdout + committed.stderr)
        for leaf in ("software/python", "software/node", "software/java", "data/dbt", "ai/skills", "infra/terraform", "apple/xcode"):
            run = tomllib.loads((render(leaf) / "mise.toml").read_text())["tasks"]["setup:dev"]["run"]
            self.assertIn("pre-commit install --allow-missing-config --install-hooks", run, leaf)
        self.assertEqual(2, (ROOT / "_post_gen.sh").read_text().count("--allow-missing-config --install-hooks"))

    def test_apm_version_has_one_template_source(self) -> None:
        partial = (ROOT / "templates/_base/_mise_agent_tasks.part").read_text()

        self.assertIn('{% set apm_version = "0.33.0" %}', partial)
        self.assertEqual(1, partial.count("0.33.0"))

    def test_with_ci_a_skipped_approvals_run_cancels_nothing(self) -> None:
        # With CI on, a run whose job skips (a draft, dependabot) gets its own group, as without CI (#45)
        approvals = yaml.safe_load((render() / ".github/workflows/approvals.yml").read_text())
        job = approvals["jobs"]["approvals"]
        pr = {"number": 17, "draft": False}
        events = {
            "label": ({"event_name": "pull_request", "actor": "owner", "event": {"pull_request": pr}}, True),
            "review": ({"event_name": "pull_request_review", "actor": "verifier", "event": {"pull_request": pr}}, True),
            "draft label": ({"event_name": "pull_request", "actor": "owner", "event": {"pull_request": {"number": 17, "draft": True}}}, False),
            "dependabot label": ({"event_name": "pull_request", "actor": "dependabot[bot]", "event": {"pull_request": pr}}, False),
            "push run": ({"event_name": "workflow_run", "event": {"pull_request": pr, "workflow_run": {"event": "push"}}}, False),
        }
        for name, (github, runs) in events.items():
            with self.subTest(event=name):
                self.assertEqual(runs, bool(evaluate(job["if"], github)))
                group = evaluate(approvals["concurrency"]["group"], {**github, "run_id": name})
                self.assertEqual("approvals-17" if runs else f"approvals-skipped-{name}", group)
        ci_completion = {"event_name": "workflow_run", "event": {"workflow_run": {"event": "pull_request"}}}
        self.assertTrue(evaluate(job["if"], ci_completion))
        self.assertIn("github.event.workflow_run.pull_requests[0].number", approvals["concurrency"]["group"])

    def test_disabled_layer_leaves_no_agent_framework(self) -> None:
        project = render(include_mise=True, include_agent_layer=False)

        self.assertFalse((project / "apm.yml").exists())
        self.assertFalse((project / "fnox.toml").exists())
        self.assertFalse((project / ".apm").exists())
        self.assertFalse((project / ".agents-toolkit").exists())
        self.assertNotIn("agent:sync", (project / "mise.toml").read_text())

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
            tasks["agent:sync"]["description"],
        )
        self.assertEqual("Launch Claude Code.", tasks["agent:claude"]["description"])
        self.assertEqual("Launch Codex.", tasks["agent:codex"]["description"])
        for task in ("agent:claude", "agent:codex"):
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
            ("apple/xcode", {}),
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
                self.assertNotIn("agent:sync", (project / "mise.toml").read_text())

    def run_check_unit(self, project: Path) -> subprocess.CompletedProcess[str]:
        scratch = Path(tempfile.mkdtemp(prefix="apple-gate-mise-"))
        atexit.register(shutil.rmtree, scratch, True)
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        env = {
            **os.environ,
            "MISE_CACHE_DIR": str(scratch / "cache"),
            "MISE_DATA_DIR": str(scratch / "data"),
            "MISE_STATE_DIR": str(scratch / "state"),
            "MISE_OFFLINE": "true",
            "MISE_TRUSTED_CONFIG_PATHS": str(project),
        }
        return subprocess.run([MISE, "run", "--skip-tools", "check:unit"], cwd=project, env=env,
                              capture_output=True, text=True)

    def test_apple_leaf_check_unit_runs_the_projects_gate_script(self) -> None:
        project = render("apple/xcode", include_example=False, gate_script="Scripts/gate.sh")
        self.assertEqual([], [name for name in ("Package.swift", "Sources", "Tests", "Scripts/gate.sh")
                              if (project / name).exists()])
        gate = project / "Scripts/gate.sh"
        for code in (0, 1):
            with self.subTest(gate_exit=code):
                marker = project / f"gate-ran-{code}"
                gate.write_text(f"#!/bin/sh\ntouch {marker.name}\nexit {code}\n")
                gate.chmod(0o755)

                result = self.run_check_unit(project)

                self.assertTrue(marker.exists(), result.stdout + result.stderr)
                self.assertEqual(code, result.returncode, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("xcrun"), "the starter's gate runs Xcode's swift test")
    def test_apple_starter_passes_its_own_gate(self) -> None:
        project = render("apple/xcode")
        self.assertTrue(os.access(project / "Scripts/gate.sh", os.X_OK))

        result = self.run_check_unit(project)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertRegex(result.stdout + result.stderr, r"Test run with 1 test .*passed")

    def test_gate_script_is_asked_only_for_the_apple_leaf(self) -> None:
        self.assertNotIn("gate_script", (render("software/python") / ".copier-answers.yml").read_text())
        project = render("apple/xcode", gate_script="tools/gate.sh")
        self.assertIn("gate_script: tools/gate.sh", (project / ".copier-answers.yml").read_text())
        self.assertEqual("./tools/gate.sh", tomllib.loads((project / "mise.toml").read_text())["tasks"]["test:fast"]["run"])
        self.assertTrue(os.access(project / "tools/gate.sh", os.X_OK))
        for unsafe in ("Scripts/merge gate.sh", "/abs/gate.sh", "Scripts/gate'.sh", "Scripts/gate.sh\n"):
            with self.subTest(gate_script=unsafe), self.assertRaises(subprocess.CalledProcessError):
                render("apple/xcode", gate_script=unsafe)
        ignored = (project / ".gitignore").read_text().splitlines()
        self.assertEqual([], [entry for entry in (".build/", "DerivedData/", "build/", "xcuserdata/", "*.xcuserstate")
                              if entry not in ignored])

    def test_every_leaf_renders_a_hook_config_that_passes_its_own_eof_lint(self) -> None:
        for project_type, answers in LEAVES:
            for include_mise in (True, False):
                with self.subTest(project_type=project_type, include_mise=include_mise, **answers):
                    text = (render(project_type, include_mise=include_mise, **answers) / ".pre-commit-config.yaml").read_text()
                    self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"), repr(text[-40:]))

    def test_swift_keeps_four_space_indentation_in_every_leaf(self) -> None:
        # Xcode honours .editorconfig, so a 2-space default would reflow every Swift edit.
        def indent_size(editorconfig: str, name: str) -> str:
            size = ""
            sections = re.split(r"^\[(.+)\]$", editorconfig, flags=re.M)
            for glob, body in zip(sections[1::2], sections[2::2]):
                pattern = re.escape(glob).replace(r"\*", "[^/]*").replace(r"\{", "(").replace(r"\}", ")").replace(",", "|")
                if re.fullmatch(pattern, name) and (match := re.search(r"^indent_size = (\S+)", body, re.M)):
                    size = match.group(1)
            return size

        for project_type, answers in LEAVES:
            with self.subTest(project_type=project_type, **answers):
                editorconfig = (render(project_type, **answers) / ".editorconfig").read_text()
                self.assertEqual("4", indent_size(editorconfig, "App.swift"))
                self.assertEqual("2", indent_size(editorconfig, "ci.yml"))

    def test_autofixing_hooks_skip_apm_managed_trees(self) -> None:
        # APM hash-tracks every file it deploys, so a hook that rewrites one
        # produces drift that only surfaces later as a --frozen failure.
        for project_type, fixers in (
            ("authoring/content", ("lint:eof", "lint:whitespace", "lint:markdownlint")),
            ("software/python", ("lint:eof", "lint:whitespace", "lint:ruff", "lint:ruff-format")),
            ("software/node", ("lint:eof", "lint:whitespace", "lint:biome")),
        ):
            with self.subTest(project_type=project_type):
                mise = tomllib.loads((render(project_type=project_type) / "mise.toml").read_text())
                managed = re.compile(mise["env"]["APM_MANAGED"])
                for task in fixers:
                    self.assertIn('--skip "${APM_MANAGED:-}"', mise["tasks"][task]["run"], task)
                self.assertNotIn("APM_MANAGED", mise["tasks"]["lint:gitleaks"]["run"])
                # The lockfile is generated hashes, so it cannot carry an inline
                # pragma; everything else — vendored skills included — is scanned.
                secrets = re.search(r'--skip "([^"]+)"', mise["tasks"]["lint:detect-secrets"]["run"])
                self.assertRegex("apm.lock.yaml", secrets.group(1))
                self.assertNotRegex(".agents/skills/wayfinder/SKILL.md", secrets.group(1))

        for path in (
            ".agents/skills/wayfinder/SKILL.md",
            ".claude/skills/wayfinder/SKILL.md",
            ".claude/rules/project.md",
            ".agents/skills/audit-third-party-software/scripts/extract_strings_urls.py",
            ".codex/config.toml",
            ".github/instructions/project.instructions.md",
            "AGENTS.md",
            "src/AGENTS.md",
            "src/CLAUDE.md",
        ):
            self.assertRegex(path, managed, f"{path} must be left to APM")

        # Project-owned files stay linted — including the root CLAUDE.md, which
        # the template authors rather than APM compiling it.
        for path in (
            "CLAUDE.md",
            "README.md",
            "docs/index.md",
            "src/lego_sorter/__init__.py",
            "apm.yml",
        ):
            self.assertNotRegex(path, managed, f"{path} must stay linted")


class RenovateGenerationTest(unittest.TestCase):
    def test_mise_projects_get_renovate_and_no_dependabot(self) -> None:
        project = render(include_mise=True, include_agent_layer=True)
        config = json.loads((project / "renovate.json").read_text())
        self.assertFalse((project / ".github/dependabot.yml").exists())
        self.assertEqual(["github-tags"], [m["datasourceTemplate"] for m in config["customManagers"]])
        rules = {rule.get("groupName"): rule for rule in config["packageRules"]}
        agent = rules["template and agent packages"]
        self.assertEqual((["verify"], True, False), (agent["addLabels"], agent["draftPR"], agent["automerge"]))
        self.assertEqual(["mise run agent:sync -- --refresh"], agent["postUpgradeTasks"]["commands"])
        self.assertTrue(rules["tools and libraries"]["automerge"])
        maintenance = config["lockFileMaintenance"]
        self.assertEqual((True, rules["tools and libraries"]["schedule"], True),
                         (maintenance["enabled"], maintenance["schedule"], maintenance["automerge"]))
        tasks = tomllib.loads((project / "mise.toml").read_text())["tasks"]
        self.assertIn("deps:renovate", tasks)
        self.assertIn("^mise run agent:sync -- --refresh$", tasks["deps:renovate"]["run"])

    def test_the_apm_manager_reads_the_rendered_pin(self) -> None:
        project = render(include_mise=True, include_agent_layer=True)
        manager = json.loads((project / "renovate.json").read_text())["customManagers"][0]
        # Renovate's matchStrings are ECMAScript; this one uses nothing Python's re reads differently.
        found = re.search(manager["matchStrings"][0].replace("(?<", "(?P<"), (project / "apm.yml").read_text())
        self.assertEqual(("kzarzycki/agent-skills", "engineering", "0.24.1"),
                         (found["packageName"], found["package"], found["currentValue"]))

    def test_without_the_agent_layer_renovate_has_no_apm_manager_or_task(self) -> None:
        config = json.loads((render(include_mise=True, include_agent_layer=False) / "renovate.json").read_text())
        self.assertNotIn("customManagers", config)
        self.assertNotIn("postUpgradeTasks", json.dumps(config))

    def test_without_mise_dependabot_stays(self) -> None:
        project = render(include_mise=False)
        self.assertTrue((project / ".github/dependabot.yml").exists())
        self.assertFalse((project / "renovate.json").exists())


if __name__ == "__main__":
    unittest.main()
