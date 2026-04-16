# NetInventory Architecture

## Current Direction

`netinventory` should be treated as a hybrid subsystem inside `TRACK`, but its
hybrid nature should be made explicit rather than left accidental.

The intended shape is:

- `Agent`
- `Hub`
- `Web`

## Agent

The agent runs on the laptop or controlled device that is physically touching a
network.

Typical properties:

- local execution
- may require elevated privileges
- may perform raw capture or privileged inspection
- can attach physical field notes such as:
  - rack
  - cabinet
  - patch panel
  - wall port
  - cable path

The agent is the part that touches reality directly.

## Hub

The hub is the central state holder.

Typical responsibilities:

- SQLite state
- observations
- task runs
- user context
- export/import bundles
- service API

The hub should not depend on raw local capture privileges.

## Web

The web layer is the operator-facing view on top of the hub.

Typical responsibilities:

- show current status
- show known networks
- show recent task runs
- show recent annotations
- expose agent bootstrap/download links

The web surface should explain the system and route users into the agent path,
not attempt to perform privileged local network capture itself.

## TRACK Integration

Inside `TRACK`, `netinventory` should be understood as:

- field network evidence capture
- central aggregation of those observations
- later linking to locations, devices, rooms, racks, and other `TRACK`
  knowledge

This means `netinventory` belongs in the shared documentation and
administration picture even though its runtime shape differs from `map3d` and
`museumcontrol`.

## Practical Rule

Privileged capture happens at the edge.

Central storage, review, and routing happen in the hub.

That separation is the main simplification.
