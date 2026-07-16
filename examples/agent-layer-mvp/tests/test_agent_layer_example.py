from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AgentLayerExampleTest(unittest.TestCase):
    def test_mcp_client_calls_fnox_wrapped_canary(self) -> None:
        fnox = shutil.which("fnox")
        if fnox is None:
            self.skipTest("fnox is not installed")

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def call_canary() -> tuple[list[str], str]:
            parameters = StdioServerParameters(
                command=fnox,
                args=[
                    "exec",
                    "--profile",
                    "local",
                    "--no-defaults",
                    "--non-interactive",
                    "--if-missing",
                    "error",
                    "--",
                    "uv",
                    "run",
                    "python",
                    "scripts/mcp_canary.py",
                ],
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

        tools, result = asyncio.run(call_canary())
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

    def test_native_auth_rejects_environment_token(self) -> None:
        result = subprocess.run(
            ["scripts/check_native_auth.sh"],
            cwd=ROOT,
            env={**os.environ, "GITHUB_TOKEN": "synthetic-not-a-token"},
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("GITHUB_TOKEN must be unset", result.stderr)

    def test_apm_mcp_runs_canary_through_local_fnox_profile(self) -> None:
        manifest = (ROOT / "apm.yml").read_text()

        for expected in (
            "agent-layer-canary",
            "fnox",
            "--profile",
            "local",
            "scripts/mcp_canary.py",
        ):
            self.assertIn(expected, manifest)

    def test_project_check_selects_its_local_fnox_profile(self) -> None:
        mise = (ROOT / "mise.toml").read_text()

        self.assertIn(
            "fnox check --profile local --no-defaults --all --non-interactive",
            mise,
        )


if __name__ == "__main__":
    unittest.main()
