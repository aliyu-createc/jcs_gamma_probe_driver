import importlib.util
import json
from pathlib import Path
import threading
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import urlopen

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dose_web", ROOT / "nodes" / "dose_web.py")
dose_web = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dose_web)


class TestDoseHistory(unittest.TestCase):
    def diagnostics(self, level=0, flags=None):
        if flags is None:
            flags = {name: "OK" for name in dose_web.HEALTH_FLAGS}
        return SimpleNamespace(
            level=level, message="Probe status", hardware_id="0157",
            values=[SimpleNamespace(key=key, value=value) for key, value in flags.items()],
        )

    def test_separate_probes_zero_readings_and_stale_age(self):
        with patch.object(dose_web.time, "monotonic", return_value=100) as clock:
            history = dose_web.DoseHistory(["/probe_1/dose", "/probe_2/dose"], 5)
            self.assertIsNone(history.snapshot()["series"][0]["age_seconds"])
            clock.return_value = 101
            history.record("/probe_1/dose", 0.0)
            clock.return_value = 107
            result = history.snapshot()
        self.assertEqual(result["series"][0]["samples"], [(1, 0.0)])
        self.assertEqual(result["series"][0]["age_seconds"], 6)
        self.assertEqual(result["series"][1]["samples"], [])
        self.assertIsNone(result["series"][1]["age_seconds"])

    def test_history_is_bounded_and_rejects_nonfinite_values(self):
        history = dose_web.DoseHistory(["/dose"], 5)
        for value in range(305):
            history.record("/dose", value)
            history.record_average("/dose", value / 2)
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.assertRaises(ValueError):
                history.record("/dose", value)
            with self.assertRaises(ValueError):
                history.record_average("/dose", value)
        series = history.snapshot()["series"][0]
        samples = series["samples"]
        self.assertEqual(len(samples), 300)
        self.assertEqual(samples[0][1], 5)
        self.assertEqual(samples[-1][1], 304)
        self.assertEqual(len(series["average_samples"]), 300)
        self.assertEqual(series["average_samples"][-1][1], 152)

    def test_driver_average_alarm_and_diagnostics_are_independent_per_probe(self):
        with patch.object(dose_web.time, "monotonic", return_value=100) as clock, \
                patch.object(dose_web.time, "time", return_value=1700000000):
            history = dose_web.DoseHistory(["/probe_1/dose", "/probe_2/dose"], 5)
            clock.return_value = 101
            history.record("/probe_1/dose", 200.0)
            history.record_average("/probe_1/dose", 20.0)
            history.record_alarm("/probe_1/dose", True)
            history.record_diagnostics("/probe_1/dose", self.diagnostics(level=1))
            clock.return_value = 120
            result = history.snapshot()
        first, second = result["series"]
        self.assertEqual(result["started_at"] + first["samples"][0][0], 1700000001)
        self.assertEqual(first["average_samples"], [(1, 20.0)])
        self.assertEqual(first["average_age_seconds"], 19)
        self.assertIs(first["alarm_active"], True)
        self.assertEqual(first["diagnostics"]["age_seconds"], 19)
        self.assertEqual(first["diagnostics"]["flags"], {
            name: "OK" for name in dose_web.HEALTH_FLAGS
        })
        self.assertEqual(second["average_samples"], [])
        self.assertIsNone(second["alarm_active"])
        self.assertIsNone(second["diagnostics"])

    def test_connection_diagnostics_replace_previous_healthy_flags_with_unknown(self):
        history = dose_web.DoseHistory(["/dose"], 5)
        history.record_diagnostics("/dose", self.diagnostics())
        history.record_diagnostics("/dose", self.diagnostics(level=3, flags={}))
        diagnostics = history.snapshot()["series"][0]["diagnostics"]
        self.assertEqual(diagnostics["level"], 3)
        self.assertTrue(all(value is None for value in diagnostics["flags"].values()))

    def test_fault_flags_and_alarm_clear_follow_driver_messages(self):
        history = dose_web.DoseHistory(["/dose"], 5)
        flags = {name: "OK" for name in dose_web.HEALTH_FLAGS}
        flags["ht_fault"] = "FAULT"
        history.record_diagnostics("/dose", self.diagnostics(level=1, flags=flags))
        history.record_alarm("/dose", True)
        history.record_alarm("/dose", False)
        series = history.snapshot()["series"][0]
        self.assertEqual(series["diagnostics"]["flags"]["ht_fault"], "FAULT")
        self.assertIs(series["alarm_active"], False)
        flags["ht_fault"] = "invalid"
        with self.assertRaises(ValueError):
            history.record_diagnostics("/dose", self.diagnostics(flags=flags))
        with self.assertRaises(ValueError):
            history.record_alarm("/dose", "False")


class TestPlotHTTP(unittest.TestCase):
    def test_serves_plot_and_readings_without_exposing_other_files(self):
        history = dose_web.DoseHistory(
            ["/gamma_probe/dose_rate"], 5,
            thresholds={"/gamma_probe/dose_rate": 75.0},
            probe_names={"/gamma_probe/dose_rate": "Import Drum Probe"},
        )
        history.record("/gamma_probe/dose_rate", 0.0)
        page = (ROOT / "web" / "dose_plot.html").read_bytes()
        server = dose_web.make_server(history, page, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = "http://127.0.0.1:%d" % server.server_port
            with urlopen(base + "/", timeout=2) as response:
                self.assertEqual(response.read(), page)
            with urlopen(base + "/api/data", timeout=2) as response:
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                result = json.load(response)
                self.assertEqual(result["series"][0]["topic"], "/gamma_probe/dose_rate")
                self.assertEqual(result["series"][0]["samples"][0][1], 0.0)
                self.assertEqual(result["series"][0]["probe_name"], "Import Drum Probe")
                self.assertEqual(result["series"][0]["threshold_usvh"], 75.0)
            with self.assertRaises(HTTPError) as error:
                urlopen(base + "/../package.xml", timeout=2)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class TestPlotSettings(unittest.TestCase):
    def run_viewer(self, params):
        rospy = SimpleNamespace(
            init_node=Mock(), get_param=lambda key, default=None: params.get(key, default),
            resolve_name=lambda topic: topic, Subscriber=Mock(), spin=Mock(), loginfo=Mock(),
        )
        modules = {
            "rospy": rospy,
            "rospkg": SimpleNamespace(RosPack=lambda: SimpleNamespace(get_path=lambda _: str(ROOT))),
            "diagnostic_msgs.msg": SimpleNamespace(DiagnosticStatus=object),
            "std_msgs.msg": SimpleNamespace(Bool=object, Float64=object),
        }
        with patch.dict(sys.modules, modules), \
                patch.object(dose_web, "make_server", return_value=Mock()) as make_server:
            dose_web.main()
        return make_server.call_args[0][0]

    def test_reads_four_yaml_names_and_independent_thresholds_from_driver_namespaces(self):
        config = yaml.safe_load((ROOT / "config" / "probes.yaml").read_text())
        topics = ["/probe_%d/gamma_probe/dose_rate" % index for index in range(1, 5)]
        params = {"~topics": topics}
        expected = []
        for index, topic in enumerate(topics, 1):
            settings = config["probe_%d" % index]["gamma_probe"]
            namespace = topic.rsplit("/", 1)[0]
            params.update({namespace + "/" + key: value for key, value in settings.items()})
            params[namespace + "/dose_threshold_usvh"] = index * 10.0
            expected.append(settings["probe_name"])
        result = self.run_viewer(params).snapshot()["series"]
        self.assertEqual([row["probe_name"] for row in result], expected)
        self.assertEqual([row["threshold_usvh"] for row in result], [10, 20, 30, 40])
        self.assertTrue(all(row["age_seconds"] is None for row in result))

    def test_legacy_topic_and_default_label_still_work_without_yaml(self):
        result = self.run_viewer({}).snapshot()["series"]
        self.assertEqual(result[0]["topic"], "/gamma_probe/dose_rate")
        self.assertEqual(result[0]["probe_name"], "Probe 1")
        self.assertIsNone(result[0]["threshold_usvh"])

    def test_invalid_names_are_reported_instead_of_silently_relabelled(self):
        for name in ("", " ", None, 42):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "probe_name"):
                self.run_viewer({"/gamma_probe/probe_name": name})


if __name__ == "__main__":
    unittest.main()
