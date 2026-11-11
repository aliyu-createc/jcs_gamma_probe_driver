#!/usr/bin/env python
"""
Unit tests for the published outputs of the gamma probe driver.

Runs without a ROS master: rospy, the message packages and pyserial are stubbed
before the node is imported, and each publisher records what it was given so the
tests can assert on the driver's actual output.

    python -m unittest discover -s tests
"""
from __future__ import print_function

import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import Mock, patch


# --- Stubs, installed before importing the node ------------------------------

class FakePublisher(object):
    def __init__(self, topic, msg_type, **kwargs):
        self.topic = topic
        self.latch = kwargs.get("latch", False)
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


class FakeRospy(types.ModuleType):
    """Minimal rospy: params are settable per-test, shutdown is a flag."""

    class ROSInterruptException(Exception):
        pass

    def __init__(self):
        types.ModuleType.__init__(self, "rospy")
        self.params = {}
        self.publishers = {}
        self.shutdown = False
        self.warnings = []

    def reset(self, **params):
        self.params = params
        self.publishers = {}
        self.shutdown = False
        self.warnings = []

    def init_node(self, *args, **kwargs):
        pass

    def get_name(self):
        return "/gamma_probe"

    def get_param(self, name, default=None):
        return self.params.get(name, default)

    def Publisher(self, topic, msg_type, **kwargs):
        pub = FakePublisher(topic, msg_type, **kwargs)
        self.publishers[topic] = pub
        return pub

    def is_shutdown(self):
        return self.shutdown

    def sleep(self, _duration):
        pass

    def loginfo(self, *args):
        pass

    def logwarn(self, fmt, *args):
        self.warnings.append(fmt % args if args else fmt)

    def logwarn_throttle(self, _period, fmt, *args):
        self.warnings.append(fmt % args if args else fmt)

    def logerr(self, *args):
        pass


class FakeMsg(object):
    def __init__(self, data=None):
        self.data = data


class FakeDiagnosticStatus(object):
    OK = 0
    WARN = 1
    ERROR = 2
    STALE = 3

    def __init__(self):
        self.name = ""
        self.hardware_id = ""
        self.level = self.OK
        self.message = ""
        self.values = []


class FakeKeyValue(object):
    def __init__(self, key="", value=""):
        self.key = key
        self.value = value


class FakeSerialException(Exception):
    pass


def _install_stubs():
    rospy = FakeRospy()
    sys.modules["rospy"] = rospy

    std_msgs = types.ModuleType("std_msgs")
    std_msgs_msg = types.ModuleType("std_msgs.msg")
    std_msgs_msg.Float64 = FakeMsg
    std_msgs_msg.Bool = FakeMsg
    std_msgs_msg.String = FakeMsg
    std_msgs.msg = std_msgs_msg
    sys.modules["std_msgs"] = std_msgs
    sys.modules["std_msgs.msg"] = std_msgs_msg

    diag = types.ModuleType("diagnostic_msgs")
    diag_msg = types.ModuleType("diagnostic_msgs.msg")
    diag_msg.DiagnosticStatus = FakeDiagnosticStatus
    diag_msg.KeyValue = FakeKeyValue
    diag.msg = diag_msg
    sys.modules["diagnostic_msgs"] = diag
    sys.modules["diagnostic_msgs.msg"] = diag_msg

    serial = types.ModuleType("serial")
    serial.Serial = object
    serial.SerialException = FakeSerialException
    serial.EIGHTBITS = 8
    serial.PARITY_NONE = "N"
    serial.STOPBITS_ONE = 1
    sys.modules["serial"] = serial

    return rospy


ROSPY = _install_stubs()

_NODE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "nodes", "gamma_probe_node.py",
)
_spec = importlib.util.spec_from_file_location("gamma_probe_node", _NODE_PATH)
gamma_probe_node = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gamma_probe_node)

GammaProbeNode = gamma_probe_node.GammaProbeNode
crc_ccitt = gamma_probe_node.crc_ccitt


# --- Helpers -----------------------------------------------------------------

def frame(dose="000000012.5", health="1111", serial_number="0042", cmd="06", crc=None):
    """Build a probe frame. crc=None appends a placeholder; crc='auto' computes a valid one."""
    payload = "$%s,%s,%s,%s" % (cmd, serial_number, health, dose)
    if crc == "auto":
        crc = "%04X" % crc_ccitt(payload + "*")
    elif crc is None:
        crc = "0000"
    return "%s*%s\r\n" % (payload, crc)


class FakeConnection(object):
    """Feeds canned lines as bytes, like pyserial, then reports EOF and shuts the node down."""

    def __init__(self, lines, rospy_stub):
        self.lines = [l.encode("ascii") if isinstance(l, str) else l for l in lines]
        self.rospy = rospy_stub
        self.is_open = True

    def readline(self):
        if self.lines:
            return self.lines.pop(0)
        self.rospy.shutdown = True  # exhausted: let run() fall out of its loops
        return b""

    def close(self):
        self.is_open = False


class DriverOutputTest(unittest.TestCase):
    """Base: builds a node with stubbed params and exposes its publishers."""

    def make_node(self, **params):
        ROSPY.reset(**params)
        node = GammaProbeNode()
        self.node = node
        self.dose = ROSPY.publishers["~dose_rate"]
        self.dose_avg = ROSPY.publishers["~dose_rate_avg"]
        self.alarm = ROSPY.publishers["~alarm"]
        self.diagnostics = ROSPY.publishers["~diagnostics"]
        self.raw = ROSPY.publishers["~raw_message"]
        return node

    def run_lines(self, lines, **params):
        node = self.make_node(**params)
        node.connect = lambda: setattr(node, "serial_conn", FakeConnection(lines, ROSPY)) or True
        node.run()
        return node

    def doses(self):
        return [m.data for m in self.dose.messages]

    def alarms(self):
        return [m.data for m in self.alarm.messages]


# --- Startup output ----------------------------------------------------------

class TestStartupOutput(DriverOutputTest):

    def test_alarm_is_latched_and_starts_false(self):
        """A subscriber connecting late must still see a defined alarm state."""
        self.make_node()
        self.assertTrue(self.alarm.latch)
        self.assertEqual(self.alarms(), [False])

    def test_default_threshold_is_150_usvh(self):
        """0.15 mSv/h, per the operating manual. Guards against drift in the default."""
        node = self.make_node()
        self.assertEqual(node.threshold, 150.0)


# --- Dose rate and averaging -------------------------------------------------

class TestDoseOutput(DriverOutputTest):

    def test_valid_frame_publishes_dose_raw_and_diagnostics(self):
        self.run_lines([frame(dose="000000012.5")])
        self.assertEqual(self.doses(), [12.5])
        self.assertEqual(self.raw.messages[0].data, frame(dose="000000012.5").strip())
        self.assertEqual(len(self.diagnostics.messages), 1)

    def test_average_is_published_over_a_ten_sample_window(self):
        # 10 samples at 100.0, then one at 0.0: the average must drop by a tenth,
        # not to zero, and the first sample must have aged out.
        lines = [frame(dose="000000100.0")] * 10 + [frame(dose="000000000.0")]
        self.run_lines(lines)
        averages = [m.data for m in self.dose_avg.messages]
        self.assertAlmostEqual(averages[0], 100.0)
        self.assertAlmostEqual(averages[-1], 90.0)
        self.assertEqual(len(averages), 11)

    def test_dose_rate_published_per_frame_not_smoothed(self):
        """~dose_rate must stay instantaneous; only ~dose_rate_avg is smoothed."""
        self.run_lines([frame(dose="000000010.0"), frame(dose="000000030.0")])
        self.assertEqual(self.doses(), [10.0, 30.0])
        self.assertAlmostEqual(self.dose_avg.messages[-1].data, 20.0)


# --- Malformed input ---------------------------------------------------------

class TestMalformedFrames(DriverOutputTest):

    def assert_rejected(self, line):
        self.run_lines([line])
        self.assertEqual(self.doses(), [], "bad frame must not publish a dose rate: %r" % line)
        self.assertEqual(self.diagnostics.messages, [])

    def test_missing_start_delimiter(self):
        self.assert_rejected("06,0042,1111,000000012.5*0000\r\n")

    def test_missing_crc_delimiter(self):
        self.assert_rejected("$06,0042,1111,000000012.5\r\n")

    def test_wrong_command_code(self):
        self.assert_rejected(frame(cmd="07"))

    def test_non_numeric_dose(self):
        self.assert_rejected(frame(dose="ERROR"))

    def test_short_health_field(self):
        self.assert_rejected(frame(health="11"))

    def test_wrong_field_count(self):
        self.assert_rejected("$06,0042,1111*0000\r\n")

    def test_raw_message_is_published_even_when_the_frame_is_rejected(self):
        """~raw_message is the evidential record, so it must capture garbage too."""
        self.run_lines(["$06,0042,GARBAGE*0000\r\n"])
        self.assertEqual(len(self.raw.messages), 1)
        self.assertEqual(self.doses(), [])


# --- Threshold and hysteresis ------------------------------------------------

class TestAlarmOutput(DriverOutputTest):

    def test_alarm_asserts_at_the_threshold(self):
        self.run_lines([frame(dose="000000150.0")], **{"~dose_threshold_usvh": 150.0})
        self.assertEqual(self.alarms(), [False, True])

    def test_no_alarm_below_the_threshold(self):
        self.run_lines([frame(dose="000000149.9")], **{"~dose_threshold_usvh": 150.0})
        self.assertEqual(self.alarms(), [False])

    def test_alarm_holds_inside_the_hysteresis_band(self):
        """Above (threshold - hysteresis) the alarm must stay asserted."""
        lines = [frame(dose="000000151.0"), frame(dose="000000145.0")]
        self.run_lines(lines, **{"~dose_threshold_usvh": 150.0, "~alarm_hysteresis_usvh": 10.0})
        self.assertEqual(self.alarms(), [False, True])
        self.assertTrue(self.node.alarm_active)

    def test_alarm_clears_below_the_hysteresis_band(self):
        lines = [frame(dose="000000151.0"), frame(dose="000000139.0")]
        self.run_lines(lines, **{"~dose_threshold_usvh": 150.0, "~alarm_hysteresis_usvh": 10.0})
        self.assertEqual(self.alarms(), [False, True, False])

    def test_alarm_is_published_only_on_transition(self):
        """Steady-state re-publishing would swamp the topic; only edges are sent."""
        lines = [frame(dose="000000151.0")] * 5
        self.run_lines(lines, **{"~dose_threshold_usvh": 150.0})
        self.assertEqual(self.alarms(), [False, True])

    def test_alarm_keys_off_instantaneous_dose_not_the_average(self):
        """A single-sample excursion must latch the alarm even though the 10 s
        average stays well under the threshold."""
        lines = [frame(dose="000000010.0")] * 9 + [frame(dose="000000200.0")]
        self.run_lines(lines, **{"~dose_threshold_usvh": 150.0})
        self.assertIn(True, self.alarms())
        self.assertLess(self.dose_avg.messages[-1].data, 150.0)


# --- Health / diagnostics ----------------------------------------------------

class TestDiagnosticsOutput(DriverOutputTest):

    def diag_values(self, msg):
        return {kv.key: kv.value for kv in msg.values}

    def test_healthy_probe_reports_ok(self):
        self.run_lines([frame(health="1111", dose="000000010.0")])
        msg = self.diagnostics.messages[-1]
        self.assertEqual(msg.level, FakeDiagnosticStatus.OK)
        values = self.diag_values(msg)
        self.assertEqual(values["overload"], "OK")
        self.assertEqual(values["ht_fault"], "OK")

    def test_health_digits_map_to_the_right_labels(self):
        # Digit order: overload, lifetime_counts, ht_fault, no_counts. 0 = FAULT.
        self.run_lines([frame(health="1101")])
        values = self.diag_values(self.diagnostics.messages[-1])
        self.assertEqual(values["overload"], "OK")
        self.assertEqual(values["lifetime_counts"], "OK")
        self.assertEqual(values["ht_fault"], "FAULT")
        self.assertEqual(values["no_counts"], "OK")

    def test_health_fault_warns_but_does_not_suppress_the_dose_rate(self):
        """Documented behaviour (manual 5.6.4): an overload fault raises only a
        diagnostics WARN, and the reading from that frame is still published.
        The operator, not the driver, is the interlock."""
        self.run_lines([frame(health="0111", dose="000000005.0")])
        self.assertEqual(self.diagnostics.messages[-1].level, FakeDiagnosticStatus.WARN)
        self.assertEqual(self.doses(), [5.0])

    def test_health_fault_does_not_assert_the_alarm(self):
        self.run_lines([frame(health="0111", dose="000000005.0")], **{"~dose_threshold_usvh": 150.0})
        self.assertEqual(self.alarms(), [False])

    def test_threshold_breach_reports_warn(self):
        self.run_lines([frame(dose="000000200.0")], **{"~dose_threshold_usvh": 150.0})
        self.assertEqual(self.diagnostics.messages[-1].level, FakeDiagnosticStatus.WARN)


# --- Loss of data ------------------------------------------------------------

class TestDataLoss(DriverOutputTest):

    def test_timeout_publishes_nothing_and_leaves_the_alarm_stale(self):
        """Documented behaviour (manual 5.6.4): on loss of data the driver stops
        publishing and ~alarm holds its last value — including False. A stale
        reading is not an absence of hazard, which is why the manual requires the
        operator to treat a non-updating display as a potentially elevated field."""
        self.run_lines(["", "", ""])
        self.assertEqual(self.doses(), [])
        self.assertEqual(self.alarms(), [False])  # only the initial latched value
        self.assertEqual(self.diagnostics.messages, [])


# --- CRC ---------------------------------------------------------------------

class TestCrc(DriverOutputTest):

    def test_crc_ccitt_matches_the_standard_check_vector(self):
        self.assertEqual(crc_ccitt("123456789"), 0x29B1)

    def test_bad_crc_is_rejected_when_verification_is_enabled(self):
        self.run_lines([frame(crc="DEAD")], **{"~verify_crc": True})
        self.assertEqual(self.doses(), [])

    def test_valid_crc_is_accepted_when_verification_is_enabled(self):
        self.run_lines([frame(dose="000000012.5", crc="auto")], **{"~verify_crc": True})
        self.assertEqual(self.doses(), [12.5])

    def test_non_hex_crc_is_rejected_when_verification_is_enabled(self):
        self.run_lines([frame(crc="ZZZZ")], **{"~verify_crc": True})
        self.assertEqual(self.doses(), [])

    def test_bad_crc_is_accepted_by_default(self):
        """verify_crc defaults to False, so a corrupted frame that still parses is
        published as a real reading. Manual 5.6.4 requires it to be enabled for any
        deployment where the dose rate is relied on operationally."""
        self.run_lines([frame(dose="000000012.5", crc="DEAD")])
        self.assertEqual(self.doses(), [12.5])


class TestAdsInput(DriverOutputTest):
    def setUp(self):
        self.ads = types.ModuleType("pyads")
        self.ads.ADSError = type("ADSError", (Exception,), {})
        self.ads.PLCTYPE_UDINT = "UDINT"
        self.ads.PLCTYPE_STRING = "STRING"
        self.ads.open_port = Mock()
        self.ads.close_port = Mock()
        self.ads.set_local_address = Mock()
        self.plc = Mock()
        self.ads.Connection = Mock(return_value=self.plc)
        self.module_patch = patch.dict(sys.modules, {"pyads": self.ads})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.params = {
            "~ads_host": "192.0.2.10",
            "~ads_ams_net_id": "192.0.2.10.1.1",
            "~ads_local_ams_net_id": "192.0.2.20.1.1",
            "~ads_message_symbol": "GVL_Gamma.sRawMessage",
            "~ads_counter_symbol": "GVL_Gamma.nRxSequence",
            "~ads_poll_interval": 0.1,
            "~ads_stale_timeout": 0.2,
        }

    def run_ads(self, reads, ticks, **overrides):
        params = dict(self.params)
        params.update(overrides)
        node = self.make_node(**params)
        self.plc.read_by_name.side_effect = reads
        self.clock = 0.0
        self.sleeps = []

        def sleep(duration):
            self.clock += duration
            self.sleeps.append(duration)
            if len(self.sleeps) >= ticks:
                ROSPY.shutdown = True

        with patch.object(gamma_probe_node.time, "monotonic",
                          side_effect=lambda: self.clock), \
                patch.object(gamma_probe_node.time, "sleep", side_effect=sleep):
            node.run()
        return node

    def test_ads_uses_configured_endpoint_symbols_types_and_closes(self):
        self.run_ads([0, 2, frame(), 2], 1)
        self.assertEqual(self.doses(), [12.5])
        self.ads.Connection.assert_called_once_with("192.0.2.10.1.1", 851, "192.0.2.10")
        self.ads.set_local_address.assert_called_once_with("192.0.2.20.1.1")
        self.ads.open_port.assert_called_once_with()
        self.ads.close_port.assert_called_once_with()
        self.plc.set_timeout.assert_called_once_with(2000)
        self.assertEqual(self.plc.read_by_name.call_args_list[1].args,
                         ("GVL_Gamma.nRxSequence", "UDINT"))
        self.assertEqual(self.plc.read_by_name.call_args_list[2].args,
                         ("GVL_Gamma.sRawMessage", "STRING"))
        self.plc.close.assert_called_once_with()
        self.assertEqual(self.raw.messages[0].data, frame().strip())
        self.assertEqual(self.diagnostics.messages[-1].level, FakeDiagnosticStatus.OK)

    def test_retained_value_is_not_published_at_startup(self):
        self.run_ads([8, 8, frame(), 8], 1)
        self.assertEqual(self.doses(), [])
        self.assertEqual(self.raw.messages, [])
        self.assertEqual(self.diagnostics.messages[-1].level, FakeDiagnosticStatus.STALE)

    def test_counter_deduplicates_but_identical_fresh_readings_are_published(self):
        self.run_ads([0, 2, frame(), 2, 2, frame(), 2, 4, frame(), 4], 3)
        self.assertEqual(self.doses(), [12.5, 12.5])
        self.assertEqual(len(self.dose_avg.messages), 2)

    def test_odd_sequence_and_changed_snapshot_are_rejected(self):
        self.run_ads([0, 1, 2, frame(), 4, 4, frame(), 4], 3)
        self.assertEqual(self.doses(), [12.5])
        self.assertEqual(len(self.raw.messages), 1)

    def test_counter_wrap_is_a_new_sample(self):
        self.run_ads([4294967294, 0, frame(), 0], 1)
        self.assertEqual(self.doses(), [12.5])

    def test_stale_data_at_exact_timeout_preserves_alarm_and_clears_average(self):
        high = frame(dose="000000200.0")
        self.run_ads([0, 2, high, 2, 2, high, 2, 2, high, 2], 3)
        self.assertEqual(self.doses(), [200.0])
        self.assertEqual(self.alarms(), [False, True])
        self.assertEqual(self.diagnostics.messages[-1].level, FakeDiagnosticStatus.STALE)
        self.assertEqual(list(self.node.dose_buffer), [])

    def test_recovery_after_stale_starts_a_new_average_and_clears_alarm(self):
        high = frame(dose="000000200.0")
        self.run_ads([0, 2, high, 2, 2, high, 2, 2, high, 2, 4, frame(), 4], 4)
        self.assertEqual(self.doses(), [200.0, 12.5])
        self.assertEqual(self.dose_avg.messages[-1].data, 12.5)
        self.assertEqual(self.alarms(), [False, True, False])
        self.assertEqual(self.diagnostics.messages[-1].level, FakeDiagnosticStatus.OK)

    def test_invalid_fresh_frames_do_not_prevent_stale_status(self):
        self.run_ads([0, 2, "garbage", 2, 4, "garbage", 4, 6, "garbage", 6], 3)
        self.assertEqual(self.doses(), [])
        self.assertEqual(len(self.raw.messages), 3)
        levels = [msg.level for msg in self.diagnostics.messages]
        self.assertIn(FakeDiagnosticStatus.ERROR, levels)
        self.assertEqual(levels[-1], FakeDiagnosticStatus.STALE)

    def test_ads_reuses_crc_and_health_diagnostics(self):
        self.run_ads([0, 2, frame(crc="DEAD"), 2,
                      4, frame(health="1101", crc="auto"), 4], 2,
                     **{"~verify_crc": True})
        self.assertEqual(self.doses(), [12.5])
        self.assertEqual(self.diagnostics.messages[-1].level, FakeDiagnosticStatus.WARN)

    def test_read_failure_reconnects_without_republishing_retained_data(self):
        self.run_ads([0, 2, frame(), 2, self.ads.ADSError("connection lost"),
                      2, 2, frame(), 2, 4, frame(), 4], 4)
        self.assertEqual(self.ads.Connection.call_count, 2)
        self.assertEqual(self.plc.close.call_count, 2)
        self.assertIn(5.0, self.sleeps)
        self.assertEqual(self.doses(), [12.5, 12.5])
        self.assertIn(FakeDiagnosticStatus.ERROR,
                      [msg.level for msg in self.diagnostics.messages])

    def test_open_failure_is_reported_and_connection_closed(self):
        self.plc.open.side_effect = self.ads.ADSError("route missing")
        self.run_ads([], 1)
        self.assertEqual(self.doses(), [])
        self.plc.close.assert_called_once_with()
        self.assertEqual(self.diagnostics.messages[-1].level, FakeDiagnosticStatus.ERROR)

    def test_invalid_configuration_fails_explicitly(self):
        for overrides in (
                {"~tcp_host": "bridge"},
                {"~ads_ams_net_id": "192.0.2.10"},
                {"~ads_local_ams_net_id": "999.0.2.20.1.1"},
                {"~ads_message_symbol": ""},
                {"~ads_counter_symbol": ""},
                {"~ads_port": 0},
                {"~ads_timeout_ms": -1},
                {"~ads_poll_interval": float("nan")},
                {"~ads_poll_interval": 0},
                {"~ads_stale_timeout": -1}):
            params = dict(self.params)
            params.update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.make_node(**params)

    def test_missing_optional_dependency_has_actionable_error(self):
        with patch.dict(sys.modules, {"pyads": None}), \
                self.assertRaisesRegex(ImportError, "requirements-ads.txt"):
            self.make_node(**self.params)

    def test_serial_mode_does_not_import_optional_pyads(self):
        with patch.dict(sys.modules, {"pyads": None}):
            self.run_lines([frame()])
        self.assertEqual(self.doses(), [12.5])


if __name__ == "__main__":
    unittest.main(verbosity=2)
