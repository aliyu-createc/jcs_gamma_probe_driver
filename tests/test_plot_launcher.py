import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "plot.sh"


class TestPlotLauncher(unittest.TestCase):
    def run_launcher(self, docker_result=0, never_ready=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = {
                "sudo": 'echo "start:$*" >> "$CALL_LOG"\nexit "$DOCKER_RESULT"\n',
                "docker": "exit 0\n",
                "curl": (
                    'echo poll >> "$CALL_LOG"\n'
                    'if [ "$NEVER_READY" = 1 ]; then exit 1; fi\n'
                    'if [ -f "$READY_FLAG" ]; then exit 0; fi\n'
                    'touch "$READY_FLAG"\nexit 1\n'
                ),
                "sleep": "exit 0\n",
                "xdg-open": 'echo "open:$*" >> "$CALL_LOG"\n',
            }
            for name, body in commands.items():
                executable = root / name
                executable.write_text("#!/bin/sh\n" + body)
                executable.chmod(0o755)
            environment = dict(
                os.environ,
                PATH=directory + os.pathsep + os.defpath,
                CALL_LOG=str(root / "calls"),
                READY_FLAG=str(root / "ready"),
                DOCKER_RESULT=str(docker_result),
                NEVER_READY="1" if never_ready else "0",
            )
            result = subprocess.run(
                ["bash", str(SCRIPT)], env=environment,
                capture_output=True, text=True, timeout=5,
            )
            calls = (root / "calls").read_text().splitlines()
        return result, calls

    def test_starts_saved_viewer_and_waits_before_opening_browser(self):
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [
            "start:docker start gamma_probe_plot",
            "poll", "poll",
            "open:http://127.0.0.1:8080",
        ])

    def test_docker_failure_does_not_open_browser(self):
        result, calls = self.run_launcher(docker_result=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, ["start:docker start gamma_probe_plot"])

    def test_unavailable_viewer_reports_error_without_opening_browser(self):
        result, calls = self.run_launcher(never_ready=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Plot did not become ready", result.stderr)
        self.assertFalse(any(call.startswith("open:") for call in calls))


if __name__ == "__main__":
    unittest.main()
