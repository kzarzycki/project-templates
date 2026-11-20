from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import affected_tests as at  # noqa: E402

ALL = at.all_modules()


class SelectTests(unittest.TestCase):
    def test_docs_only_runs_the_version_contract(self):
        self.assertEqual(at.select(["README.md", "docs/knowledge/gotchas.md"]), ["tests.test_version_contract"])

    def test_one_test_file_runs_itself(self):
        self.assertEqual(at.select(["tests/test_gate_slot.py"]), ["tests.test_gate_slot"])

    def test_shared_or_wide_paths_run_everything(self):
        for path in ("templates/_base/_gate_slot.sh", ".github/workflows/ci.yml", "tests/conftest.py",
                     "tests/test_agent_layer_generation.py", "scripts/affected_tests.py", "copier.yml",
                     "something/unknown.txt"):
            self.assertEqual(at.select(["README.md", path]), ALL, path)

    def test_a_deleted_test_file_falls_back_to_the_version_contract(self):
        self.assertEqual(at.select(["tests/test_gone.py"]), ["tests.test_version_contract"])


class CliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> list[str]:
        out = subprocess.run([sys.executable, str(at.ROOT / "scripts/affected_tests.py"), *args],
                             capture_output=True, text=True, check=True)
        return out.stdout.split()

    def test_no_base_or_a_bad_base_selects_everything(self):
        self.assertEqual(self.run_cli(), ALL)
        self.assertEqual(self.run_cli("0" * 40), ALL)
        self.assertEqual(self.run_cli("deadbeef" * 5), ALL)

    def test_a_real_diff_in_a_fresh_clone(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone = Path(tmp) / "c"
            git = lambda *a: subprocess.run(["git", "-C", str(clone), *a], check=True, capture_output=True, text=True)  # noqa: E731
            subprocess.run(["git", "clone", "-q", str(at.ROOT), str(clone)], check=True)
            (clone / "scripts").mkdir(exist_ok=True)
            (clone / "scripts/affected_tests.py").write_text((at.ROOT / "scripts/affected_tests.py").read_text())
            commit = lambda m: (git("add", "-A"), git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", m))  # noqa: E731
            commit("script")
            base = git("rev-parse", "HEAD").stdout.strip()
            (clone / "README.md").write_text("x\n")
            commit("docs")
            out = subprocess.run([sys.executable, str(clone / "scripts/affected_tests.py"), base],
                                 capture_output=True, text=True, check=True).stdout.split()
            self.assertEqual(out, ["tests.test_version_contract"])


if __name__ == "__main__":
    unittest.main()
