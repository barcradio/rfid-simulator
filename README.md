# RFID Interface Test Harness

A lightweight RFID interface test harness for **Ultra Tracker**, with the **Zebra FXR90** as the first simulated reader implementation.

The project is intentionally **not** a complete Zebra FXR90 implementation. It reproduces the externally visible behavior that Ultra Tracker consumes so the RFID interface can be tested with normal race traffic, high-volume traffic, bursts, unknown tags, reconnects, and controlled failure scenarios.

The architecture is intended to make additional reader simulators possible later:

```text
Ultra Tracker
     │
     │ RFID interface
     ▼
RFID Interface Test Harness
     │
     ├── Zebra FXR90 simulator   ← current implementation
     ├── Future reader simulator
     └── Future reader simulator
```

## Current reader implementation

The current implementation simulates the subset of the **Zebra FXR90** interface used by Ultra Tracker:

- HTTPS REST API on port **443**
- WebSocket Secure (WSS) on port **443**
- REST login with HTTP Basic authentication
- Bearer-authenticated `/cloud/*` endpoints
- Unauthenticated `/ws` WebSocket

```text
HTTPS REST:  https://<host>:443/cloud/...
WSS:         wss://<host>:443/ws
```

The FXR90-specific REST paths, WebSocket payload format, and `FX90_*` environment variables are retained because they are part of the current Ultra Tracker integration contract.

## Test control panel

The harness includes a browser-based control panel for repeatable integration and stress testing:

```text
https://<host>:443/test/
```

It provides:

- **Live scan status**
- **Live counters** for total tags, legitimate runner tags, noise tags, remaining runners, custom noise remaining, and WebSocket clients
- **Race configuration** for runner count, bib range, tag order, noise percentage, and one-read-per-tag behavior
- **Custom noise tags** supplied as a JSON array
- **Burst configuration** for burst size, duration, time between bursts, and artificial tag delay
- **Failure injection** for WebSocket disconnects after a tag count or elapsed time
- **Scenario selection and time acceleration** for long-duration race simulations
- **Start, stop, save, and reset controls**
- **Diagnostic JSON** containing the complete current test state

Settings are runtime-only and can only be changed while the simulated reader is stopped.

### Scenario simulation

Scenario simulation is designed for longer, repeatable race-day traffic patterns that are difficult to reproduce with simple burst settings. Scenarios are versioned JSON definitions stored under `src/fx90_simulator/scenarios/` and are loaded by name through the test API and control panel.

Built-in scenarios currently include:

| Scenario | Purpose | Duration | Runners | Burst max | Distribution |
|---|---|---:|---:|---:|---|
| **Start Line** | Recorded start arrivals from StartLine.csv | 10m 21.1s | 341 | 20 | Recorded timeline |
| **Finish Line** | Recorded finish arrivals from FinishLine.csv | 18h 14m 41s | 253 | 5 | Recorded timeline |
| **Aid2** | Recorded aid-station arrivals from Aid2.csv | 3h 37m 2.414s | 310 | 20 | Recorded timeline |
| **Short Burst** | Fast development/integration scenario | 60 seconds | 50 | 20 | Truncated normal |

The scenario configuration is the source of truth for the traffic schedule. Each scenario has a deterministic `random_seed`, so the same configuration produces the same arrival schedule. Runner tags remain unique when `report_each_tag_once` is enabled.

Start Line and Finish Line use every timestamp from the archived `StartLine.csv` and `FinishLine.csv` recordings, sorted chronologically and converted to seconds since each recording's earliest read. The first runner is emitted immediately; all subsequent gaps, simultaneous arrivals, and the finish timeline's midnight rollover are preserved. The original recording windows are September 25, 2026 06:06:26.827-06:16:47.927 for start and September 25 23:39:23 through September 26 17:54:04 for finish. The finish profile does **not** include the wait between race start and the first finisher.

These profiles replay timing, not recorded bib identities: tags are generated using the existing tag-order setting and synthetic bib ranges 1-341 (start), 1-310 (Aid2), and 1-253 (finish). Aid2 uses every timestamp from the archived `Aid2.csv`, normalized to its first arrival just like the other profiles. Short Burst remains synthetic.

Noise is randomly generated, not replayed from the logs. The archived `Startline.log` contains 7 rejected-tag warnings for 341 runners; `Aid2.log` contains 77 for 310 runners, including repeated tags and one warning after the last runner. These give measured additive rates of 2.05% and 24.84% (noise reads divided by runner reads, not all reads), rounded to **2% for Start Line** and **25% for Aid2**. **Finish Line also uses 25%**, borrowing the higher observed rate because no finish log is available. The profiles add noise with that probability at each runner arrival without consuming or delaying a runner. Counts are approximate rather than fixed; a fixed seed and tag-order configuration make the random sequence repeatable. Log timestamps, tag values, malformed-message errors, and connection failures are not replayed.

The measured offsets are embedded in the scenario JSON files, so the simulator does not need the original recordings. The raw CSVs and logs are kept outside the repository. To regenerate a profile, restore the CSVs to the ignored `rfidreader_data/` directory or substitute their archived paths, then run from the repository root:

```powershell
python scripts\import_reader_profile.py rfidreader_data\StartLine.csv src\fx90_simulator\scenarios\start-line.json --noise-percent 2
python scripts\import_reader_profile.py rfidreader_data\Aid2.csv src\fx90_simulator\scenarios\aid2.json --noise-percent 25
python scripts\import_reader_profile.py rfidreader_data\FinishLine.csv src\fx90_simulator\scenarios\finish-line.json --noise-percent 25
```

The importer replaces the destination's timing, runner count, synthetic bib range, and noise setting while preserving its name, burst settings, seed, and time scale. It treats each CSV row as an arrival. `--noise-percent` defaults to zero when omitted.

Scenario noise is **additive**: configured noise events are inserted in addition to the scheduled runner reads rather than replacing them. This means a 500-runner scenario still delivers all 500 legitimate runner tags even when noise is enabled.

The control panel provides four time-scale choices:

```text
1x    normal simulated time
10x   ten times faster
60x   sixty times faster
600x  six hundred times faster
```

For example, Start Line completes in about 10.35 seconds at 60x, while Finish Line completes in about 109.47 seconds at 600x.

Within a scenario burst, the scheduled arrival spacing is also scaled by `time_scale`. The configured `max_duration_seconds` therefore represents actual simulated spacing between events, not just a grouping hint.

### Scenario JSON format

A scenario definition has this general shape:

```json
{
  "name": "Custom Start",
  "version": 1,
  "type": "start-line",
  "duration_seconds": 3600,
  "runner_count": 500,
  "bib_start": 1,
  "bib_end": 500,
  "distribution": {
    "type": "truncated-normal",
    "center_seconds": 480,
    "spread_seconds": 720
  },
  "burst": {
    "max_size": 20,
    "max_duration_seconds": 0.8
  },
  "noise": {
    "percent": 5
  },
  "report_each_tag_once": true,
  "random_seed": 12345,
  "time_scale": 1
}
```

Supported arrival distributions are `truncated-normal`, `log-normal`, and `recorded`. A recorded distribution replaces the statistical parameters with an explicit schedule:

```json
{
  "type": "recorded",
  "arrivals_seconds": [0, 17.407, 61.623]
}
```

`arrivals_seconds` must contain exactly `runner_count` finite, nonnegative offsets in chronological order, all within `duration_seconds`. Equal offsets are allowed for simultaneous arrivals. Recorded offsets are used directly without random sampling or jitter; changing the seed only changes synthetic tag ordering and noise generation.

Burst settings limit how many scheduled arrivals may be grouped together and the maximum simulated duration of that burst. Scenario validation also ensures bib numbers fit the four-digit decimal RFID representation and that the configured runner count fits the bib range.

To inspect the available scenarios through the API:

```text
GET /test/scenarios
```

To select a built-in scenario:

```text
PUT /test/scenario
```

with a body such as:

```json
{"name":"Start Line"}
```

A selected scenario is started with:

```text
POST /test/scenario/start
```

**API clients must select a scenario before calling `POST /test/scenario/start`.** If no scenario is selected, the start request returns `400 no scenario selected`. The browser control panel performs the selection automatically when you choose a scenario.

Resetting the test clears the selected scenario:

```text
POST /test/reset
```

### Custom noise tags

Custom noise tags are treated as a one-shot queue. When a noise event occurs, the next supplied custom tag is sent in list order. Once the list is exhausted, the generated noise pool is used.

This is useful for parser and error-handling tests because custom values are not required to look like valid RFID tags. For example:

```json
[
  "00000000000000000000015A",
  "00000000000000000000015B",
  "00000000000000000000015C"
]
```

The **Custom noise remaining** counter shows how many supplied values are still waiting to be consumed. Because noise selection is probabilistic, the queue is not a fixed number of events; it drains only when noise events are selected.

### Suggested test workflow

1. Open `/test/` in a browser.
2. For a normal race simulation, select a built-in scenario and choose a time scale.
3. For short/manual tests, configure the race, burst, noise, and failure-injection settings instead.
4. Click **Save Settings** when using manual settings.
5. Connect Ultra Tracker to the harness.
6. Click **Start Scan** or **Start Scenario**.
7. Watch the live counters and WebSocket client count.
8. Use **Stop Scan** or **Reset** before changing the configuration.

For example, setting `disconnect_after_tags` to `190` deliberately closes the WebSocket after approximately 190 delivered events, allowing Ultra Tracker reconnect and recovery behavior to be tested against a repeatable failure.

The test control API is also available directly:

```text
GET  /test/status
GET  /test/scenarios
PUT  /test/config
PUT  /test/scenario
POST /test/start
POST /test/scenario/start
POST /test/stop
POST /test/reset
GET  /test/
```

## Automated tests

Install dependencies and run the complete suite:

```bash
pytest
```

Useful subsets:

```bash
pytest -m unit
pytest -m integration
pytest -m websocket
pytest -m stress
```

The `stress` marker is reserved for tests that intentionally generate large or high-volume traffic so those tests do not have to run on every small code change.

Scenario tests cover built-in scenario loading and properties, accelerated reader emission timing, recorded schedule validation and API selection, deterministic synthetic scheduling, duration bounds, burst limits, bib-range validation, deterministic tag generation, and additive scenario noise behavior. Exact comparisons against every recorded CSV arrival run when the corresponding archived CSV is restored to `rfidreader_data/`; otherwise pytest reports those comparisons as skipped. The Docker image does not include the recordings.

## Zebra FXR90 / Ultra Tracker contract

This section documents the current reader-specific compatibility contract. It is deliberately kept separate from the generic test-harness purpose so additional reader implementations can be added without changing the overall project description.

### REST

`GET /cloud/localRestLogin` uses HTTP Basic authentication and returns:

```json
{"code":0,"message":"<bearer-token>"}
```

All other supported REST endpoints require `Authorization: Bearer <token>`.

Supported endpoints:

```text
GET /cloud/localRestLogin
GET /cloud/status
GET /cloud/mode
PUT /cloud/mode
PUT /cloud/start
PUT /cloud/stop
```

`PUT /cloud/start` accepts the request body used by Ultra Tracker (`{"doNotPersistState":true}`), starts tag generation, and returns HTTP 204. If already active it returns HTTP 422 with `start currently ongoing`.

`PUT /cloud/stop` stops tag generation and returns HTTP 204.

`GET /cloud/status` reports simulated reader state, including `radioActivity` and antenna state. `GET /cloud/mode` returns the simulated reader mode. `PUT /cloud/mode` accepts the request and returns HTTP 204.

### WebSocket

Ultra Tracker connects without a Bearer token:

```text
wss://<host>:443/ws
```

Tag events use the observed FXR90 format:

```json
{"data":{"eventNum":1,"format":"epc","idHex":"000000000000000000001"},"timestamp":"2026-09-06T16:00:00.000-0600","type":"CUSTOM"}
```

The `idHex` format is compatible with Ultra Tracker's current parser: 20 leading zeroes followed by the decimal runner/tag number.

## Simulated traffic behavior

The default configuration is designed around a typical ultra race with roughly 300–400 runners:

- **400 legitimate runner tags** by default
- Legitimate runner tags are generated from the configured bib range and reported **once per reader start**
- Runner reads can be sent in **sequential or randomized order**
- Runner reads are grouped into bursts of up to **20 events**
- A burst targets approximately **one second or less**
- **5% unknown/noise tags** by default
- Generated noise uses bib numbers outside the configured runner range
- Tag generation remains stopped until `/cloud/start` is called unless `FX90_AUTO_START=true`
- Periodic heartbeat logs report scan state, counts, remaining runners, custom noise remaining, and connected WebSocket clients

The harness also supports deliberate WebSocket disconnects and artificial delivery delay so reconnect, health-check, timeout, and throughput behavior can be tested deliberately rather than relying only on failures from a physical reader.

## Project layout

```text
fx90-simulator/
├── src/fx90_simulator/
│   ├── api/          # REST, WebSocket, and test-control interfaces
│   ├── simulator/    # Simulated reader, scenarios, test controls, and tag generation
│   ├── scenarios/    # Versioned built-in scenario JSON definitions
│   ├── config.py     # Environment-based configuration
│   └── main.py       # Application entry point
├── tests/            # Automated unit and integration tests
├── scripts/          # Developer utilities
├── certs/            # Local TLS certificates (not committed)
├── data/             # Runtime and captured data
├── systemd/          # Native Linux service definition
├── .devcontainer/    # VS Code Dev Container configuration
├── Dockerfile
├── compose.yaml
├── requirements.txt
└── README.md
```

## Configuration

Configuration is supplied through environment variables. Docker Compose loads credentials from a local `.secrets` file.

Create the local secrets file from the committed template:

```bash
cp secrets_example .secrets
```

Important settings include:

| Variable | Default | Purpose |
|---|---:|---|
| `FX90_HOST` | `0.0.0.0` | Listen address |
| `FX90_HTTPS_PORT` | `443` | REST and WSS port |
| `FX90_BIB_START` | `1` | First possible legitimate bib number |
| `FX90_BIB_END` | `429` | Last possible legitimate bib number |
| `FX90_RUNNER_COUNT` | `400` | Number of legitimate runner tags per reader start |
| `FX90_TAG_ORDER` | `random` | Legitimate tag order: `random` or `sequential` |
| `FX90_NOISE_PERCENT` | `5` | Percentage of generated events using noise tags |
| `FX90_MAX_BURST_SIZE` | `20` | Maximum events in one burst |
| `FX90_MAX_BURST_SECONDS` | `0.8` | Target maximum burst duration |
| `FX90_BETWEEN_BURSTS_MIN` | `2` | Minimum seconds between bursts |
| `FX90_BETWEEN_BURSTS_MAX` | `8` | Maximum seconds between bursts |
| `FX90_REPORT_EACH_TAG_ONCE` | `true` | Report each legitimate runner once per start |
| `FX90_NOISE_POOL_SIZE` | `50` | Number of reusable generated noise tags |
| `FX90_AUTO_START` | `false` | Start automatically |
| `FX90_HEARTBEAT_SECONDS` | `5` | Diagnostic heartbeat interval |
| `FX90_CORS_ORIGINS` | _(unset)_ | Comma-separated allowed browser origins |

Legitimate RFID values are derived directly from the bib number. For example:

```text
Bib 1   -> 000000000000000000001
Bib 10  -> 000000000000000000010
Bib 190 -> 000000000000000000190
Bib 429 -> 000000000000000000429
```

No runner/tag data file is required.

## TLS and certificate pinning

The harness uses TLS because Ultra Tracker connects to the simulated FXR90 over HTTPS and WSS. Generate local certificates with:

```bash
./scripts/generate-certs.sh
```

The script detects the machine's hostname and primary IP and includes them in the server certificate's Subject Alternative Names.

If Ultra Tracker's `sslCert` field is being used for certificate pinning, obtain the server certificate serial with:

```bash
openssl x509 -in certs/server.crt -noout -serial
```

Enter the hexadecimal value after `serial=` as the certificate pin.

Keep `ca.key` and `server.key` private. Do not commit private keys or generated certificates.

## Docker deployment

```bash
git clone https://github.com/JordenLuke/fx90-simulator.git
cd fx90-simulator
git checkout develop
cp secrets_example .secrets
./scripts/generate-certs.sh
docker compose up -d --build
```

The container publishes HTTPS/WSS on port **443**.

Check the service:

```bash
docker compose ps
docker compose logs -f
```

Stop it with:

```bash
docker compose down
```

## Native Raspberry Pi / Linux deployment

Native deployment is useful on a Raspberry Pi or another Linux host where Docker is not desired. The examples install the harness under `/opt/fx90-simulator`.

```bash
sudo apt update
sudo apt install -y git python3 python3-venv openssl
sudo mkdir -p /opt
sudo git clone https://github.com/JordenLuke/fx90-simulator.git /opt/fx90-simulator
sudo chown -R "$USER":"$USER" /opt/fx90-simulator
cd /opt/fx90-simulator
git checkout develop
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./scripts/generate-certs.sh
```

For normal operation, use the repository's systemd service rather than running the application as root.

## Development container

The repository includes a VS Code Dev Container configuration. Open the repository in VS Code and select **Reopen in Container**. The harness is available on port `443`.

## Capture utility

`scripts/capture.py` is a utility for the current Zebra FXR90-compatible WebSocket interface. It records raw tag data for analysis or replay work and can reconnect after reader-side WebSocket/TCP resets.

```bash
python3 scripts/capture.py
python3 scripts/capture.py --cafile certs/ca.crt
```

Captured data is stored under `data/`.

## Security notes

This harness is intended for controlled test networks. The default credentials are development defaults and should be changed before exposing the harness to an untrusted network.

## License

[MIT](https://opensource.org/license/mit) ©2026
