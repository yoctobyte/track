# TRACK — Concept Notes

This file captures relevant conclusions from broader design conversations that
shape the direction of the whole `track/` project, not just `map3d`.

Primary philosophy documents now live in:

- [philosophy/TRACK_PHILOSOPHY.md](./philosophy/TRACK_PHILOSOPHY.md)
- [philosophy/CONVERSATION_NOTES.md](./philosophy/CONVERSATION_NOTES.md)

This file remains useful as raw extracted conceptual notes and supporting
material.

## 2026-04-14 — Detailed Architectural Vision

A detailed update on the modular "umbrella" vision, infrastructure strategy, 
and federated security model was captured from user feedback.

See: [ARCHITECTURAL_FEEDBACK.md](./ARCHITECTURAL_FEEDBACK.md)

## 2026-04-12 — Shared conversation: broader TRACK architecture

Source:

- https://chatgpt.com/share/69dbc9ea-92ec-8387-8439-e1d56e3bf5a5

### Key conclusion

`TRACK` is not just:

- an asset tracker
- a wiki
- a CMDB
- a remote-control dashboard
- a field survey tool

It is closer to:

**a capture-first operational memory system**

That means:

- people should be able to dump observations in quickly
- the system should preserve raw inputs first
- structure, linking, naming, enrichment, and control can be layered on later

### Phrase / expansion captured in that conversation

The conversation converged on:

**TRACK — Technical Resource And Control Knowledge Kit**

The most important part is not the acronym itself, but the shape it implies:

- knowledge backbone
- modular tools
- capture and enrichment first
- control as an extension, not the only goal

### Architectural shape inferred there

## TRACK Core

Shared backbone that holds truth over time. The conversation suggested this
core should center on:

- observations
- entities
- relationships
- locations
- documents
- media
- QR identities

This maps well to the existing repo direction.

## TRACK Kit modules

The conversation strongly supported a modular "kit" model instead of one
massive monolith.

Examples discussed there:

- `TRACK-Kit: Capture`
  - photo upload
  - voice note upload
  - document upload
  - quick notes
  - QR scanning

- `TRACK-Kit: Vision`
  - OCR
  - object recognition
  - similarity matching
  - scene/device recognition

- `TRACK-Kit: Audio`
  - speech-to-text
  - transcription
  - keyword extraction

- `TRACK-Kit: Control`
  - remote actions
  - reboot / volume / launch / config operations
  - Ansible fits here naturally

`devicecontrol/` is the first concrete implementation of this kit direction:
an Ansible-backed, environment-aware control surface with manual bootstrap tools
and a limited web UI for approved actions.

- `TRACK-Kit: Mapping`
  - rooms
  - cabinets
  - zones
  - QR anchors
  - spatial organization

- `TRACK-Kit: Linking`
  - "this belongs to that"
  - "this cable goes there"
  - "this manual belongs to that device"
  - "this rack is in that room"

### Very important workflow idea

The conversation emphasized that your intended workflow is unusual:

1. walk into a space
2. take a photo / record audio / attach document
3. store raw input immediately
4. later transcribe / describe / classify / connect

That is different from traditional tools, which are usually:

- structure-first
- schema-first
- asset-first

Whereas TRACK should remain:

- capture-first
- usefulness-from-day-one
- progressive-structure

### Minimal viable TRACK from that conversation

The conversation suggested that the first useful version of TRACK is smaller
than it might seem:

**TRACK Core + Capture Kit**

Minimal Phase 1 capability:

- upload photo
- record voice note
- attach document
- add short note
- optionally scan QR

Then later:

- group observations
- create named entities
- assign locations
- link related things

### Relationship to existing tools

The conversation argued that existing tools may still be useful as reference or
partial inspiration, but are not a full fit:

- Snipe-IT
- BookStack
- ODK / field-survey tools
- Immich / PhotoPrism / photo-first systems

The expected outcome is not necessarily "replace all of them", but build the
missing glue layer that matches the actual workflow.

### Naming / identity notes

The conversation also argued:

- `TRACK` is broad but usable
- generic-word ambiguity is a bigger risk than domain conflict
- `TRACK Core`, `TRACK Kit`, `TRACK Capture`, `TRACK Control` become much more
  distinctive than plain `TRACK`

### Current interpretation for this repo

This conversation changes how the whole project should be read:

- `map3d` is one kit/subproject inside a larger operational memory system
- future subprojects are not random extras; they are likely other TRACK kits
- the top-level project should preserve a common conceptual model:
  - observations
  - entities
  - relationships
  - locations
  - media
  - time

### Caution

This was still a design conversation, not a locked architecture spec. It is
best treated as directional guidance for future planning and naming.
