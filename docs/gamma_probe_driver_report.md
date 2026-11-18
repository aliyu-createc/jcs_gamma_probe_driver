# Four-Probe Gamma Dose-Rate Monitoring System

## Technical Description, Communications Architecture and Web Visualisation

| Document control | Details |
|---|---|
| Issue | 1.0 |
| Date | 18 November 2026 |
| System | JCS RMS30-102ASx gamma probe driver and four-probe dashboard |
| Software package | `jcs_gamma_probe` |
| Document purpose | Describe the implemented system, intended operational uses, connection methods, processing and browser presentation |
| Status | Engineering description; not a safety case, calibration certificate or transport-compliance approval |

## Executive summary

The system acquires gamma dose-rate measurements from four JCS RMS30-102ASx
probes, processes each probe independently and presents the results in a local
web dashboard. Its intended applications are:

- Input-tray dose-rate screening before waste enters the X-ray system and passes
  over the GeGI imager.
- Dose-rate screening of LLW drums against the criteria established for transport.
- Equivalent drum-monitoring functions at the HDRI and Fuel drum positions.

The driver supports direct serial acquisition, a serial-to-TCP bridge and
Beckhoff Automation Device Specification (ADS) communications. The preferred
four-probe installation uses one ADS connection to read four independent
message/sequence pairs in the PLC global variable list `GVL_DoseProbes`.
Each probe retains its own name, calibration factor, threshold, averaging
buffer, alarm state and ROS topic namespace.

The browser does not communicate with the PLC. A separate ROS subscriber
collects the driver's outputs, serves a local HTTP interface and supplies JSON
data to a JavaScript dashboard. The dashboard renders four charts directly
using HTML Canvas, without an external plotting service or chart library.

Functional checks have demonstrated four live PLC feeds, four ROS output
namespaces and four populated browser panels. The automated test suite contains
72 passing tests at the date of this report. These results demonstrate software
functionality, not radiological calibration, validated waste acceptance or
regulatory compliance.

**The implementation is a monitoring and indication system. It does not issue
machine permits, inhibit equipment, stop a conveyor or enforce a safety interlock.**

## 1. Operational purpose and measurement interpretation

### 1.1 Probe duties

| Monitoring position | Current dashboard name | Intended operational purpose |
|---|---|---|
| Input tray | Import Drum Probe | Provide the gamma dose-rate indication used to assess whether waste is within the approved acceptance envelope before entering the X-ray machine and passing over the GeGI imager |
| LLW drum station | LLW Drum Probe | Support drum dose-rate assessment against the applicable, approved transport-screening criteria |
| HDRI drum station | HDRI Drum Probe | Provide an equivalent dose-rate monitoring function for the HDRI drum position |
| Fuel drum station | Fuel Drum Probe | Provide an equivalent dose-rate monitoring function for the Fuel drum position |

The user's input-tray probe is currently labelled **Import Drum Probe** in
configuration. This report uses "input-tray probe" for its operational role;
the existing display name has not been changed.

At the input tray, the measurement is intended to inform an acceptance decision
before the next imaging operations. At the three drum positions, it is intended
to inform the assessment of the drum's external radiation field. In both cases,
the approved criterion, measurement geometry and decision procedure must be
defined by the responsible engineering and radiation-protection personnel.

### 1.2 Dose rate is not accumulated dose or a complete drum assessment

The published quantity is an indicated **gamma dose rate in microsieverts per
hour**, written `uSv/h` in software parameter names and `µSv/h` on the dashboard.
It is a rate at the detector's measurement position:

- It is not accumulated dose in microsieverts.
- It is not a measurement of the total radioactive inventory or activity of a drum.
- It does not, by itself, establish the maximum dose rate at every position around
  a package or at a prescribed assessment distance.
- It does not determine waste classification or complete transport compliance.

Consequently, the expression "drum total dose rate" should be replaced in
operating documents by the particular dose-rate quantity and measurement
position used by the approved assessment procedure.

Transport acceptance can depend on package classification, measurement geometry,
the applicable jurisdiction and other requirements beyond a single dose-rate
reading. No applicable regulatory limits or approved machine-acceptance limits
have been supplied for this implementation.

**The configured value of 150 µSv/h is a retained software default, not an
approved transport limit or a demonstrated X-ray/GeGI acceptance limit.**

## 2. System architecture

### 2.1 Preferred four-probe data path

```text
RMS30 probe A -- independent RS485 receive channel --+
RMS30 probe B -- independent RS485 receive channel --+
RMS30 probe C -- independent RS485 receive channel --+--> Beckhoff PLC
RMS30 probe D -- independent RS485 receive channel --+    GVL_DoseProbes
                                                           |
                                                One read-only ADS connection
                                                           |
                                              ROS node /gamma_probes_ads
                                                           |
                                  Four independent ROS topic namespaces
                                                           |
                                         ROS subscriber: dose_web.py
                                                           |
                                      Local HTTP server and JSON history
                                                           |
                                       Browser JavaScript + HTML Canvas
                                                           |
                                 Four dose/average charts and status panels
```

The PLC performs serial reception and publishes complete probe frames into
ADS-readable variables. The PC driver does not configure the PLC serial
terminals or replace the PLC receiver program.

### 2.2 Functional layers

| Layer | Responsibility |
|---|---|
| Probe | Detect gamma radiation and transmit the instrument's dose-rate indication and health flags |
| Physical interface | Carry the RS485 serial data through an adapter or PLC serial terminal |
| PLC interface, where used | Make complete frames available with an independently advancing sequence number for each probe |
| Driver | Check frames, apply the software factor, calculate averages, evaluate alarms and publish diagnostics |
| ROS | Distribute independent measurement, alarm and diagnostic streams |
| Web backend | Subscribe to ROS, retain bounded in-memory histories and serve HTTP/JSON |
| Browser | Render charts, metrics, health indicators and connection/freshness states |

The preferred shared-ADS launch uses **one ROS acquisition node**, not four
independent ADS processes. Independence is maintained through per-probe state
and topic namespaces.

## 3. Probe communications and frame integrity

### 3.1 Instrument interface

The manufacturer describes an automatically transmitted ASCII output at
approximately one frame per second. Host request commands are not needed to
obtain the normal measurement stream.

| Item | Interface characteristic |
|---|---|
| Electrical interface | RS485 |
| Baud rate | 9600 baud |
| Serial format | 8 data bits, no parity, 1 stop bit |
| Nominal transmission interval | 1 second |
| Dose field | Already expressed in µSv/h |
| Manufacturer's stated dose-rate range | 3 µSv/h to 100 mSv/h |
| Manufacturer's stated energy response | 60 keV to 1.25 MeV |

The range and energy-response statements are from the RMS30-102ASx datasheet,
Issue 1.0, August 2023. They are not a substitute for the calibration certificate
of each installed instrument. A reported zero or a reading below the stated
range must not be interpreted as proof that no radiation is present.

### 3.2 ASCII frame

```text
$06,SSSS,HHHH,DDDDDDDDD.D*CCCC
```

| Field | Meaning |
|---|---|
| `$` | Start of frame |
| `06` | Data-message command identifier |
| `SSSS` | Reported device serial number |
| `HHHH` | Four probe-health indicators |
| `DDDDDDDDD.D` | Probe-reported dose rate in µSv/h |
| `*` | End of payload and checksum delimiter |
| `CCCC` | Four hexadecimal CRC characters |

The four health indicators represent overload, lifetime counts, high-tension
fault and no-counts status. The protocol defines `1` as normal/OK and `0` as a
fault or warning. The decoder reports a non-`1` health character as a fault.

| Health indicator | Interpretation |
|---|---|
| Overload | The probe reports an overload condition; the displayed dose must not be assumed to quantify an out-of-range field correctly |
| Lifetime counts | The probe reports its cumulative detector-life warning |
| HT fault | The probe reports an internal high-tension supply fault |
| No counts | The probe reports its internal no-counts warning; this is distinct from a network or ADS reception timeout |

### 3.3 CRC verification

The driver implements the manufacturer's verified frame checksum using:

- Polynomial `0x1021`.
- Initial value `0x1D0F` for the implemented shift/XOR algorithm.
- ASCII bytes from `$` through `*`, inclusive.
- Exclusion of the checksum characters and trailing CR/LF.

The published manufacturer example
`$06,0133,1111,000000000.0*96CE` is included in regression testing.
With verification enabled, a missing, malformed or mismatched checksum prevents
the frame from becoming a published dose reading.

CRC verification is enabled for all four probes in the supplied YAML.
Legacy single-probe defaults permit it to be disabled, so commissioning another
connection method must explicitly confirm that verification is enabled.

Raw input is published separately before parsing and CRC checks. This assists
troubleshooting without treating a rejected frame as a valid dose measurement.

## 4. Supported connection methods

### 4.1 Method A: direct serial acquisition

```text
Probe -> RS485-to-USB adapter -> operating-system serial device -> ROS driver
```

The driver opens a device such as `/dev/ttyUSB0` using Python `pyserial`.
The serial port and baud rate are launch parameters. Where the driver is
containerised, the serial device must also be made available to the container
with appropriate device permissions; this is unnecessary for the ADS path.

An illustrative native ROS launch is:

```bash
roslaunch jcs_gamma_probe gamma_probe.launch \
    port:=/dev/ttyUSB0 verify_crc:=true
```

This mode operates one probe per driver instance. Four direct serial probes
would require four separately configured instances and physical interfaces.

**Framing qualification:** the current direct-serial driver uses newline-based
`readline()` with a five-second timeout. The probe may produce CR-only endings.
CR-only framing therefore requires specific commissioning; the ADS path must
not be taken as evidence that direct-serial framing has also been qualified.

### 4.2 Method B: serial-to-TCP bridge

```text
Probe -> Windows COM port -> serial_bridge.py -> TCP stream -> ROS driver
```

This method allows a ROS container to consume data from a Windows serial port.
The supplied bridge defaults to `COM6`, 9600 baud and TCP port `3241`.
It reads serial data through a carriage return and appends a newline before
forwarding it, providing the line termination expected by the TCP reader.

For Docker Desktop on Windows, the driver can connect using:

```bash
roslaunch jcs_gamma_probe gamma_probe.launch \
    tcp_host:=host.docker.internal tcp_port:=3241 verify_crc:=true
```

The bridge's port settings are constants in the supplied Python utility, not
command-line options. One COM port and one actively serviced TCP connection are
handled by that utility.

The bridge itself supports traffic in both directions. Although this driver
does not transmit probe commands, bytes sent by another TCP client could be
forwarded to the serial port. The bridge binds to all host interfaces and
provides no application authentication or TLS; access must therefore be
restricted by the approved network configuration.

The serial/TCP paths log connection and read problems and retry failed connection
attempts. They do not have the PLC sequence-number contract described below.
TCP EOF/reconnection behaviour and serial framing require their own commissioning.
The browser still independently detects aged or missing readings.

### 4.3 Method C: one probe over PLC ADS

```text
Probe -> PLC serial receiver -> message/sequence symbols -> ADS -> ROS driver
```

The driver uses `pyads` and AdsLib to read one complete ASCII message and its
sequence counter. This path requires:

1. A working PLC serial receiver.
2. The PLC IP address and AMS Net ID.
3. The runtime ADS port.
4. The actual message and sequence symbol names.
5. A client AMS Net ID and matching PLC-side return route.
6. Site-approved network access to the ADS transport.

An AMS Net ID is a logical ADS routing identifier. It is not interchangeable
with an IP address. ADS runtime port `851` is also distinct from TCP port
`48898`, which carries the network transport used by this installation.

Earlier operation used `GVL_Gamma.sRawMessage` and `GVL_Gamma.nRxSequence`.
Those were the initial single-probe symbols; the configured four-probe system
now uses `GVL_DoseProbes`.

### 4.4 Method D: four probes over one shared ADS connection

This is the preferred current configuration:

```bash
roslaunch jcs_gamma_probe gamma_probes_shared_ads.launch
```

The shared driver reads all four symbol pairs using the existing single client
identity and return route. It does not open four competing ADS connections.
Each channel has an independent baseline, freshness timer, dose buffer,
threshold, factor and alarm state.

The complete symbol names are `GVL_DoseProbes.` followed by the fields below:

| Channel | ROS position | Serial observed | Message field | Sequence field |
|---|---|---|---|---|
| A | `probe_1` | 0157 | `sRawMessageA` | `nRxSequenceA` |
| B | `probe_2` | 0158 | `sRawMessageB` | `nRxSequenceB` |
| C | `probe_3` | 0155 | `sRawMessageC` | `nRxSequenceC` |
| D | `probe_4` | 0156 | `sRawMessageD` | `nRxSequenceD` |

These are configured symbol-to-position assignments. The software reports
device serial numbers but does not enforce a separate expected-serial lock.
The mapping should be checked after instrument replacement or rewiring.

### 4.5 Optional legacy mode: four independent ADS nodes

The retained `gamma_probes_ads.launch` starts four independent driver processes.
Because each process runs its own AdsLib router, that arrangement requires four
distinct client AMS Net IDs and corresponding PLC-side return routes.

It remains available for installations needing process separation. It is not
required by the current shared-connection design. Separate clients must not
reuse the shared driver's AMS identity concurrently.

### 4.6 Current network settings

| Setting | Configured value |
|---|---|
| PLC IP address | `172.31.1.100` |
| PLC AMS Net ID | `5.176.89.72.1.1` |
| Client AMS Net ID | `172.31.1.89.1.1` |
| Client address associated with the existing route | `172.31.1.89` |
| ADS runtime port | `851` |
| ADS TCP transport | `48898` |
| ADS request timeout | 2000 ms |
| Poll interval | 0.1 s |
| ADS stale-data timeout | 5.0 s |

Routing, permissions and firewall access must all agree. Reachable Ethernet or
a matching Net ID alone does not establish authorised ADS access. The current
driver uses plain ADS, not Secure ADS; it should remain on an appropriately
controlled network.

## 5. PLC consistency, freshness and failure handling

### 5.1 Message/sequence contract

Each probe's PLC interface consists of a `STRING(80)` message and `UDINT` counter.
One PLC writer must:

1. Increment the counter to an odd value before changing the message.
2. Assign one complete received probe frame.
3. Increment the counter again to an even value after the assignment.

The PC reads:

```text
sequence before -> raw message -> sequence after
```

The snapshot is accepted only when the sequence values match and are even.
This rejects reads occurring during a PLC update. The counter must advance
for every newly received complete frame, including a frame whose text is
identical to the previous one.

### 5.2 New data versus retained data

At startup and after reconnection, each current sequence becomes a baseline.
A subsequent changed, stable sequence is required before the driver publishes
a dose. The retained PLC string is therefore not presented as a fresh reading
simply because the connection has opened.

The interface holds the latest frame; it is not a lossless queue. Intermediate
frames can be missed if reception outpaces reading. Polling at 0.1 s does not
increase the instrument's nominal one-second measurement rate.

### 5.3 Per-channel and shared failures

| Condition | Implemented ADS response |
|---|---|
| Odd or changing sequence | Discard that snapshot and retry on subsequent polls |
| Unchanged sequence | Do not republish a duplicate measurement |
| Fresh frame fails parsing or CRC | Preserve raw input, publish ERROR diagnostics and do not refresh last-valid time |
| No fresh valid frame for 5 s | Publish STALE diagnostics and clear that probe's averaging buffer |
| Valid data returns | Resume processing; an average cleared by staleness starts again from fresh samples |
| Shared ADS connection/read failure | Publish ERROR diagnostics for all four channels, close the connection and retry after five seconds |
| Reconnection | Establish new per-probe baselines and clear averaging buffers |

Communication loss does not manufacture a zero reading or clear an existing
active alarm. A false alarm value at startup or during stale data is not proof
that an acceptance criterion is satisfied.

The PLC also exposes communication flags, including stale-data, receive-timeout,
serial-error and rejected-frame indicators. The present driver does not subscribe
to those additional flags: its PLC freshness checks use the sequence contract
and successfully processed frames. They must not be confused with the four
instrument health indicators displayed in the dashboard.

## 6. Measurement processing, calibration and alarms

### 6.1 Processing sequence

```text
Raw frame -> preserve raw input -> parse and CRC check
                                      |
                         apply per-probe software factor
                                      |
                        +-------------+--------------+
                        |             |              |
                  instantaneous   rolling mean   threshold with
                   dose output    of up to 10     hysteresis
                                    samples          |
                        +-------------+--------------+
                                      |
                         measurement/health diagnostics
```

Only the selected probe's buffer and alarm are updated by its accepted frame.
The viewer neither recalibrates measurements nor independently recomputes the
driver's mean or alarm.

### 6.2 Software calibration factor

For probe `i`:

```text
corrected dose rate[i] = probe-reported dose rate[i] x calibration_factor[i]
```

The factor is dimensionless, finite and strictly positive. Its default is `1.0`,
which leaves the indicated dose unchanged. Corrected values are used consistently
for the instantaneous output, average, threshold decision and dose diagnostics.
Non-finite corrected results are rejected and logged.

The instrument already outputs µSv/h. Its typical counts-per-second sensitivity
is not an additional conversion to apply to that field. The software multiplier
is an additional correction and does not change the instrument's internal
calibration or its hardware health/overload thresholds.

Where an approved calibration assessment supports a multiplicative correction,
the arithmetic is reference dose rate divided by probe-reported dose rate.
The basis and uncertainty must come from the instrument's calibration evidence,
not an arbitrary adjustment or a zero/near-zero background reading. A single
multiplier cannot establish accuracy across all energies, geometries or overload
conditions. No factory coefficients or calibration certificates are stored by
this driver.

### 6.3 Rolling average

Each probe has a ten-sample rolling buffer. The output is the arithmetic mean
of the available accepted samples, using fewer than ten during initial filling.
At nominal one-second sampling it represents approximately ten seconds, but
it is sample-based rather than a guaranteed time-weighted ten-second mean.

### 6.4 Alarm evaluation

Let `D` be corrected instantaneous dose rate, `T` the threshold and `H` the
hysteresis, all dose-rate quantities being in µSv/h:

- An inactive alarm activates when `D >= T`.
- An active alarm clears only when `D < T - H`.
- Between those conditions the previous state is retained.

The alarm acts on the **instantaneous corrected reading**, not the mean.
With the current defaults of `T = 150` and `H = 1`, activation occurs at or above
150 µSv/h and clearance below 149 µSv/h.

The ROS alarm publisher is latched so late subscribers receive its latest state.
This is not a manually acknowledged alarm latch: normal readings below the
clearance boundary can clear it automatically. No alarm acknowledgement,
operator audit trail or certified annunciator is implemented.

### 6.5 Health versus dose acceptability

A probe can report all four hardware health flags as OK while measuring above
the configured threshold. Healthy electronics and a dose-rate criterion being
met are different conditions. The driver reports a diagnostic warning for a
hardware flag fault or an active dose alarm.

## 7. Configuration and ROS interfaces

### 7.1 YAML configuration

The shared launch loads [config/probes.yaml](../config/probes.yaml) into the ROS
parameter server. Common connection settings sit under
`gamma_probes_ads.connection`; each probe's settings sit under
`probe_N.gamma_probe`.

An abbreviated example is:

```yaml
gamma_probes_ads:
  connection:
    ads_host: "172.31.1.100"
    ads_ams_net_id: "5.176.89.72.1.1"
    ads_local_ams_net_id: "172.31.1.89.1.1"
    ads_port: 851
    ads_timeout_ms: 2000
    ads_poll_interval: 0.1
    ads_stale_timeout: 5.0

probe_1:
  gamma_probe:
    ads_message_symbol: GVL_DoseProbes.sRawMessageA
    ads_counter_symbol: GVL_DoseProbes.nRxSequenceA
    verify_crc: true
    probe_name: Import Drum Probe
    dose_threshold_usvh: 150.0
    alarm_hysteresis_usvh: 1.0
    calibration_factor: 1.0
```

Display names may be edited without renaming ROS interfaces. Namespace keys
identify the channels and should not be casually changed. Shared connection
settings are validated, and duplicated per-probe message or counter symbols
are rejected at startup.

Settings are read at startup, not hot-reloaded. Restart the driver after changes
and restart the viewer after driver initialisation to refresh its metadata
and remove chart history collected under the previous configuration.

### 7.2 Published topics

Each channel publishes these topics under `/probe_N/gamma_probe/`:

| Suffix | ROS type | Content |
|---|---|---|
| `dose_rate` | `std_msgs/Float64` | Corrected instantaneous dose rate |
| `dose_rate_avg` | `std_msgs/Float64` | Driver's rolling mean |
| `alarm` | `std_msgs/Bool` | Latest threshold/hysteresis state; latched |
| `diagnostics` | `diagnostic_msgs/DiagnosticStatus` | Health, status, instrument identity and applied processing metadata |
| `raw_message` | `std_msgs/String` | Received raw text, including rejected input |

For example, `/probe_2/gamma_probe/dose_rate` belongs to the LLW Drum Probe.
ROS names remain stable even if its display label changes.

These messages do not provide a coordinated, hardware-stamped four-probe
acquisition time. A configured `frame_id` parameter does not make the primitive
Float64/Bool/String messages stamped messages.

## 8. From ROS messages to the browser

### 8.1 Web backend

[nodes/dose_web.py](../nodes/dose_web.py) is a separate ROS node. For each
configured probe it subscribes to dose rate, driver average, alarm and
diagnostics. It makes no ADS connection and sends no commands to the PLC.

Its responsibilities are:

1. Maintain separate, lock-protected dose and average histories.
2. Retain up to 300 samples per curve per probe.
3. Record arrival times relative to a monotonic clock.
4. Retain the latest alarm and diagnostic status.
5. Read the probe names and threshold metadata from ROS parameters at startup.
6. Serve the dashboard page and JSON snapshots.

History is held only in memory. Restarting the viewer loses that history.
ROS raw-message publication and container logs do not constitute a purpose-built,
durable radiological measurement archive.

### 8.2 HTTP interface

| Endpoint | Function |
|---|---|
| `http://127.0.0.1:8080/` | Serve the HTML, CSS and JavaScript dashboard |
| `http://127.0.0.1:8080/api/data` | Return the current per-probe histories, ages, alarm state, threshold and diagnostic flags as JSON |

The backend uses Python's standard-library threaded HTTP server. Responses
disable caching, and JSON serialisation does not permit NaN or infinity.
The HTTP handler exposes the defined endpoints, not an arbitrary project-file
browser. Content-security and content-type headers are also set.

Binding to `127.0.0.1` makes the viewer local to the host in the Linux
host-network deployment. This is not an authenticated or TLS-protected remote
web application; network publication beyond that arrangement would require a
separately designed deployment.

### 8.3 Browser data updates

[web/dose_plot.html](../web/dose_plot.html) creates four persistent probe cards.
JavaScript requests `/api/data`, updates the display and schedules another
request 500 ms after completion. Requests have a three-second timeout.
This is HTTP polling, not a WebSocket or direct browser-to-ROS connection.

An independent 500 ms render timer advances displayed ages even while a request
is delayed. A frozen request therefore cannot indefinitely preserve a green
health display.

Names and other labels are inserted as text. No external fonts, charting CDN
or internet-hosted rendering service is required.

### 8.4 Chart rendering

Each card has its own HTML Canvas and two-dimensional drawing context. On
render, JavaScript:

1. Sizes the drawing surface for the card and the display's device-pixel ratio.
2. Selects points within the latest 300-second visible window.
3. Calculates horizontal time and vertical dose-rate coordinates.
4. Scales the vertical axis using visible readings and the threshold.
5. Draws grid lines, numeric labels and the local-time axis.
6. Draws the instantaneous-dose curve in solid teal.
7. Draws the driver's average in dashed purple.
8. Draws the available threshold as a dashed red horizontal line.

Samples separated by more than the stale timeout are not joined by a continuous
curve. At nominal 1 Hz, the 300-point history represents approximately five
minutes; higher input rates can shorten the retained time span.

Horizontal labels use normal browser-local `HH:MM:SS` time. The backend supplies
an epoch start time and elapsed arrival times, which are combined for display.
These are viewer-arrival timestamps, not independently synchronised detector or
PLC timestamps.

The dose and mean are formatted to three decimal places. That display formatting
does not establish three-decimal-place measurement accuracy.

### 8.5 Status presentation

The dashboard uses a two-by-two desktop layout and a single column on narrow
screens. Each card includes the name, serial number, dose, mean, age, threshold,
alarm, chart and four hardware-health indicators. Connection details are
collapsed by default.

The overall **Healthy** state requires:

- Fresh dose data.
- Fresh diagnostics at OK level.
- All four health flags explicitly OK.
- A known inactive driver alarm.
- A functioning viewer connection.

A missing or stale value does not become zero. An unassigned position is shown
as not configured; an assigned topic without measurements waits for data.
Historical values can remain visible but are marked stale. Last-known active
alarms remain prominent when freshness is lost.

The header separately counts receiving channels, healthy channels and driver
alarms. The browser alarm is visual; no browser sound is implemented.

### 8.6 Relationship to the earlier standalone plot

The repository also contains [plot_dose.py](../plot_dose.py), a Windows-specific
COM-port/Matplotlib utility. It bypasses ROS, uses its own average-based alarm
and can sound a Windows beep. It does not provide the same CRC/health/configuration
pipeline as the four-probe driver. It should not be confused with the current
web dashboard or used simultaneously with another program owning the same COM
port.

## 9. Deployment and routine operation

The Docker image packages ROS Noetic, the catkin workspace, `pyserial`, `pyads`
and the driver/viewer resources. The entrypoint sources ROS and the workspace
before executing the selected launch command. Linux host networking supports
the current ADS return-route address and ROS communications.

The host can therefore run the containers without a native ROS Noetic
installation. Containerisation does not change the legacy support status of
ROS Noetic or remove the need for a maintained, site-approved deployment.

| Task | Host command | Effect |
|---|---|---|
| Build/update and recreate the driver | `./probe.sh rebuild` | Build first, stop existing viewer/driver, replace only the driver container, mount the configuration read-only, then start and attach |
| Normal saved-driver startup | `./probe.sh` | Start and attach without rebuilding or recreating |
| Open the dashboard | `./plot.sh` | Start the saved viewer, wait for HTTP readiness and open the host's default browser |

Run the dashboard command in another terminal once the driver has initialised.
Ctrl+C in the attached driver terminal stops the driver. The rebuild shortcut
leaves existing containers untouched if the image build fails and retains the
saved viewer container. A viewer container must have been created once as
described in the [operating instructions](../README.md#per-probe-yaml-configuration-and-calibration).

The configuration directory is mounted read-only into the driver container.
Normal YAML edits do not require a new image; code changes do. Rebuilding an
image alone never updates an existing saved container.

ROS communication also requires the ROS master and negotiated topic connections;
the browser's HTTP port is not a replacement for those ROS connections.

## 10. Verification evidence and qualification limits

| Evidence | Result and scope |
|---|---|
| Automated tests, 18 November 2026 | 72 tests passed using `python3 -m unittest discover -s tests -q` |
| PLC symbol discovery | Confirmed four `sRawMessageA` through `D` STRING fields and four `nRxSequenceA` through `D` UDINT fields |
| Direct read-only PLC check | All four counters advanced; sampled frames passed CRC and carried four distinct serial numbers |
| Bounded shared-driver hardware check | Eight accepted frames per probe over exactly one physical ADS connection; driver outputs were captured using test publishers |
| Live ROS/web observation, 18 November 2026, approximately 12:09 UTC | Four dose topics were published by `/gamma_probes_ads`; the HTTP API contained the expected four serial numbers with sub-second sample ages at that observation |
| Browser observation during report preparation | Four populated panels and four Canvas charts; the browser displayed active threshold alarms during the check |
| Earlier browser layout checks | Desktop and narrow-screen layouts checked at 1440, 375 and 320 px widths; synthetic healthy, alarm, fault and stale cases exercised |

The software tests cover parsing, CRC, corrected measurements, averaging,
hysteresis, retained-frame suppression, shared-connection isolation, staleness,
reconnection, web history, HTTP responses and launcher failure handling.

The browser's alarm observation is an indication of what the application
reported at that time, not an independently verified radiation survey or an
approved assessment of the material. Hardware health flags being OK do not
negate a dose alarm.

The following are **not established** by these functional checks:

- Traceable calibration or uncertainty for the installed probes.
- Approved input-tray or drum acceptance thresholds.
- A validated geometry for assessing a complete waste item or drum.
- Compliance with any particular transport regulation.
- Safety integrity, deterministic response time or machine-interlock performance.
- Long-duration availability, lossless measurement capture or qualified audit logging.
- Equivalent commissioning of direct serial and serial-to-TCP alternatives.

## 11. Actions before operational acceptance

1. **Approve the measurement basis.** Define the dose-rate quantity, detector
   position and assessment conditions for each station.
2. **Approve individual thresholds.** Establish the input-tray criterion for the
   X-ray/GeGI workflow and the applicable screening criteria at all drum stations.
   Do not treat the supplied 150 µSv/h defaults as those approvals.
3. **Verify instrument calibration.** Record serial numbers, calibration
   certificates, uncertainty and the justification for any non-unity software factor.
4. **Validate station identity.** Confirm the A/B/C/D symbol mapping against the
   physical detector positions after installation or replacement.
5. **Perform controlled functional acceptance.** Exercise valid data, alarms,
   health faults, unplugged probes, stalled sequences, PLC/network interruptions,
   restart recovery and loss of the browser/backend.
6. **Define fail-state decisions.** Specify the operator response to stale,
   missing, invalid or faulted data. Such states must not be treated as evidence
   that a dose-rate criterion has been met.
7. **Engineer any required interlocks separately.** The current read-only driver
   supplies no verified machine permit or safety-rated protective function.
8. **Provide records where required.** If readings support acceptance or transport
   records, add an approved durable recording and review process including
   measurement context, time, identity and configuration.
9. **Control configuration and deployment.** Review changes to thresholds,
   calibration, symbol assignments, network settings and deployed software.

## 12. Implementation references

| Reference | Source |
|---|---|
| Driver, shared acquisition and processing | [nodes/gamma_probe_node.py](../nodes/gamma_probe_node.py) |
| Per-probe and common ADS settings | [config/probes.yaml](../config/probes.yaml) |
| Preferred acquisition launch | [launch/gamma_probes_shared_ads.launch](../launch/gamma_probes_shared_ads.launch) |
| Single-probe launch | [launch/gamma_probe.launch](../launch/gamma_probe.launch) |
| Optional four-process launch | [launch/gamma_probes_ads.launch](../launch/gamma_probes_ads.launch) |
| Four-topic viewer launch | [launch/gamma_probe_plot.launch](../launch/gamma_probe_plot.launch) |
| ROS/HTTP backend | [nodes/dose_web.py](../nodes/dose_web.py) |
| Browser layout and renderer | [web/dose_plot.html](../web/dose_plot.html) |
| Serial/TCP bridge | [serial_bridge.py](../serial_bridge.py) |
| Container and environment | [Dockerfile](../Dockerfile), [entrypoint.sh](../entrypoint.sh) |
| Host shortcuts | [probe.sh](../probe.sh), [plot.sh](../plot.sh) |
| Automated verification | [tests/](../tests/) |
| Operating instructions | [README.md](../README.md) |
| Instrument specification | JCS RMS30-102ASx datasheet, Issue 1.0, August 2023; project-supplied manufacturer document |

## Conclusion

The driver provides a coherent four-channel monitoring path from the instrument
ASCII frames, through PLC ADS and ROS, to independently rendered browser charts.
The shared ADS design uses the existing return route while preserving separate
measurements, calibration factors, averages, alarms and health states.

It is suitable as the implemented software foundation for input-tray and
drum-station dose-rate indication. Its use in waste acceptance, X-ray/GeGI
workflow decisions or transport screening remains conditional on approved
measurement procedures, calibrated instruments, justified limits and any
separately required protective systems.
