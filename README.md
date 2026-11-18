# JCS Gamma Probe Driver

ROS driver for the **JCS RMS30-102ASx ASCII Gamma Probe** over RS485/USB serial.

## Overview

Reads dose rate from a John Caunt Scientific RMS30-102ASx gamma probe through serial, a raw TCP stream, or a Beckhoff PLC exposing the raw message through ADS. Publishes dose rate to ROS topics and raises an alarm when a configurable threshold is exceeded.

See the [technical report](docs/gamma_probe_driver_report.md) for the monitoring
roles, connection architecture, processing, browser rendering and qualification
boundaries.

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

CRC verification follows the **RMS30-102ASx data sheet, Issue 1.0 (August 2023)**,
Communications / Error checking sections. The shift/XOR implementation uses
polynomial `0x1021` and initialization `0x1D0F`, covering the ASCII bytes from `$`
through `*` inclusive, excluding the checksum and CR/LF. It matches the published
example `$06,0133,1111,000000000.0*96CE`. The former `0xFFFF` initialization in this
implementation did not match that example or captured probe frames. With
`verify_crc:=true`, the checksum must contain exactly four hexadecimal digits;
missing, malformed or mismatched checksums reject the frame without publishing dose.

## Files

| File | Purpose |
|------|---------|
| `nodes/gamma_probe_node.py` | ROS node — reads probe data (serial, TCP or ADS), publishes to ROS topics |
| `requirements-ads.txt` | Optional Python dependency for Linux ADS mode |
| `serial_bridge.py` | Windows utility — bridges COM port to TCP for Docker access |
| `plot_dose.py` | Windows utility — live dose rate plot with audible alarm |
| `nodes/dose_web.py` | Local browser plot of one to four ROS dose-rate topics |
| `plot.sh` | Linux host shortcut — starts the saved viewer and opens the default browser |
| `probe.sh` | Linux host shortcut — starts the driver, or rebuilds/recreates it with `rebuild` |
| `Dockerfile` | Builds a self-contained ROS Noetic container with serial, TCP and ADS dependencies |
| `entrypoint.sh` | Docker entrypoint script |
| `launch/gamma_probe.launch` | ROS launch file with configurable parameters |
| `launch/gamma_probes_ads.launch` | Launches four probe nodes reading one PLC over ADS |
| `launch/gamma_probes_shared_ads.launch` | Reads all four probes over one ADS connection and publishes four independent topic namespaces |
| `config/probes.yaml` | Per-probe display names, corrected-dose thresholds, hysteresis and calibration factors |
| `launch/gamma_probe_plot.launch` | Starts the dashboard with all four probe topics |

## ROS Topics

| Topic | Type | Description |
|-------|------|-------------|
| `~dose_rate` | `std_msgs/Float64` | Probe-reported dose multiplied by `calibration_factor`, in µSv/h |
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
| `~probe_name` | `Gamma Probe` | Human-readable dashboard name; does not rename ROS nodes/topics |
| `~calibration_factor` | `1.0` | Finite positive multiplier applied before publishing dose, averaging and alarm evaluation |
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

## Linux / Beckhoff PLC over ADS

This mode targets **ROS Noetic with Python 3**, normally Ubuntu 20.04. A standard
ROS Melodic/Python 2 environment cannot run this version of the node. Ubuntu 24.04
and 26.04 do not provide a standard ROS Noetic installation either; use the Docker
instructions below on those hosts. Noetic and Ubuntu 20.04 are legacy platforms;
the container does not change their support status. Follow your site's support
and network policies.

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

### Build and launch with Docker on Linux

The image includes ROS Noetic, pyserial, pyads and the build tools needed for
AdsLib. No host ROS installation, serial bridge or USB passthrough is needed.
From the repository directory:

```bash
sudo docker build -t jcs_gamma_probe .
sudo docker run --rm -it --network host --name gamma_probe_ads \
    jcs_gamma_probe \
    roslaunch jcs_gamma_probe gamma_probe.launch \
    ads_host:=<PLC_IP> \
    ads_ams_net_id:=<PLC_AMS_NET_ID> \
    ads_local_ams_net_id:=<CLIENT_AMS_NET_ID> \
    ads_port:=851 \
    ads_message_symbol:=GVL_Gamma.sRawMessage \
    ads_counter_symbol:=GVL_Gamma.nRxSequence \
    verify_crc:=true
```

Replace all placeholders with the agreed PLC settings. Linux host networking
lets AdsLib use the laptop's PLC-facing IP address, so the PLC return route must
point to that address, not a Docker bridge address. The PLC-side route must
permit incoming plain ADS; an enabled Unidirectional option has caused ADS
access-denied errors with AdsLib. Keep firewall access restricted to the client.
Do not run a second client process using the same client AMS Net ID concurrently.

In another terminal, monitor the running container without sourcing ROS on the
host:

```bash
sudo docker exec -it gamma_probe_ads /entrypoint.sh \
    rostopic echo /gamma_probe/dose_rate
sudo docker exec -it gamma_probe_ads /entrypoint.sh \
    rostopic echo /gamma_probe/diagnostics
```

Run each monitoring command separately. The entrypoint sources both ROS and the
catkin workspace; an ordinary `docker exec ... rostopic` does not do that.
Press Ctrl+C in the launch terminal to stop the driver. To stop it from another
terminal:

```bash
sudo docker stop gamma_probe_ads
```

For four probes, use the same `docker run` prefix with the
`gamma_probes_shared_ads.launch` command below. It reads connection settings
from YAML rather than requiring four client AMS Net IDs. Monitor topics using
`/probe_1/gamma_probe/...` through `/probe_4/gamma_probe/...`.

### Browser plot on Linux

Keep the ROS driver running. The viewer subscribes to its ROS topics; it does not
open another ADS connection or write to the PLC. Rebuild the image once to include
the viewer (an already-running driver container can stay on its existing image):

```bash
sudo docker build -t jcs_gamma_probe .
sudo docker create -it --network host --name gamma_probe_plot \
    jcs_gamma_probe rosrun jcs_gamma_probe dose_web.py
```

Create the named viewer container only once; if it already exists, skip that
step. Then, each time you want the plot, run this from the repository directory
on the laptop (not inside Docker and not with `sudo`):

```bash
./plot.sh
```

The shortcut uses `sudo` only to start the saved viewer, waits for its HTTP
endpoint, and opens **http://127.0.0.1:8080** in your default browser using
`xdg-open`. It requires host `curl` and `xdg-open` (provided by `xdg-utils`).
Closing the browser does not stop the viewer or driver. To stop the viewer:

```bash
sudo docker stop gamma_probe_plot
```

No host ROS installation, display forwarding, browser extensions or internet
connection for chart libraries is needed. A bare `docker start -ai` only starts
the web server; it does not open a host browser. For a custom viewer port, open
its URL manually instead of using the default-port shortcut.

For four probes, replace the viewer command with:

```bash
sudo docker create -it --network host --name gamma_probe_plot \
    jcs_gamma_probe roslaunch jcs_gamma_probe gamma_probe_plot.launch
```

The viewer subscribes to `dose_rate`, `dose_rate_avg`, `alarm` and `diagnostics`
in each configured driver's node namespace. Set `_topics` to that driver's
`dose_rate` topic. The dashboard always displays four probe panels in a two-column
desktop layout (one column on narrow screens), with an independent chart, dose,
average, alarm and health lights for each probe. Panels follow `_topics` order;
unassigned panels show **Not configured**, while assigned topics with no readings
show **Waiting for data**. Readings are never duplicated to fill an empty panel.
Connection details are collapsed by default, with a compact status footer.
Names come from each driver's `probe_name` parameter. Start the driver launch
before the viewer so its YAML parameters are available, even for probes that
are not connected yet. Custom topic lists remain supported via `rosrun` and
the `_topics` parameter.

Solid curves show instantaneous dose, dashed curves show the
driver's ten-reading average (not a separate browser calculation), and red dashed
lines show available `dose_threshold_usvh` parameters. The horizontal axis uses
local clock time (`HH:MM:SS`) in the browser's timezone.

Each probe has a visual driver-alarm indicator and four health lights: overload,
lifetime counts, HT fault and no counts. Green means a fresh OK flag; red means a
fresh fault; amber means unknown or stale. The overall healthy light requires
fresh dose data, fresh OK diagnostics, all four flags OK and a known inactive
driver alarm. Missing diagnostics never default to healthy.

The alarm follows the driver's instantaneous-dose threshold and hysteresis, not
the average. Its latched state remains visible when data goes stale, explicitly
marked as last known; lack of a new alarm transition is not itself a stale alarm.

The viewer binds only to localhost. Optional ROS private parameters are `_port`
(default `8080`) and `_stale_timeout` (default `5.0` seconds; match the driver's
stale timeout). It retains up to 300 readings per topic and plots those within the
last five minutes, starting when the viewer receives data. Missing or stale data
is never replaced with zero, and gaps longer than the stale timeout are not joined.
Connection failures are displayed explicitly.

This is a dose display, **not a safety alarm**. Green indicates reported status,
not independent proof of safe conditions; stale data cannot establish safety.

If the viewer stays at "Waiting for data", check the driver logs:

```bash
sudo docker logs --tail 30 gamma_probe_ads
```

With `verify_crc:=true`, CRC-mismatched frames are not published as dose readings.
If these errors persist, confirm the CRC parameters against the manufacturer's
protocol specification; do not treat an empty plot as a zero reading.

### Build and launch natively on ROS Noetic

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

No serial bridge or USB adapter on the PC is needed.

### Running four probes through one PLC

**Recommended: one shared ADS connection.** The verified PLC symbols are:

| ROS position | Probe name | Serial | Raw message | Sequence |
|--------------|------------|--------|-------------|----------|
| `probe_1` | Import Drum Probe | 0157 | `GVL_DoseProbes.sRawMessageA` | `GVL_DoseProbes.nRxSequenceA` |
| `probe_2` | LLW Drum Probe | 0158 | `GVL_DoseProbes.sRawMessageB` | `GVL_DoseProbes.nRxSequenceB` |
| `probe_3` | HDRI Drum Probe | 0155 | `GVL_DoseProbes.sRawMessageC` | `GVL_DoseProbes.nRxSequenceC` |
| `probe_4` | Fuel Drum Probe | 0156 | `GVL_DoseProbes.sRawMessageD` | `GVL_DoseProbes.nRxSequenceD` |

These four feeds were read live on 18 November 2026: all sequences advanced,
the sampled frames passed CRC, and all four reported health digits were `1111`.
This is a point-in-time communication check, not a calibration or safety check.

```bash
roslaunch jcs_gamma_probe gamma_probes_shared_ads.launch
```

The shared launch loads [`config/probes.yaml`](config/probes.yaml). The
`gamma_probes_ads.connection` section supplies the PLC endpoint, **one** client
AMS Net ID/return route, timeouts and polling interval. Each `probe_N.gamma_probe`
section supplies its symbol pair and independent name, factor, alarm settings
and CRC setting. To use another file, pass `probe_config:=/path/to/probes.yaml`.
Keep CRC verification enabled for all four probes.

One ROS node manages the single connection, but dose, average, alarm, raw message
and diagnostics remain separate under `/probe_1/gamma_probe` through
`/probe_4/gamma_probe`. Each probe has its own sequence baseline, last-valid-frame
time, averaging buffer and latched alarm. One stale feed or malformed probe frame
does not stop the other probes; a shared connection error marks all four as ERROR and reconnects.
No PLC variables are written. Do not run a second ADS driver using the same
client AMS Net ID at the same time.

#### Optional legacy mode: four independent driver nodes

`gamma_probes_ads.launch` starts four independent probe nodes in namespaces
`/probe_1` … `/probe_4`, all reading the same PLC. Requirements:

- The PLC must expose **one STRING/UDINT symbol pair per probe**, each following
  the single-writer sequence contract above. Each pair must be written only from its own
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
    probe1_message_symbol:=GVL_DoseProbes.sRawMessageA \
    probe1_counter_symbol:=GVL_DoseProbes.nRxSequenceA \
    probe2_local_ams_net_id:=<CLIENT_AMS_NET_ID_2> \
    probe2_message_symbol:=GVL_DoseProbes.sRawMessageB \
    probe2_counter_symbol:=GVL_DoseProbes.nRxSequenceB \
    probe3_local_ams_net_id:=<CLIENT_AMS_NET_ID_3> \
    probe3_message_symbol:=GVL_DoseProbes.sRawMessageC \
    probe3_counter_symbol:=GVL_DoseProbes.nRxSequenceC \
    probe4_local_ams_net_id:=<CLIENT_AMS_NET_ID_4> \
    probe4_message_symbol:=GVL_DoseProbes.sRawMessageD \
    probe4_counter_symbol:=GVL_DoseProbes.nRxSequenceD \
    verify_crc:=true
```

Names, calibration factors and individual alarm settings are loaded from
[`config/probes.yaml`](config/probes.yaml) by default. A different file can be
selected with `probe_config:=/path/to/probes.yaml`. YAML values override the
shared alarm launch arguments and symbol pairs; use `probe_config:=""` to disable
YAML and retain the launch arguments. In this legacy mode, connection settings,
timeouts and polling remain launch arguments; `gamma_probes_ads.connection` is
used only by the shared launch. Each probe publishes under its
namespace, with message `frame_id` set to `gamma_probe_1` … `gamma_probe_4`:

```bash
rostopic echo /probe_1/gamma_probe/dose_rate
rostopic echo /probe_1/gamma_probe/diagnostics
rostopic echo /probe_2/gamma_probe/dose_rate
...
```

### Per-probe YAML configuration and calibration

Edit [`config/probes.yaml`](config/probes.yaml), not the Python or launch files.
The initial configuration is:

| ROS position | Display name | Threshold (µSv/h) | Software factor |
|--------------|--------------|------------------|-----------------|
| `probe_1` | Import Drum Probe | 150.0 | 1.0 |
| `probe_2` | LLW Drum Probe | 150.0 | 1.0 |
| `probe_3` | HDRI Drum Probe | 150.0 | 1.0 |
| `probe_4` | Fuel Drum Probe | 150.0 | 1.0 |

For example, the first entry is:

```yaml
probe_1:
  gamma_probe:
    ads_message_symbol: GVL_DoseProbes.sRawMessageA
    ads_counter_symbol: GVL_DoseProbes.nRxSequenceA
    verify_crc: true
    frame_id: gamma_probe_1
    probe_name: Import Drum Probe
    dose_threshold_usvh: 150.0
    alarm_hysteresis_usvh: 1.0
    calibration_factor: 1.0
```

Change values independently under each position. Keep the `probe_1` … `probe_4`
and `gamma_probe` keys unchanged: those identify the ROS namespaces, not the
editable labels. Display names must be non-empty strings. Factors must be finite
positive numbers; thresholds and hysteresis must be finite non-negative numbers.
Invalid values fail startup explicitly. The supplied thresholds preserve the old
default; they are **not a recommendation of safe operating limits**.

The processing order is:

```text
CRC/parse -> probe-reported dose x factor -> dose_rate
                                        -> ten-reading average
                                        -> threshold/hysteresis alarm
                                        -> dose diagnostics
```

Threshold and hysteresis values are in **corrected µSv/h**; they are not multiplied
by the factor. A factor of `1.0` leaves the dose unchanged. Raw ASCII messages,
serial numbers and all four hardware health flags remain unchanged. Diagnostics
also report the applied name, factor and threshold.

**What calibration means here.** The manufacturer's RMS30-102ASx datasheet
(Issue 1.0, August 2023) says the ASCII dose field is already in µSv/h, not counts.
Its typical sensitivity of 0.70 cps per µSv/h is therefore **not** another
conversion to apply to this field. The datasheet specifies a dose-rate range of
3 µSv/h to 100 mSv/h and energy response of 60 keV to 1.25 MeV. It gives
linearity/statistical specifications but no individual calibration coefficients
or calibration-adjustment procedure.

This YAML factor is an additional software correction, **not hardware calibration
or certification**. Obtain each probe's calibration certificate and any justified
correction from the manufacturer or a qualified calibration provider. Where an
approved comparison supports a multiplicative correction, its arithmetic is
`factor = reference dose / probe-reported dose`; for example, 100 / 80 = 1.25.
Do not derive factors from zero/near-zero background readings or assume a single
factor corrects energy dependence, nonlinearity or overload. Leave it at `1.0`
unless there is a documented basis for changing it.

**Short Docker commands.** From the repository directory, run this once to
build/update the image, stop the viewer/driver, recreate only the driver with
the read-only YAML mount, and start it:

```bash
./probe.sh rebuild
```

This interrupts monitoring. A failed build leaves the existing containers
untouched. The saved viewer is kept. If you have never created the viewer,
create it once in another terminal:

```bash
sudo docker create -it --network host --name gamma_probe_plot \
    jcs_gamma_probe roslaunch jcs_gamma_probe gamma_probe_plot.launch
```

For everyday use, no rebuild or recreation is needed:

```bash
./probe.sh
```

Once the driver has initialized, run `./plot.sh` in another terminal to open the
dashboard. Both driver commands attach to its logs; Ctrl+C stops the driver.
The driver shortcut resolves paths relative to its own location, so it can also
be called by its full path from another directory.

Each panel
must receive its own fresh readings and health diagnostics before it can show
healthy operation. Missing or disconnected probes remain unknown/stale rather
than displaying synthetic zero readings. The shared driver uses the one existing
PLC return route; three additional routes are not needed.

The directory is mounted read-only into the container (mounting the directory
also accommodates editors that replace files on save). Later edits need no
image rebuild or container recreation. Stop the viewer, restart the driver to
reload YAML, then start the viewer after driver initialization:

```bash
sudo docker stop gamma_probe_plot
sudo docker restart gamma_probe_ads
# Once the driver has initialized:
./plot.sh
```

The viewer restart also clears history collected under the previous factor.
Settings are startup-only; changing the file or ROS parameters alone does not
reconfigure a running driver. Native single-probe launches can use the same
file with `probe_namespace:=probe_1 probe_config:=/absolute/path/to/probes.yaml`.
Without a config file or namespace argument, the single-probe launch retains
its legacy topics and a factor of `1.0`.

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

Tests require PyYAML (`python3-yaml`, also included with ROS Noetic).

```bash
python3 -m unittest discover -s tests -v
```

## Hardware

- **Probe**: JCS RMS30-102ASx (9600 baud, 8N1, RS485)
- **Power**: 12V DC, 200mA minimum
- **Wiring**: Data A (+) → adapter A, Data B (-) → adapter B, shared GND
