"""scripts/gate-slot: one host gate slot at a time, freed by any exit, and GATE_JOBS within the host's cores."""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_agent_layer_generation import LEAVES, render

ROOT = Path(__file__).resolve().parents[1]
GATE_SLOT = ROOT / "templates/_base/_gate_slot.sh"


class GateSlotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = tempfile.mkdtemp(prefix="gate-slot-test-")
        self.env = {**os.environ, "XDG_CACHE_HOME": self.cache}
        self.env.pop("GATE_SLOTS", None)
        self.env.pop("LC_ALL", None)  # the fake uptime keys on it: a runner's own LC_ALL=C would hide the override

    def start(self, *command: str) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [str(GATE_SLOT), *command],
            env=self.env,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

    def held(self) -> None:
        """Wait until the first run took slot 1."""
        lock = Path(self.cache, "engineering-loop", "gate.1.lock")
        deadline = time.monotonic() + 10
        while not (lock.exists() and lock.read_text().strip()):
            self.assertLess(time.monotonic(), deadline, "the first run never took the slot")
            time.sleep(0.05)

    def test_two_gates_run_one_after_the_other_and_the_second_says_it_waits(self) -> None:
        marks = Path(self.cache, "marks")
        step = f"echo start >> {marks}; sleep 1; echo end >> {marks}"
        first = self.start("sh", "-c", step)
        self.held()
        second = self.start("sh", "-c", step)
        _, first_err = first.communicate(timeout=30)
        _, second_err = second.communicate(timeout=30)
        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertEqual(marks.read_text().split(), ["start", "end", "start", "end"])
        self.assertIn(f"gate-slot: waiting for a host gate slot (held by pid {first.pid})", second_err)
        self.assertNotIn("waiting", first_err)

    def test_a_killed_holder_frees_its_slot(self) -> None:
        holder = self.start("sleep", "60")
        self.held()
        os.killpg(holder.pid, signal.SIGKILL)
        holder.communicate(timeout=10)
        after = subprocess.run([str(GATE_SLOT), "true"], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertNotIn("waiting", after.stderr)

    def test_more_slots_run_gates_side_by_side(self) -> None:
        self.env["GATE_SLOTS"] = "2"
        first = self.start("sleep", "3")
        self.held()
        second = subprocess.run([str(GATE_SLOT), "true"], env=self.env, capture_output=True, text=True, timeout=10)
        first.kill()
        first.communicate()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("waiting", second.stderr)

    def host(self, cores: str, uptime: str) -> Path:
        """Put a fake getconf and uptime first on PATH; uptime prints the file it returns, so a test can change it.
        Outside LC_ALL=C the fake prints decimal commas, as procps does under a locale such as de_DE."""
        bin_dir = Path(self.cache, "bin")
        bin_dir.mkdir(exist_ok=True)
        reading = Path(self.cache, "uptime.txt")
        reading.write_text(uptime + "\n")
        comma = f'sed "s/\\([0-9]\\)\\.\\([0-9]\\)/\\1,\\2/g" {reading}'
        for name, body in (("getconf", f"echo {cores}"), ("uptime", f'[ "$LC_ALL" = C ] && cat {reading} || {comma}')):
            fake = bin_dir / name
            fake.write_text(f"#!/bin/sh\n{body}\n")
            fake.chmod(0o755)
        self.env["PATH"] = f"{bin_dir}:{self.env['PATH']}"
        return reading

    def jobs(self) -> str:
        out = subprocess.run(
            [str(GATE_SLOT), "sh", "-c", 'echo "$GATE_JOBS"'], env=self.env, capture_output=True, text=True, timeout=10
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def test_gate_jobs_is_the_free_cores_within_one_and_all_of_them(self) -> None:
        mac = "10:00  up 3 days, 2 users, load averages: {} 1.00 0.50"
        linux = " 10:00:00 up 3 days,  2 users,  load average: {}, 1.00, 0.50"
        for form in (mac, linux):
            for load, jobs in (("0.00", "10"), ("2.50", "7"), ("9.99", "1"), ("160.00", "1")):
                with self.subTest(form=form, load=load):
                    self.host("10", form.format(load))
                    self.assertEqual(self.jobs(), jobs)

    def test_unreadable_cores_or_load_fall_back_to_one_core_and_no_load(self) -> None:
        self.host("", "no load here")
        self.assertEqual(self.jobs(), "1")
        self.host("8", "no load here")
        self.assertEqual(self.jobs(), "8")

    def test_a_gate_that_waited_sizes_itself_to_the_load_when_it_starts(self) -> None:
        reading = self.host("10", "load averages: 9.00 1.00 0.50")
        holder = self.start("sleep", "2")
        self.held()
        waiter = self.start("sh", "-c", 'echo "$GATE_JOBS"')
        time.sleep(0.5)
        reading.write_text("load averages: 1.00 1.00 0.50\n")
        out, err = waiter.communicate(timeout=30)
        holder.communicate(timeout=30)
        self.assertIn("waiting", err)
        self.assertEqual(out.strip(), "9")

    def test_a_bad_slot_count_is_refused(self) -> None:
        self.env["GATE_SLOTS"] = "0"
        out = subprocess.run([str(GATE_SLOT), "true"], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 2)

    def test_a_failing_command_keeps_its_exit_code(self) -> None:
        out = subprocess.run([str(GATE_SLOT), "sh", "-c", "exit 7"], env=self.env, capture_output=True, timeout=10)
        self.assertEqual(out.returncode, 7)


class GateSlotGenerationTest(unittest.TestCase):
    def test_every_template_runs_check_unit_through_an_executable_gate_slot(self) -> None:
        for project_type, answers in LEAVES:
            if project_type == "authoring/content":
                continue  # its check:unit is a network-bound link check, not a test suite: no gate slot
            with self.subTest(project_type=project_type, **answers):
                project = render(project_type, **answers)
                folder = "Scripts" if project_type == "apple/xcode" else "scripts"
                script = project / folder / "gate-slot"
                self.assertTrue(os.access(script, os.X_OK), script)
                self.assertEqual(script.read_text(), GATE_SLOT.read_text())
                mise = (project / "mise.toml").read_text()
                unit = mise.split('[tasks."check:unit"]', 1)[1].split("\n[tasks", 1)[0]
                self.assertIn(f"{folder}/gate-slot mise run --skip-tools test:unit", unit)


if __name__ == "__main__":
    unittest.main()
