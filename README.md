# JCS Gamma Probe Driver

ROS driver for the **JCS RMS30-102ASx ASCII Gamma Probe** over RS485/USB serial.

## Overview

Reads dose rate from a John Caunt Scientific RMS30-102ASx gamma probe connected via a USB-to-RS485 adapter. Publishes dose rate to ROS topics and raises an alarm when a configurable threshold is exceeded.

### Probe Protocol

The probe transmits automatically at 1Hz (no polling required):

```
$06,SSSS,HHHH,DDDDDDDDD.D*CCCC\r
```

| Field | Description |
|-------|-------------|
| `06` | Send data command |
| `SSSS` | Device serial number |
| `HHHH` | Health digits (overload, lifetime, HT fault, no counts) — 1=OK, 0=fault |
| `DDDDDDDDD.D` | Dose rate in µSv/h |
| `CCCC` | CRC-CCITT 16-bit checksum (optional) |

## Files

| File | Purpose |
|------|---------|
| `nodes/gamma_probe_node.py` | ROS node — reads probe data (serial or TCP), publishes to ROS topics |
| `serial_bridge.py` | Windows utility — bridges COM port to TCP for Docker access |
| `plot_dose.py` | Windows utility — live dose rate plot with audible alarm |
| `Dockerfile` | Builds a self-contained ROS Noetic container |
| `entrypoint.sh` | Docker entrypoint script |
| `launch/gamma_probe.launch` | ROS launch file with configurable parameters |

## ROS Topics

| Topic | Type | Description |
|-------|------|-------------|
| `~dose_rate` | `std_msgs/Float64` | Dose rate in µSv/h |
| `~alarm` | `std_msgs/Bool` | True when dose exceeds threshold (latched) |
| `~diagnostics` | `diagnostic_msgs/DiagnosticStatus` | Probe health and status |
| `~raw_message` | `std_msgs/String` | Raw ASCII message from probe |

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `~port` | `/dev/ttyUSB0` | Serial port |
| `~baud_rate` | `9600` | Baud rate |
| `~tcp_host` | `` (empty) | TCP bridge host (enables TCP mode when set) |
| `~tcp_port` | `3241` | TCP bridge port |
| `~dose_threshold_usvh` | `150.0` | Alarm threshold in µSv/h (0.15 mSv/h) |
| `~alarm_hysteresis_usvh` | `1.0` | Hysteresis band to clear alarm |
| `~verify_crc` | `False` | Validate CRC-CCITT checksum |
| `~frame_id` | `gamma_probe` | Frame ID for messages |

## Setup (Windows + Docker)

### Prerequisites

- Docker Desktop
- Python 3 with `pyserial` and `matplotlib` (`pip install pyserial matplotlib`)
- USB-to-RS485 adapter (e.g. CH340-based) connected to probe

### Build

```powershell
docker build -t jcs_gamma_probe .
```

### Run

**Terminal 1 — Start serial bridge:**
```powershell
python serial_bridge.py
```

**Terminal 2 — Run the ROS container:**
```powershell
docker run -it --rm --name gamma_probe jcs_gamma_probe roslaunch jcs_gamma_probe gamma_probe.launch tcp_host:=host.docker.internal
```

**Terminal 3 — Monitor topics:**
```powershell
docker exec -it gamma_probe bash -c "source /catkin_ws/devel/setup.bash && rostopic echo /gamma_probe/dose_rate"
```

### Live Plot (standalone, no Docker)

```powershell
python plot_dose.py
```

Displays real-time dose rate with a 150 µSv/h (0.15 mSv/h) threshold and audible alarm.

### Direct Serial Test

```powershell
python -c "import serial; s=serial.Serial('COM6',9600,timeout=5); print(repr(s.read_until(b'\r'))); s.close()"
```

## Linux / Direct Serial (no bridge needed)

```bash
roslaunch jcs_gamma_probe gamma_probe.launch port:=/dev/ttyUSB0
```

## Hardware

- **Probe**: JCS RMS30-102ASx (9600 baud, 8N1, RS485)
- **Power**: 12V DC, 200mA minimum
- **Wiring**: Data A (+) → adapter A, Data B (-) → adapter B, shared GND
