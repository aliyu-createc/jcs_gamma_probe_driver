import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "probe.sh"


class TestProbeLauncher(unittest.TestCase):
    def run_launcher(self, *args, containers="gamma_probe_plot\ngamma_probe_ads",
                     fail_command=""):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sudo = root / "sudo"
            sudo.write_text('#!/bin/sh\nexec "$@"\n')
            sudo.chmod(0o755)
            docker = root / "docker"
            docker.write_text(
                "#!%s\n" % sys.executable
                + "import json, os, sys\n"
                + "args = sys.argv[1:]\n"
                + "with open(os.environ['CALL_LOG'], 'a') as log:\n"
                + "    log.write(json.dumps(args) + '\\n')\n"
                + "if ' '.join(args).startswith(os.environ['FAIL_COMMAND'] or 'NEVER_FAIL'):\n"
                + "    sys.exit(17)\n"
                + "if args[:2] == ['container', 'ls']:\n"
                + "    print(os.environ['CONTAINERS'])\n"
            )
            docker.chmod(0o755)
            environment = dict(
                os.environ, PATH=directory + os.pathsep + os.defpath,
                CALL_LOG=str(root / "calls"), CONTAINERS=containers,
                FAIL_COMMAND=fail_command,
            )
            result = subprocess.run(
                ["bash", str(SCRIPT), *args], cwd=directory, env=environment,
                capture_output=True, text=True, timeout=5,
            )
            log = root / "calls"
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    def test_rebuild_uses_repository_paths_and_replaces_only_the_driver(self):
        result, calls = self.run_launcher("rebuild")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [
            ["build", "-t", "jcs_gamma_probe", str(ROOT)],
            ["container", "ls", "--all", "--format", "{{.Names}}"],
            ["stop", "gamma_probe_plot"],
            ["stop", "gamma_probe_ads"],
            ["rm", "gamma_probe_ads"],
            ["create", "-it", "--network", "host", "--name", "gamma_probe_ads",
             "--mount", "type=bind,source=%s/config,target=/gamma-config,readonly" % ROOT,
             "jcs_gamma_probe", "roslaunch", "jcs_gamma_probe", "gamma_probes_shared_ads.launch",
             "probe_config:=/gamma-config/probes.yaml"],
            ["start", "-ai", "gamma_probe_ads"],
        ])

    def test_daily_start_does_not_build_stop_or_recreate_containers(self):
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [
            ["container", "ls", "--all", "--format", "{{.Names}}"],
            ["start", "-ai", "gamma_probe_ads"],
        ])

    def test_rebuild_handles_missing_containers_and_start_explains_first_use(self):
        result, calls = self.run_launcher("rebuild", containers="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call[0] in ("stop", "rm") for call in calls))
        self.assertEqual(calls[-1], ["start", "-ai", "gamma_probe_ads"])
        result, calls = self.run_launcher(containers="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Driver container not found", result.stderr)
        self.assertIn("rebuild", result.stderr)
        self.assertFalse(any(call[0] == "start" for call in calls))

    def test_docker_failures_abort_without_running_later_steps(self):
        for failure in ("build", "container ls", "stop", "rm", "create", "start"):
            with self.subTest(failure=failure):
                result, calls = self.run_launcher("rebuild", fail_command=failure)
                self.assertEqual(result.returncode, 17)
                self.assertTrue(" ".join(calls[-1]).startswith(failure))

    def test_bad_arguments_do_not_touch_docker(self):
        for args in (("delete",), ("start", "extra")):
            with self.subTest(args=args):
                result, calls = self.run_launcher(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Usage:", result.stderr)
                self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
