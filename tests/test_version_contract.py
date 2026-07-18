from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VersionContractTest(unittest.TestCase):
    def text(self, path: str) -> str:
        return (ROOT / path).read_text()

    def test_default_runtimes_use_current_stable_or_lts_lines(self) -> None:
        copier = self.text("copier.yml")

        for name, version in (
            ("python_version", "3.14"),
            ("node_version", "24"),
            ("java_version", "25"),
            ("terraform_version", "1.15.8"),
        ):
            block = re.search(rf"^{name}:\n(?:(?:  ).*\n)+", copier, re.MULTILINE)
            self.assertIsNotNone(block)
            self.assertIn(f'default: "{version}"', block.group(0))

    def test_mise_tools_are_qualified_and_do_not_float(self) -> None:
        mise_sources = list((ROOT / "templates").rglob("mise.toml.jinja"))
        combined = "\n".join(path.read_text() for path in mise_sources)

        self.assertNotIn('= "latest"', combined)
        self.assertIn('uv = "0.11.29"', combined)
        self.assertIn('pre-commit = "4.6.0"', combined)
        self.assertIn('tflint = "0.63.1"', combined)
        self.assertIn(
            'gradle = "9.6.1"', self.text("templates/_lang/java/_mise_tools.part")
        )

    def test_generated_workflows_pin_current_actions(self) -> None:
        expected = {
            "actions/checkout": "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",  # pragma: allowlist secret
            "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",  # pragma: allowlist secret
            "actions/setup-node": "820762786026740c76f36085b0efc47a31fe5020",  # pragma: allowlist secret
            "actions/setup-java": "03ad4de0992f5dab5e18fcb136590ce7c4a0ac95",  # pragma: allowlist secret
            "astral-sh/setup-uv": "11f9893b081a58869d3b5fccaea48c9e9e46f990",  # pragma: allowlist secret
            "jdx/mise-action": "dad1bfd3df957f44999b559dd69dc1671cb4e9ea",  # pragma: allowlist secret
            "lycheeverse/lychee-action": "e7477775783ea5526144ba13e8db5eec57747ce8",  # pragma: allowlist secret
            "hashicorp/setup-terraform": "dfe3c3f87815947d99a8997f908cb6525fc44e9e",  # pragma: allowlist secret
            "terraform-linters/setup-tflint": "6e1e0642c0289bd619021bf6b34e3c08ed1e005a",  # pragma: allowlist secret
        }
        workflow_sources = [ROOT / ".github/workflows/ci.yml"]
        workflow_sources.extend((ROOT / "templates").rglob("*.yml.jinja"))
        workflow_sources.extend((ROOT / "examples").rglob("*.yml"))
        uses = re.findall(
            r"uses:\s*([^@\s]+)@([^\s#]+)",
            "\n".join(path.read_text() for path in workflow_sources),
        )

        for action, ref in uses:
            if action in expected:
                self.assertEqual(expected[action], ref, action)
        for action in expected:
            self.assertIn(action, {name for name, _ in uses})

    def test_root_ci_pins_its_toolchain(self) -> None:
        workflow = self.text(".github/workflows/ci.yml")

        self.assertIn("permissions:\n  contents: read", workflow)
        checkout = re.search(
            r"actions/checkout@[^\n]+\n(?:(?:        ).*\n)+", workflow
        )
        self.assertIsNotNone(checkout)
        self.assertIn("persist-credentials: false", checkout.group(0))
        for expected in (
            'version: "0.11.29"',
            "uv tool install copier==9.17.0",
            "uv tool install pre-commit==4.6.0",
            "mise exec terraform@1.15.8 tflint@0.63.1 --",
            'java-version: "25"',
        ):
            self.assertIn(expected, workflow)

    def test_pre_commit_hooks_use_current_releases(self) -> None:
        base = self.text("templates/_base/_precommit.yml.jinja")
        python = self.text("templates/_lang/python/_precommit.yml.jinja")
        authoring = self.text(
            "templates/authoring/content/.pre-commit-config.yaml.jinja"
        )

        for revision in (
            "v6.0.0",
            "v1.5.0",
            "v8.30.1",
            "v4.4.0",
            "v1.7.12",
            "v1.27.0",
        ):
            self.assertIn(f"rev: {revision}", base)
        self.assertIn("rev: v0.15.22", python)
        self.assertIn("rev: v0.49.1", authoring)

    def test_java_build_uses_current_qualified_releases(self) -> None:
        build = self.text("templates/_lang/java/_build.gradle.kts.jinja")
        wrapper = self.text(
            "templates/software/java/gradle/wrapper/gradle-wrapper.properties"
        )

        self.assertIn('version "8.8.0"', build)
        self.assertIn("junit-bom:6.1.2", build)
        self.assertIn('googleJavaFormat("1.35.0")', build)
        self.assertIn("gradle-9.6.1-bin.zip", wrapper)

    def test_node_dependencies_start_at_current_qualified_releases(self) -> None:
        for path in (
            "templates/_lang/node/_package.json.jinja",
            "templates/ai/mcp/{% if language == 'node' %}package.json{% endif %}.jinja",
        ):
            package = self.text(path)
            for dependency in (
                '"@biomejs/biome": "^2.5.4"',
                '"@types/node": "^24.13.3"',
                '"@vitest/coverage-v8": "^4.1.10"',
                '"typescript": "^7.0.2"',
                '"vitest": "^4.1.10"',
            ):
                self.assertIn(dependency, package)

        mcp = self.text(
            "templates/ai/mcp/{% if language == 'node' %}package.json{% endif %}.jinja"
        )
        self.assertIn('"@modelcontextprotocol/sdk": "^1.29.0"', mcp)

        tsconfig = self.text("templates/_lang/node/_tsconfig.json")
        self.assertIn('"allowImportingTsExtensions": true', tsconfig)

        biome = self.text("templates/_lang/node/_biome.json")
        self.assertIn("https://biomejs.dev/schemas/2.5.4/schema.json", biome)
        self.assertIn('"rules": { "preset": "recommended" }', biome)
        self.assertNotIn('"recommended": true', biome)

    def test_python_mcp_sdk_uses_current_qualified_minor(self) -> None:
        template = self.text(
            "templates/ai/mcp/{% if language == 'python' %}pyproject.toml{% endif %}.jinja"
        )
        example = self.text("examples/agent-layer-mvp/pyproject.toml")

        self.assertIn('"mcp>=1.28,<2"', template)
        self.assertIn('"mcp>=1.28,<2"', example)

    def test_python_dependency_floors_match_qualified_releases(self) -> None:
        python = self.text("templates/_lang/python/_pyproject.toml.jinja")
        mcp = self.text(
            "templates/ai/mcp/{% if language == 'python' %}pyproject.toml{% endif %}.jinja"
        )
        example = self.text("examples/agent-layer-mvp/pyproject.toml")
        dbt = self.text("templates/data/dbt/pyproject.toml.jinja")

        for project in (python, mcp, example):
            for requirement in (
                "setuptools>=83",
                "pytest>=9.1",
                "pytest-cov>=7.1",
                "diff-cover>=10.3",
                "ruff>=0.15.22",
            ):
                self.assertIn(requirement, project)
        for requirement in (
            "dbt-core>=1.12,<2",
            "dbt-snowflake>=1.12,<2",
            "sqlfluff>=4.2,<5",
            "sqlfluff-templater-dbt>=4.2,<5",
        ):
            self.assertIn(requirement, dbt)


if __name__ == "__main__":
    unittest.main()
