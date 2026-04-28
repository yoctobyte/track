# TRACK Install Profiles

TRACK installs should start from one question:

```text
How should this machine participate?
```

The answer selects a profile. The profile only controls defaults and which
services start automatically; every machine can still become a trusted sync
node later.

## Profiles

### Standalone

Use when the machine is a fresh isolated TRACK node.

Default behavior:

- create local TrackHub config
- create local TrackSync host identity
- create or suggest one local environment slug
- do not require a remote host
- run local apps according to local config
- keep all data local until the operator pairs with another trusted node

This is the safest first-run path when there is no known server or existing
installation.

### Server

Use for an always-on or mostly-on node.

Default behavior:

- expose TrackHub and TrackSync on configured bind/ports
- keep NetInventory Client hidden from public overview, with localhost shortcut
- run server-side subprojects according to selected environment
- accept pairing requests after admin approval
- act as relay/public surface for intermittent laptops when policy allows

A server is not the only source of truth. It is a durable node that other nodes
can sync with.

### Client / Field Laptop

Use for laptops and workstations that collect or produce data.

Default behavior:

- bind user-facing tools to localhost
- show local-only app shortcuts, such as NetInventory Client
- create a TrackSync host identity
- suggest the known environment/location slug
- optionally pair with a known remote server
- sync opportunistically when online

Laptops are trusted nodes after approval. They are expected to be offline often.

## First-Run Questions

Minimum interactive questions:

```text
Profile: standalone | server | client
Local host name: suggested from hostname
Location slug: suggested by installer or operator
Admin password: generated or entered
Remote host URL: optional
Remote pairing credential: optional
```

For known deployments, most of this can be suggested but should still be
visible to the user:

```text
Profile: client
Remote host URL: https://track.example.org/tracksync
Suggested location slug: museum
Public base URL: https://track.example.org
```

The common user flow should be:

1. User enters the public TRACK host, for example
   `https://track.praktijkpioniers.com`.
2. Installer derives the TrackSync URL as
   `https://track.praktijkpioniers.com/tracksync`.
3. Installer asks that remote host for public realms/environments.
4. User chooses a realm/location from the returned list.
5. User enters the realm password or pairing password.
6. Local node stores the remote as a pending/trusted peer depending on the
   response.

The user should not need to know subproject-specific URLs. They provide the
TRACK host and credentials; TrackSync handles the global pairing.

## Preseeded Install

Known-user-base installs should support a tiny preseed file or environment
variables.

Example:

```json
{
  "profile": "client",
  "trackhub_public_base_url": "https://track.praktijkpioniers.com",
  "tracksync_remote_url": "https://track.praktijkpioniers.com/tracksync",
  "suggested_location_slug": "museum",
  "suggested_location_name": "Museum",
  "netinventory_client_visible_localhost": true
}
```

Equivalent environment variables:

```bash
TRACK_PROFILE=client
TRACK_PUBLIC_BASE_URL=https://track.praktijkpioniers.com
TRACKSYNC_REMOTE_URL=https://track.praktijkpioniers.com/tracksync
TRACK_LOCATION_SLUG=museum
TRACK_LOCATION_NAME=Museum
```

## Pairing Flow

There are two valid first-run outcomes.

### Start Fresh

The operator skips remote pairing.

The installer should:

- create local TrackSync identity
- create local environment metadata
- write TrackHub config for the selected profile
- start TrackHub locally

The node can be paired later without losing local data.

### Pair With Remote

The operator enters a public TRACK host such as:

```text
https://track.praktijkpioniers.com
```

The installer normalizes that to the remote TrackSync endpoint:

```text
https://track.praktijkpioniers.com/tracksync
```

The installer should:

- create local TrackSync identity
- fetch the remote public realm/environment list
- let the user choose the intended realm/location
- ask for the realm password or pairing password
- store the remote URL as a peer candidate
- submit or prepare a pairing request
- show pending/approved state
- sync only after the remote admin trusts this node

Until approval, the laptop can still collect local append-only data.

## Trust Boundary

Pairing is global to TRACK.

Subprojects do not own trust. NetInventory, Map3D, DeviceControl, and future
apps should expose adapters to TrackSync. TrackSync decides which node is
trusted, which data tiers are allowed, and when to pull or push.

Normal data sync should be append-only:

- new facts are appended
- changed files become new immutable revisions
- hiding data uses tombstones or superseding records
- physical deletion is local retention policy, not sync behavior

## Current Implementation Status

Already present:

- TrackHub environment config and app visibility controls
- localhost-only shortcut for hidden NetInventory Client
- TrackSync host identity
- manual peer URL plus secret configuration
- signed hello/manifest/file APIs
- environment metadata in manifests
- artifact root manifests

Still needed:

- single first-run installer/profile command
- TrackHub admin template restoration
- preseed file/env handling
- TrackSync pending pairing requests
- remote admin approve/reject flow
- adapter registry for subproject record exports/imports
- scheduled opportunistic sync for intermittent laptops
