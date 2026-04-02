# NetInventory Project Goals

## Problem

We have a laptop and run this app while moving through the museum infrastructure.
The human may plug the laptop into arbitrary Ethernet sockets on arbitrary switches
or routers. The system should automatically observe the network environment and
record what it can learn.

The museum infrastructure is poorly documented or undocumented. The purpose of this
project is to build that documentation from field observations.

## Primary Goal

Auto-detect when the laptop has moved to a different network environment and produce
useful summaries of what was discovered there.

This should work when the operator simply keeps the app running and moves around.

## Data Sources

Preferred and possible signals:

- Wired Ethernet link state and IP configuration
- Gateway identity
- ARP neighbors and reachable hosts
- SSID/BSSID when Wi-Fi is visible or connected
- Bluetooth devices if available
- GPS coordinates when a USB GPS device is present and usable

Location hints matter, but GPS is often unavailable indoors. The system should
therefore treat Wi-Fi and possibly Bluetooth observations as location/context
signals too.

## Current Product Direction

The app should:

- Detect network changes automatically while running continuously
- Capture enough raw evidence to reconstruct what network the laptop is on
- Derive a stable network identity from multiple signals
- Summarize repeated observations instead of only storing unbounded raw records
- Help build a practical map of museum infrastructure over time

## Current Pain Points

- We appear to keep too many records
- We do not summarize aggressively enough
- Network changes should be detected automatically during movement
- Indoor location estimation is still weak when GPS is absent

## Working Definition Of Success

After walking around with the laptop and plugging into random ports, we should be
able to answer questions such as:

- Which distinct networks did we encounter?
- Where were they likely located?
- Which sockets, switches, gateways, and neighboring devices appear related?
- What changed between visits to the same place?
- What evidence supports each conclusion?

## Near-Term Engineering Priorities

1. Improve network-change detection so the collector produces a new observation
   when the environment actually changes, not just on noisy events.
2. Reduce raw snapshot sprawl by rolling up repeated observations into per-network
   summaries.
3. Enrich location inference using Wi-Fi and Bluetooth fingerprints when GPS is
   missing.
4. Preserve enough raw evidence for audit/debugging, but make summaries the main
   product surface.
