# JCS Gamma Probe Driver

ROS driver for the **JCS RMS30-102ASx ASCII Gamma Probe** over RS485/USB serial.

## Overview

Reads dose rate from a John Caunt Scientific RMS30-102ASx gamma probe through serial, a raw TCP stream, or a Beckhoff PLC exposing the raw message through ADS. Publishes dose rate to ROS topics and raises an alarm when a configurable threshold is exceeded.

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
| `nodes/gamma_probe_node.py` | ROS node — reads probe data (serial, TCP or ADS), publishes to ROS topics |
| `requirements-ads.txt` | Optional Python dependency for Linux ADS mode |
| `serial_bridge.py` | Windows utility — bridges COM port to TCP for Docker access |
| `plot_dose.py` | Windows utility — live dose rate plot with audible alarm |
| `Dockerfile` | Builds a self-contained ROS Noetic container |
| `entrypoint.sh` | Docker entrypoint script |
| `launch/gamma_probe.launch` | ROS launch file with configurable parameters |
| `launch/gamma_probes_ads.launch` | Launches four probe nodes reading one PLC over ADS |

## ROS Topics

| Topic | Type | Description |
|-------|------|-------------|
| `~dose_rate` | `std_msgs/Float64` | Dose rate in µSv/h |
| `~dose_rate_avg` | `std_msgs/Float64` | Mean of the last ten received readings |
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
| `~ads_host` | `` (empty) | PLC IP address; enables ADS mode when set; cannot be combined with `tcp_host` |
| `~ads_ams_net_id` | `` (empty) | PLC AMS Net ID (required for ADS; six decimal bytes) |
| `~ads_local_ams_net_id` | `` (empty) | Linux client's AMS Net ID registered in the PLC return route (required for ADS) |
| `~ads_port` | `851` | TwinCAT 3 PLC runtime ADS port; confirm with the PLC engineer |
| `~ads_message_symbol` | `` (empty) | Fully qualified PLC STRING symbol (required for ADS) |
| `~ads_counter_symbol` | `` (empty) | Fully qualified PLC UDINT sequence symbol (required for ADS) |
| `~ads_timeout_ms` | `2000` | Timeout for each ADS request in milliseconds |
| `~ads_poll_interval` | `0.1` | Wall-clock seconds between ADS polls (positive) |
| `~ads_stale_timeout` | `5.0` | Wall-clock seconds without a fresh valid probe frame before STALE diagnostics |
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

## Linux / Beckhoff PLC over ADS (no Docker or USB passthrough)

This mode targets **ROS Noetic with Python 3**, normally Ubuntu 20.04. A standard
ROS Melodic/Python 2 environment cannot run this version of the node. Ubuntu 24.04
does not provide a standard ROS Noetic installation either. Noetic and Ubuntu
20.04 are legacy platforms; follow your site's support and network policies.

Connection path: probe -> EL6022 RS485 terminal -> CX9240 PLC -> Ethernet -> Linux/WSL ROS node.
The PLC must already have a program reading the serial terminal. ADS does not
configure the EL6022 or replace that program. This node reads symbols only: it
does not write PLC variables, download a program, stop the PLC, or create a route
on the PLC.

### Interface to give the PLC engineer

Expose these two ADS-readable symbols (names below are examples; actual names
are passed as launch arguments):

| Example symbol | PLC type | Contract |
|----------------|----------|----------|
| `GVL_Gamma.sRawMessage` | `STRING(80)` | One complete ASCII `$06,...*CCCC` probe frame, not WSTRING; CR/LF optional |
| `GVL_Gamma.nRxSequence` | `UDINT` | Odd during a STRING update; even when stable; advances by two for every complete received frame, even when readings are identical |

Use a single writer. Increment to odd **before** changing the STRING, then
increment to even **after** the complete STRING has been assigned. Do not advance
the sequence just because a PLC scan or timer fired. The node reads sequence,
STRING, sequence and accepts only matching even sequences. A counter incremented
only after assignment is insufficient to guard against a read during assignment.

Illustrative Structured Text, to be integrated by the PLC engineer into the
existing receiver (the `bNewCompleteFrame` pulse and `sCompletedFrame` come from
that receiver, not this ROS driver):

```iecst
(* GVL_Gamma declarations: non-retained, initial empty message / zero sequence *)
VAR_GLOBAL
    sRawMessage : STRING(80) := '';
    nRxSequence : UDINT := 0;
END_VAR
```

```iecst
IF bNewCompleteFrame THEN
    GVL_Gamma.nRxSequence := GVL_Gamma.nRxSequence + UDINT#1;
    GVL_Gamma.sRawMessage := sCompletedFrame;
    IF GVL_Gamma.nRxSequence = UDINT#4294967295 THEN
        GVL_Gamma.nRxSequence := UDINT#0;
    ELSE
        GVL_Gamma.nRxSequence := GVL_Gamma.nRxSequence + UDINT#1;
    END_IF
END_IF
```

The engineer must also supply the PLC IP, PLC AMS Net ID, runtime ADS port,
actual symbol names, and a return route for the Linux client's AMS Net ID.
Your PC's `172.31.1.89` address is **not** the PLC address. ADS port `851` is a
runtime identifier, not the TCP network port.

### Routing and WSL

- On Linux, pyads creates the client-side route when opening the connection.
  The engineer must configure the **PLC-side return route** to match
  `ads_local_ams_net_id` and the reachable client address.
- WSL 2 normally uses NAT. Its private Linux address is not automatically
  reachable from the PLC, and a Windows route is not automatically a Linux
  AdsLib route. Agree the return-route address and supported networking setup
  with the engineer. Native Linux or a supported mirrored WSL configuration
  may simplify this; do not assume Windows Ethernet connectivity proves WSL ADS
  connectivity.
- Allow the required ADS traffic through site-approved firewall rules (normally
  TCP 48898). Do not expose ADS to untrusted networks or disable firewalls.
- Choose a unique client AMS Net ID; it need not equal the client IP address.
  Never invent the PLC AMS Net ID from its IP.

See the [pyads routing documentation](https://pyads.readthedocs.io/en/latest/documentation/routing.html).

### Build and launch

In the Linux Noetic environment, install dependencies from the repository folder.
Python 3.8 uses pyads 3.3.9, which advertises Python 3.8 support; newer pyads releases
require newer Python. Build tools are needed for that release's bundled AdsLib.

```bash
sudo apt update
sudo apt install python3-pip python3-serial build-essential
python3 -m pip install -r requirements-ads.txt

source /opt/ros/noetic/setup.bash
cd ~/catkin_ws
catkin_make -DPYTHON_EXECUTABLE=/usr/bin/python3
source devel/setup.bash
```

The repository must be present in `~/catkin_ws/src/jcs_gamma_probe`, as a checkout
or symlink. Install pyads into the same Python environment that runs the node.
Replace **all** placeholders below with values agreed with the engineer:

```bash
roslaunch jcs_gamma_probe gamma_probe.launch \
    ads_host:=<PLC_IP> \
    ads_ams_net_id:=<PLC_AMS_NET_ID> \
    ads_local_ams_net_id:=<CLIENT_AMS_NET_ID> \
    ads_port:=851 \
    ads_message_symbol:=GVL_Gamma.sRawMessage \
    ads_counter_symbol:=GVL_Gamma.nRxSequence \
    verify_crc:=true
```

No serial bridge or USB adapter on the PC is needed. The existing Docker image
does not install the optional ADS dependency.

### Running four probes through one PLC

`gamma_probes_ads.launch` starts four independent probe nodes in namespaces
`/probe_1` … `/probe_4`, all reading the same PLC. Requirements:

- The PLC must expose **one STRING/UDINT symbol pair per probe**, each following
  the single-writer sequence contract above (e.g. `GVL_Gamma.sRawMessage1` /
  `GVL_Gamma.nRxSequence1` … `4`). Each pair must be written only from its own
  probe's receiver.
- Each node process runs its own AdsLib router, and AMS Net IDs must be unique
  per router. Agree **four distinct client AMS Net IDs** with the PLC engineer
  and have a **PLC-side return route for each one** (all four can point at the
  same client IP address).

```bash
roslaunch jcs_gamma_probe gamma_probes_ads.launch \
    ads_host:=<PLC_IP> \
    ads_ams_net_id:=<PLC_AMS_NET_ID> \
    probe1_local_ams_net_id:=<CLIENT_AMS_NET_ID_1> \
    probe1_message_symbol:=GVL_Gamma.sRawMessage1 \
    probe1_counter_symbol:=GVL_Gamma.nRxSequence1 \
    probe2_local_ams_net_id:=<CLIENT_AMS_NET_ID_2> \
    probe2_message_symbol:=GVL_Gamma.sRawMessage2 \
    probe2_counter_symbol:=GVL_Gamma.nRxSequence2 \
    probe3_local_ams_net_id:=<CLIENT_AMS_NET_ID_3> \
    probe3_message_symbol:=GVL_Gamma.sRawMessage3 \
    probe3_counter_symbol:=GVL_Gamma.nRxSequence3 \
    probe4_local_ams_net_id:=<CLIENT_AMS_NET_ID_4> \
    probe4_message_symbol:=GVL_Gamma.sRawMessage4 \
    probe4_counter_symbol:=GVL_Gamma.nRxSequence4 \
    verify_crc:=true
```

Alarm thresholds, timeouts and polling are shared launch arguments; edit the
launch file if a probe needs individual values. Each probe publishes under its
namespace, with message `frame_id` set to `gamma_probe_1` … `gamma_probe_4`:

```bash
rostopic echo /probe_1/gamma_probe/dose_rate
rostopic echo /probe_1/gamma_probe/diagnostics
rostopic echo /probe_2/gamma_probe/dose_rate
...
```

### Freshness, diagnostics and alarms

- At startup and reconnect, the current sequence is a baseline: the retained
  STRING is not published until a subsequent complete frame arrives.
- Unchanged sequences are not republished. New sequences with identical message
  text are fresh readings and are published.
- ADS errors publish ERROR diagnostics, close the connection and retry after
  five seconds. Invalid fresh frames publish the raw text and ERROR diagnostics.
- No fresh valid frame for `ads_stale_timeout` seconds produces STALE diagnostics.
  No synthetic dose or alarm-clear value is generated. The latched alarm holds
  its previous state (initially false); **false is not proof of safe conditions
  when data is stale**. Consumers must monitor diagnostics and topic freshness.
- Recovery resumes existing parsing, CRC checks, health reporting, threshold
  and hysteresis behavior. The ten-sample average resets on reconnect or stale data.
- This is a latest-value interface, not a queue: intermediate messages can be
  missed if the PLC updates faster than polling. The average covers ten received
  samples, not necessarily ten seconds.

From another sourced ROS terminal:

```bash
rostopic echo /gamma_probe/diagnostics
rostopic echo /gamma_probe/dose_rate
```

### Tests (no PLC or ROS master needed)

```bash
python3 -m unittest discover -s tests -v
```

## Hardware

- **Probe**: JCS RMS30-102ASx (9600 baud, 8N1, RS485)
- **Power**: 12V DC, 200mA minimum
- **Wiring**: Data A (+) → adapter A, Data B (-) → adapter B, shared GND
