# NetInventory Implementation Plan

## Product Shape

Default behavior should be simple:

- Running `netinv` should start collection and the local service/UI by default.
- It should only avoid serving or collecting when explicitly told not to.

This keeps the common workflow short while still allowing headless and remote use.

## UI Direction

We should not actively build and maintain three frontends at once.

Current decision:

- CLI is the primary user interface
- Backend/business logic must stay clearly separated from any UI
- Other UIs are optional and secondary
- The existing Flask web UI is temporary and should not receive major new feature
  work unless it directly supports backend development

This means we should avoid putting important aggregation, summarization, or
topology logic inside UI-specific code. Those capabilities belong in shared core
logic that a CLI, Tk app, or web app could all call later.

If we add a GUI again, it should be a thin client over the same backend/service
layer, not a second implementation of project logic.

## Command Model

Recommended command behavior:

- `netinv`
  Start collector + local API/UI unless disabled by flags.
- `netinv collect`
  Start collector only, optionally daemonized.
- `netinv serve`
  Start API/UI only.
- `netinv status`
  Query current state from the running process when possible.
- `netinv current`
  Show current inferred network, confidence, recent evidence, and location hints.
- `netinv recent`
  Show recent transitions and material changes.
- `netinv networks`
  Show known network summaries.
- `netinv annotate`
  Attach human notes such as room, cabinet, switch, or wall port.
- `netinv sync`
  Push/pull data to or from a central node.

## Running Process And Coordination

Subcommands should be aware of a possibly running collector/service process.

Preferred behavior:

- If a daemon is already running, read-only commands should query it over a local
  control socket or HTTP API instead of touching storage directly.
- Mutating commands should relay requests to the running process where possible.
- If no process is running, read-only commands may read local storage directly.
- If no process is running, mutating commands may perform an offline update in a
  storage-safe way.

This avoids conflicting writes and duplicate collectors.

## Collector Defaults

The collector should continuously try to infer:

- Current network identity
- Whether the environment materially changed
- Whether GPS is present and producing useful fixes
- Whether Wi-Fi and Bluetooth scans are possible
- Whether passive packet capture is possible

Detection should be persistent by default. GPS detection in particular should not
be a one-time startup check. The user may plug in the receiver later, and indoors
the system may go from no fix to usable fix after some time.

## Observation Sources

### Active/structured signals

- Link state changes
- IP addressing and routes
- Gateway IP and MAC
- ARP/neighbor tables
- DNS reachability and resolution behavior
- External IP
- Connected Wi-Fi SSID/BSSID
- Visible Wi-Fi APs and signal strengths
- Visible Bluetooth devices/beacons when available
- GPS fixes when available

### Passive signals

- Ethernet packet capture
- Wi-Fi packet capture when hardware/driver/capabilities allow monitor-like
  operation or useful passive observation

Passive observation matters because one of the goals is to detect whether a port,
VLAN, or Wi-Fi environment leaks traffic beyond what should be visible.

Examples:

- A switch port that exposes broad broadcast or unicast traffic
- A port that only ever sees gateway traffic
- A Wi-Fi network with meaningful lateral visibility
- Segments that appear isolated except for infrastructure control traffic

## Snapshot Strategy

Raw snapshots are still useful, but they should no longer be the primary product.

Recommended model:

- Keep event records and selected raw snapshots as evidence
- Maintain a current-state fingerprint
- Create a new material observation only when the fingerprint meaningfully changes
- Periodically emit a compact heartbeat instead of full repeated snapshots
- Roll repeated observations into summaries

## Fingerprinting And Change Detection

Fingerprinting should combine multiple signals, for example:

- Interface type
- Subnet set
- Gateway identity
- External IP
- Connected SSID/BSSID
- Wi-Fi scan fingerprint
- Bluetooth scan fingerprint
- Neighbor set fingerprint
- Passive traffic profile fingerprint

We should distinguish:

- `event`: something happened
- `observation`: data we gathered
- `transition`: we likely moved to a new environment
- `summary update`: confidence or topology changed without a full transition

## Summary Model

Each distinct network-like environment should maintain a summary record with:

- `network_id`
- `first_seen`
- `last_seen`
- `seen_count`
- `device_ids`
- `gateway identities`
- `subnets`
- `external IP history`
- `wifi fingerprints`
- `bluetooth fingerprints`
- `traffic visibility profile`
- `location hints`
- `human annotations`
- `evidence references`
- `confidence`

The summary should answer: "what do we think this place/network is?"

## Topology Mapping

We need to support more than simple "same network" grouping.

The model should also infer:

- same network, same location
- same network, different physical port
- same network, different switch
- uplink/downlink relationships
- likely VLAN boundaries
- likely isolation boundaries
- likely leakage between segments

Human annotations are important here. If the user records that a different wall
port, switch port, cabinet, or room was used, the system should merge that with
observed evidence and update topology confidence.

Examples of useful conclusions:

- "Same gateway and neighbor profile, different wall port"
- "Same logical network, but distinct passive traffic profile, likely different switch"
- "This port leaks traffic from other hosts"
- "This segment appears tightly isolated and only exposes gateway/infrastructure"

## Location Inference

Location inference should be multimodal and confidence-based.

Priority order is not absolute, but roughly:

- GPS fix when reliable
- Wi-Fi environment fingerprint
- Bluetooth environment fingerprint
- Repeated gateway/switch/neighbor co-occurrence
- Human annotation

GPS should be continuously retried by default because hardware may appear later
and fixes may become available only after time outdoors or near windows.

## CLI And GUI

CLI and GUI should use the same underlying service and summary model.

CLI is important for:

- field use on a laptop
- easy installation on remote devices
- permanent monitoring
- scripting and automation

GUI is important for:

- browsing known networks
- inspecting evidence
- viewing transitions and confidence
- visualizing inferred topology
- editing annotations

Near-term priority is CLI, not GUI expansion.

Notes to self:

- Keep UI code thin
- Do not duplicate workflows across multiple frontends yet
- Move summary and topology logic out of `ui/analysis_module.py`
- Treat the current web UI as disposable once a proper CLI/service exists
- Only revisit Tk or web after the backend model stabilizes

## Multi-Device Gathering

We should assume multiple devices eventually contribute observations.

Recommended model:

- each collector has a stable `device_id`
- each observation includes `device_id`, local timestamp, monotonic sequence, and
  schema version
- collectors store locally first
- collectors sync batches to a central aggregator when possible
- central ingest deduplicates and merges into global summaries

This supports permanent monitors and roaming field devices.

## Storage Tiers

Use at least three tiers:

1. `events`
   Low-level trigger and sensor records
2. `observations`
   Material snapshots/fingerprints and selective raw evidence
3. `summaries`
   Long-lived per-network and topology records

Raw packet captures, if enabled, should be separately retained and aggressively
bounded because they can grow quickly and may have privacy implications.

## Immediate Milestones

### Milestone 1: Runtime Architecture

- Refactor `netinv` into subcommands
- Make bare `netinv` start collect + serve by default
- Add single-process coordination and local control API/socket

### Milestone 2: Material Change Detection

- Introduce current-state fingerprinting
- Classify noisy events vs meaningful transitions
- Reduce duplicate snapshots

### Milestone 3: Summary Storage

- Add per-network summary records
- Track evidence references and confidence
- Expose summaries in both CLI and GUI

### Milestone 4: Richer Sensing

- Continuous GPS auto-detection and retry
- Wi-Fi scan fingerprints
- Bluetooth scan fingerprints
- Capability-aware passive capture support

### Milestone 5: Topology Inference

- Model ports, switches, gateways, and observed adjacency
- Merge human annotations into graph confidence
- Flag likely leakage and isolation characteristics

### Milestone 6: Multi-Device Sync

- Add `device_id`
- Add local spool and sync protocol
- Add central ingest and merge logic

## Recommended Next Implementation Step

The next code change should be architectural, not cosmetic:

1. Refactor the binary into a command structure with a long-running local service.
2. Add a control API so CLI commands can query or instruct a running instance.
3. Introduce a new summary store beside raw snapshots.
4. Add a first version of material-change fingerprinting.

That sequence keeps future work aligned for CLI, GUI, and remote deployment.
