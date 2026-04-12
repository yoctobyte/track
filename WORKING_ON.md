# Working On

## Current Focus

Move the Python rewrite from a simple collector into a task-driven runtime.

The system needs to support both short and long running work, with clear trigger
rules and bounded persistence.

## Active Goals

1. Define a task model that supports:
   - instant probes
   - burst jobs
   - long-running monitors
   - user-supplied context tasks
2. Make the backend aware of task state, not only collected observations.
3. Keep writes bounded for low-end devices such as Raspberry Pis on SD cards.
4. Prepare the UI/CLI/service layer to report:
   - running tasks
   - queued tasks
   - last task results
   - freshness/confidence
   - user-provided context

## Task Categories

### Instant tasks

- current IP
- routes
- gateway
- DNS
- connected Wi-Fi state

### Burst tasks

- ARP snapshot
- Wi-Fi scan
- Bluetooth scan
- external IP probe
- bounded traceroute

### Long-running tasks

- netlink/link monitor
- GPS monitor
- ARP watch
- passive traffic monitor
- Wi-Fi environment watch
- Bluetooth environment watch

### User context tasks

- location
- room
- cabinet
- wall port
- switch port
- device identity
- note / annotation

## Current Design Rules

- Long-running tasks should emit deltas or summarized observations, not constant
  raw writes.
- Human-entered context is first-class input, not UI decoration.
- Triggers, tasks, observations, and summaries are separate concepts.
- Local operation should remain zero-config.
- Remote agents should stay lightweight.

## Immediate Next Steps

1. Add a Python task model and scheduler registry
2. Track task definitions and task runs in SQLite
3. Implement the first instant task through the scheduler
4. Add user-context storage as structured records

## Progress

- task model and task-run tracking are in place
- first instant task runs through the scheduler
- user context is now stored as structured backend state
- observations now store structured fact payloads in SQLite
- duplicate instant-probe writes are now suppressed when nothing material changed
- the first instant probe now captures default gateway, resolver, and interface facts
- export/import now uses record-level replication bundles with merge support
