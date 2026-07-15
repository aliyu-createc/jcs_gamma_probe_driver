#!/usr/bin/env python
"""
Gamma Probe Node - RMS30-102ASx ASCII Gamma Probe driver.

Reads dose rate from a JCS RMS30-102ASx gamma probe connected via USB-to-RS485
adapter. Publishes dose rate and raises alarm when a configurable threshold is
exceeded.

Protocol (from probe at 1 Hz, no polling required):
  $06,SSSS,HHHH,DDDDDDDDD.D*CCCC\r\n
  - 06: send data command
  - SSSS: device serial number
  - HHHH: health digits (overload, lifetime, HT fault, no counts) 1=OK 0=fault
  - DDDDDDDDD.D: dose rate in uSv/h
  - CCCC: CRC-CCITT 16-bit (optional verification)

Parameters:
  ~port (str): Serial port (default: /dev/ttyUSB0, Windows e.g. COM3)
  ~baud_rate (int): Baud rate (default: 9600)
  ~dose_threshold_usvh (float): Alarm threshold in uSv/h (default: 150.0, i.e. 0.15 mSv/h)
  ~alarm_hysteresis_usvh (float): Hysteresis band below threshold to clear alarm (default: 1.0)
  ~verify_crc (bool): Whether to validate CRC-CCITT checksum (default: False)
  ~frame_id (str): Frame ID for published messages (default: gamma_probe)
"""
from __future__ import print_function

from collections import deque
import socket
import serial
import rospy
from std_msgs.msg import Float64, Bool, String
from diagnostic_msgs.msg import DiagnosticStatus, KeyValue


def crc_ccitt(data):
    """Compute CRC-CCITT (0xFFFF initial) over a byte string."""
    crc = 0xFFFF
    for byte in bytearray(data.encode('ascii') if isinstance(data, str) else data):
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc


class GammaProbeNode(object):
    def __init__(self):
        rospy.init_node("gamma_probe_node")

        # Parameters
        self.port = rospy.get_param("~port", "/dev/ttyUSB0")
        self.baud_rate = rospy.get_param("~baud_rate", 9600)
        self.tcp_host = rospy.get_param("~tcp_host", "")
        self.tcp_port = rospy.get_param("~tcp_port", 3241)
        self.threshold = rospy.get_param("~dose_threshold_usvh", 150.0)
        self.hysteresis = rospy.get_param("~alarm_hysteresis_usvh", 1.0)
        self.verify_crc = rospy.get_param("~verify_crc", False)
        self.frame_id = rospy.get_param("~frame_id", "gamma_probe")

        # State
        self.alarm_active = False
        self.serial_conn = None
        self.dose_buffer = deque(maxlen=10)  # 10-second averaging at 1 Hz

        # Publishers
        self.pub_dose = rospy.Publisher("~dose_rate", Float64, queue_size=10)
        self.pub_dose_avg = rospy.Publisher("~dose_rate_avg", Float64, queue_size=10)
        self.pub_alarm = rospy.Publisher("~alarm", Bool, queue_size=10, latch=True)
        self.pub_diagnostics = rospy.Publisher("~diagnostics", DiagnosticStatus, queue_size=10)
        self.pub_raw = rospy.Publisher("~raw_message", String, queue_size=10)

        # Publish initial non-alarm state
        self.pub_alarm.publish(Bool(data=False))

        rospy.loginfo("Gamma probe node: port=%s, threshold=%.1f uSv/h", self.port, self.threshold)

    def connect(self):
        """Open serial or TCP connection to the probe."""
        if self.tcp_host:
            return self._connect_tcp()
        return self._connect_serial()

    def _connect_tcp(self):
        """Connect to probe via TCP bridge."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10.0)
            sock.connect((self.tcp_host, self.tcp_port))
            self.serial_conn = sock.makefile('rb')
            self._tcp_socket = sock
            rospy.loginfo("Connected to gamma probe via TCP %s:%d", self.tcp_host, self.tcp_port)
            return True
        except (socket.error, OSError) as e:
            rospy.logerr("Failed to connect to TCP %s:%d: %s", self.tcp_host, self.tcp_port, e)
            return False

    def _connect_serial(self):
        """Open serial connection to the probe."""
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=5.0
            )
            rospy.loginfo("Connected to gamma probe on %s", self.port)
            return True
        except serial.SerialException as e:
            rospy.logerr("Failed to open serial port %s: %s", self.port, e)
            return False

    def parse_message(self, line):
        """
        Parse a probe message.
        Returns (serial_number, health, dose_rate) or None on parse failure.
        """
        line = line.strip()
        if not line.startswith('$'):
            return None

        # Split payload and CRC at '*'
        if '*' not in line:
            return None

        payload_part, crc_part = line.rsplit('*', 1)

        # Optional CRC verification
        if self.verify_crc and len(crc_part) == 4:
            # CRC is computed over payload including '$' up to and including '*'
            crc_data = payload_part + '*'
            expected_crc = crc_ccitt(crc_data)
            try:
                received_crc = int(crc_part, 16)
            except ValueError:
                rospy.logwarn("Invalid CRC hex: %s", crc_part)
                return None
            if expected_crc != received_crc:
                rospy.logwarn("CRC mismatch: expected %04X, got %04X", expected_crc, received_crc)
                return None

        # Remove '$' and parse CSV fields
        fields = payload_part[1:].split(',')
        if len(fields) != 4:
            rospy.logwarn("Unexpected field count: %d in '%s'", len(fields), line)
            return None

        cmd, serial_number, health, dose_str = fields

        if cmd != '06':
            rospy.logwarn("Unexpected command code: %s", cmd)
            return None

        try:
            dose_rate = float(dose_str)
        except ValueError:
            rospy.logwarn("Invalid dose rate value: %s", dose_str)
            return None

        if len(health) != 4:
            rospy.logwarn("Invalid health field: %s", health)
            return None

        return serial_number, health, dose_rate

    def evaluate_threshold(self, dose_rate):
        """Apply threshold with hysteresis. Returns True if alarm should be active."""
        if not self.alarm_active and dose_rate >= self.threshold:
            return True
        elif self.alarm_active and dose_rate < (self.threshold - self.hysteresis):
            return False
        return self.alarm_active

    def publish_diagnostics(self, serial_number, health, dose_rate):
        """Publish diagnostic status from probe health digits."""
        diag = DiagnosticStatus()
        diag.name = "gamma_probe/%s" % serial_number
        diag.hardware_id = serial_number

        labels = ["overload", "lifetime_counts", "ht_fault", "no_counts"]
        all_ok = True
        for i, label in enumerate(labels):
            ok = health[i] == '1'
            if not ok:
                all_ok = False
            diag.values.append(KeyValue(key=label, value="OK" if ok else "FAULT"))

        diag.values.append(KeyValue(key="dose_rate_usvh", value="%.1f" % dose_rate))
        diag.values.append(KeyValue(key="alarm_active", value=str(self.alarm_active)))

        if not all_ok:
            diag.level = DiagnosticStatus.WARN
            diag.message = "Probe health warning"
        elif self.alarm_active:
            diag.level = DiagnosticStatus.WARN
            diag.message = "Dose threshold exceeded: %.1f uSv/h" % dose_rate
        else:
            diag.level = DiagnosticStatus.OK
            diag.message = "Normal operation: %.1f uSv/h" % dose_rate

        self.pub_diagnostics.publish(diag)

    def run(self):
        """Main loop: read serial data, parse, publish, and evaluate threshold."""
        while not rospy.is_shutdown():
            if not self.connect():
                rospy.logwarn("Retrying connection in 5 seconds...")
                rospy.sleep(5.0)
                continue

            while not rospy.is_shutdown():
                try:
                    if self.tcp_host:
                        raw_line = self.serial_conn.readline().decode('ascii', errors='ignore')
                    else:
                        raw_line = self.serial_conn.readline().decode('ascii', errors='ignore')
                except (serial.SerialException, OSError) as e:
                    rospy.logerr("Read error: %s. Reconnecting...", e)
                    break

                if not raw_line:
                    # Timeout - no data received
                    rospy.logwarn_throttle(10.0, "No data from gamma probe (timeout)")
                    continue

                self.pub_raw.publish(String(data=raw_line.strip()))

                result = self.parse_message(raw_line)
                if result is None:
                    continue

                serial_number, health, dose_rate = result

                # Publish dose rate
                self.pub_dose.publish(Float64(data=dose_rate))

                # Publish 10-second average
                self.dose_buffer.append(dose_rate)
                avg_dose = sum(self.dose_buffer) / len(self.dose_buffer)
                self.pub_dose_avg.publish(Float64(data=avg_dose))

                # Evaluate threshold decision
                new_alarm_state = self.evaluate_threshold(dose_rate)
                if new_alarm_state != self.alarm_active:
                    self.alarm_active = new_alarm_state
                    self.pub_alarm.publish(Bool(data=self.alarm_active))
                    if self.alarm_active:
                        rospy.logwarn("ALARM: Dose rate %.1f uSv/h exceeds threshold %.1f uSv/h",
                                     dose_rate, self.threshold)
                    else:
                        rospy.loginfo("ALARM CLEARED: Dose rate %.1f uSv/h below threshold", dose_rate)

                # Publish diagnostics
                self.publish_diagnostics(serial_number, health, dose_rate)

            # Connection lost - clean up
            if self.tcp_host:
                try:
                    self._tcp_socket.close()
                except Exception:
                    pass
            elif self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()
            self.serial_conn = None


if __name__ == "__main__":
    try:
        node = GammaProbeNode()
        node.run()
    except rospy.ROSInterruptException:
        pass
