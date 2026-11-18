#!/usr/bin/env python3
"""Local browser plot of up to four ROS dose-rate topics."""

from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit


HEALTH_FLAGS = ("overload", "lifetime_counts", "ht_fault", "no_counts")


class DoseHistory:
    def __init__(self, topics, stale_timeout, thresholds=None, probe_names=None):
        self.started = time.monotonic()
        self.started_at = time.time()
        self.stale_timeout = stale_timeout
        self.samples = {topic: deque(maxlen=300) for topic in topics}
        self.averages = {topic: deque(maxlen=300) for topic in topics}
        self.alarms = {topic: None for topic in topics}
        self.diagnostics = {topic: None for topic in topics}
        self.thresholds = thresholds if thresholds is not None else {
            topic: None for topic in topics
        }
        self.probe_names = probe_names if probe_names is not None else {
            topic: "Probe %d" % (index + 1) for index, topic in enumerate(topics)
        }
        self.lock = threading.Lock()

    def record(self, topic, value):
        self._record_sample(self.samples, topic, value)

    def record_average(self, topic, value):
        self._record_sample(self.averages, topic, value)

    def _record_sample(self, storage, topic, value):
        if not math.isfinite(value):
            raise ValueError("Dose rate must be finite")
        with self.lock:
            storage[topic].append((time.monotonic() - self.started, value))

    def record_alarm(self, topic, active):
        if type(active) is not bool:
            raise ValueError("Alarm state must be a boolean")
        # The driver alarm is latched and published on transitions, not every frame.
        with self.lock:
            self.alarms[topic] = active

    def record_diagnostics(self, topic, message):
        if message.level not in (0, 1, 2, 3):
            raise ValueError("Unknown diagnostic level")
        flags = {name: None for name in HEALTH_FLAGS}
        for value in message.values:
            if value.key in flags:
                if value.value not in ("OK", "FAULT"):
                    raise ValueError("Unknown health flag value for %s" % value.key)
                flags[value.key] = value.value
        with self.lock:
            self.diagnostics[topic] = {
                "received": time.monotonic() - self.started,
                "level": message.level,
                "message": message.message,
                "hardware_id": message.hardware_id,
                "flags": flags,
            }

    def snapshot(self):
        with self.lock:
            now = time.monotonic() - self.started
            return {
                "now": now,
                "started_at": self.started_at,
                "stale_timeout": self.stale_timeout,
                "series": [
                    {
                        "topic": topic,
                        "probe_name": self.probe_names[topic],
                        "samples": list(samples),
                        "age_seconds": now - samples[-1][0] if samples else None,
                        "average_samples": list(self.averages[topic]),
                        "average_age_seconds": (
                            now - self.averages[topic][-1][0] if self.averages[topic] else None
                        ),
                        "alarm_active": self.alarms[topic],
                        "threshold_usvh": self.thresholds[topic],
                        "diagnostics": (
                            dict(
                                self.diagnostics[topic],
                                age_seconds=now - self.diagnostics[topic]["received"],
                            )
                            if self.diagnostics[topic] is not None else None
                        ),
                    }
                    for topic, samples in self.samples.items()
                ],
            }


def make_server(history, page, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/":
                body = page
                content_type = "text/html; charset=utf-8"
            elif path == "/api/data":
                body = json.dumps(history.snapshot(), allow_nan=False).encode("utf-8")
                content_type = "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; connect-src 'self'; "
                "base-uri 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def log_request(self, code="-", size="-"):
            if str(code) != "200":
                super().log_request(code, size)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    import rospkg
    import rospy
    from diagnostic_msgs.msg import DiagnosticStatus
    from std_msgs.msg import Bool, Float64

    rospy.init_node("gamma_probe_plot")
    topics = rospy.get_param("~topics", ["/gamma_probe/dose_rate"])
    port = rospy.get_param("~port", 8080)
    stale_timeout = rospy.get_param("~stale_timeout", 5.0)
    if (not isinstance(topics, list) or not 1 <= len(topics) <= 4
            or any(not isinstance(topic, str) or not topic.startswith("/")
                   for topic in topics)):
        raise ValueError("~topics must be a list of one to four absolute ROS topic names")
    topics = [rospy.resolve_name(topic) for topic in topics]
    if len(set(topics)) != len(topics):
        raise ValueError("~topics must not contain duplicates")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("~port must be an integer in [1, 65535]")
    if (isinstance(stale_timeout, bool) or not isinstance(stale_timeout, (int, float))
            or not math.isfinite(stale_timeout) or stale_timeout <= 0):
        raise ValueError("~stale_timeout must be finite and positive")

    thresholds = {}
    probe_names = {}
    for index, topic in enumerate(topics):
        namespace = topic.rsplit("/", 1)[0]
        threshold = rospy.get_param(namespace + "/dose_threshold_usvh", None)
        if threshold is not None and (
                isinstance(threshold, bool) or not isinstance(threshold, (int, float))
                or not math.isfinite(threshold)):
            raise ValueError("Invalid dose threshold for %s" % topic)
        thresholds[topic] = threshold
        name = rospy.get_param(namespace + "/probe_name", "Probe %d" % (index + 1))
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Invalid probe_name for %s" % topic)
        probe_names[topic] = name
    history = DoseHistory(topics, stale_timeout, thresholds, probe_names)
    page = (Path(rospkg.RosPack().get_path("jcs_gamma_probe"))
            / "web" / "dose_plot.html").read_bytes()
    server = make_server(history, page, port)

    recorders = {
        "dose": history.record,
        "average": history.record_average,
        "alarm": history.record_alarm,
    }

    def received(message, callback):
        topic, kind = callback
        try:
            if kind == "diagnostics":
                history.record_diagnostics(topic, message)
            else:
                recorders[kind](topic, message.data)
        except ValueError as exc:
            rospy.logwarn_throttle(10.0, "Invalid %s for %s: %s" % (kind, topic, exc))

    subscribers = []
    for topic in topics:
        namespace = topic.rsplit("/", 1)[0]
        for source, datatype, kind in (
                (topic, Float64, "dose"),
                (namespace + "/dose_rate_avg", Float64, "average"),
                (namespace + "/alarm", Bool, "alarm"),
                (namespace + "/diagnostics", DiagnosticStatus, "diagnostics")):
            subscribers.append(rospy.Subscriber(
                source, datatype, received, callback_args=(topic, kind), queue_size=10,
            ))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    rospy.loginfo("Dose plot: http://127.0.0.1:%d (topics: %s)", port, ", ".join(topics))
    try:
        rospy.spin()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        for subscriber in subscribers:
            subscriber.unregister()


if __name__ == "__main__":
    main()
