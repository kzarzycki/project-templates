from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AgentLayerExampleTest(unittest.TestCase):
    def test_mcp_client_calls_fnox_wrapped_canary(self) -> None:
        fnox = shutil.which("fnox")
        if fnox is None:
            self.fail("fnox is required; run 'mise install'")

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        claude = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]["agent-layer-canary"]
        codex = tomllib.loads((ROOT / ".codex/config.toml").read_text())["mcp_servers"][
            "agent-layer-canary"
        ]

        async def call_canary(command: str, arguments: list[str]) -> tuple[list[str], str]:
            parameters = StdioServerParameters(
                command=fnox if command == "fnox" else command,
                args=arguments,
                cwd=ROOT,
            )
            async with (
                stdio_client(parameters) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()
                tools = await session.list_tools()
                result = await session.call_tool("probe")
                text = result.content[0].text
                return [tool.name for tool in tools.tools], text

        for target, config in (("claude", claude), ("codex", codex)):
            with self.subTest(target=target):
                tools, result = asyncio.run(call_canary(config["command"], config["args"]))
                self.assertIn("probe", tools)
                self.assertEqual("canary-ok", result)

    def test_canary_requires_fnox_binding(self) -> None:
        env = os.environ.copy()
        env.pop("AGENT_LAYER_CANARY", None)

        result = subprocess.run(
            ["python3", "scripts/mcp_canary.py", "--probe"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("canary-ok", result.stdout)

    def test_canary_reports_fixed_marker_without_value(self) -> None:
        value = "local-profile-canary"

        result = subprocess.run(
            ["python3", "scripts/mcp_canary.py", "--probe"],
            cwd=ROOT,
            env={**os.environ, "AGENT_LAYER_CANARY": value},
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("canary-ok\n", result.stdout)
        self.assertNotIn(value, result.stdout + result.stderr)

    def test_native_auth_uses_only_gh_auth_status(self) -> None:
        scratch = Path(tempfile.mkdtemp(prefix="native-auth-test-"))
        log = scratch / "gh.log"
        gh = scratch / "gh"
        gh.write_text(
            "#!/bin/sh\n"
            'printf "%s\\n" "$*" >> "$GH_COMMAND_LOG"\n'
            'echo "simulated gh status"\n'
            'echo "simulated gh diagnostic" >&2\n'
        )
        gh.chmod(0o755)
        env = os.environ.copy()
        env.pop("GITHUB_TOKEN", None)
        env.pop("GH_TOKEN", None)
        env.update(
            {
                "GH_COMMAND_LOG": str(log),
                "PATH": f"{scratch}:/usr/bin:/bin",
            }
        )

        result = subprocess.run(
            ["scripts/check_native_auth.sh"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["auth status"], log.read_text().splitlines())
        self.assertEqual("", result.stdout)
        self.assertEqual("", result.stderr)
        self.assertIn(
            "env -u GITHUB_TOKEN -u GH_TOKEN scripts/check_native_auth.sh",
            (ROOT / "README.md").read_text(),
        )

    def test_native_auth_rejects_environment_tokens(self) -> None:
        for variable in ("GITHUB_TOKEN", "GH_TOKEN"):
            with self.subTest(variable=variable):
                env = os.environ.copy()
                env.pop("GITHUB_TOKEN", None)
                env.pop("GH_TOKEN", None)
                env[variable] = "synthetic-not-a-token"
                result = subprocess.run(
                    ["scripts/check_native_auth.sh"],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn("environment GitHub tokens must be unset", result.stderr)

    def test_apm_mcp_runs_canary_through_mcp_local_fnox_profile(self) -> None:
        manifest = (ROOT / "apm.yml").read_text()

        for expected in (
            "agent-layer-canary",
            "fnox",
            "--profile",
            "mcp-local",
            "scripts/mcp_canary.py",
        ):
            self.assertIn(expected, manifest)

    def test_project_check_selects_both_fnox_profiles(self) -> None:
        mise = (ROOT / "mise.toml").read_text()

        self.assertIn(
            "fnox check --profile local --no-defaults --all --non-interactive",
            mise,
        )
        self.assertIn(
            "fnox check --profile mcp-local --no-defaults --all --non-interactive",
            mise,
        )

    def test_project_launches_select_the_local_fnox_profile(self) -> None:
        mise = (ROOT / "mise.toml").read_text()

        self.assertEqual(2, mise.count("fnox exec --profile local --no-defaults"))

    def test_agent_profile_does_not_receive_mcp_canary(self) -> None:
        fnox = shutil.which("fnox")
        if fnox is None:
            self.fail("fnox is required; run 'mise install'")

        env = os.environ.copy()
        env.pop("AGENT_LAYER_CANARY", None)
        result = subprocess.run(
            [
                fnox,
                "exec",
                "--profile",
                "local",
                "--no-defaults",
                "--non-interactive",
                "--if-missing",
                "error",
                "--",
                "python3",
                "-c",
                "import os; raise SystemExit('AGENT_LAYER_CANARY' in os.environ)",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_ci_installs_mise_tools_before_protocol_test(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()

        self.assertIn("jdx/mise-action", workflow)
        self.assertIn("mise run agent-check", workflow)
        self.assertIn("mise exec -- uv run pytest", workflow)

    def test_readme_explains_codex_project_trust(self) -> None:
        readme = (ROOT / "README.md").read_text().lower()

        self.assertIn(".codex/config.toml", readme)
        self.assertIn("trusted", readme)

    def test_example_records_qualified_tool_versions(self) -> None:
        mise = tomllib.loads((ROOT / "mise.toml").read_text())
        instructions = (ROOT / "AGENTS.md").read_text()
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        hooks = (ROOT / ".pre-commit-config.yaml").read_text()

        self.assertEqual(
            {
                "python": "3.14",
                "uv": "0.11.29",
                "pre-commit": "4.6.0",
                "github:microsoft/apm": "0.25.0",
                "fnox": "1.30.0",
            },
            mise["tools"],
        )
        self.assertIn("<!-- APM Version: 0.25.0 -->", instructions)
        self.assertIn(
            "jdx/mise-action@dad1bfd3df957f44999b559dd69dc1671cb4e9ea",
            workflow,
        )
        for revision in ("v6.0.0", "v8.30.1", "v4.4.0", "v1.27.0", "v0.15.22"):
            self.assertIn(f"rev: {revision}", hooks)

    def test_demonstration_fixtures_state_their_scope(self) -> None:
        readme = (ROOT / "README.md").read_text()
        native_auth = (ROOT / "scripts/check_native_auth.sh").read_text()
        fnox = (ROOT / "fnox.toml").read_text()
        canary = (ROOT / "scripts/mcp_canary.py").read_text()
        manifest = (ROOT / "apm.yml").read_text()
        instruction = (ROOT / ".apm/instructions/project.instructions.md").read_text()
        mise = (ROOT / "mise.toml").read_text()
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        gitignore = (ROOT / ".gitignore").read_text()
        pyproject = (ROOT / "pyproject.toml").read_text()
        readme_flat = " ".join(readme.split())

        self.assertIn("## Demonstration fixtures", readme)
        self.assertIn("not a reusable authentication policy", readme_flat)
        self.assertIn("Demonstration-only", native_auth)
        self.assertIn("Synthetic demonstration values", fnox)
        self.assertIn("Demonstration-only MCP server", canary)
        self.assertIn("Demonstration-only MCP acceptance fixture", manifest)
        self.assertIn("Demonstration-only instruction", instruction)
        self.assertIn("Example-owned profile selection", mise)
        self.assertIn("Example-specific coding-agent acceptance commands", workflow)
        self.assertIn("# Coding-agent generated/cache state", gitignore)
        self.assertNotIn("# Agent layer generated/cache state", gitignore)
        self.assertIn("Demonstration MCP dependency", pyproject)


if __name__ == "__main__":
    unittest.main()
