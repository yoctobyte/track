# Conversation Notes

This file points to conversation-derived philosophy and planning notes that
matter across the whole `track/` project.

## Current notes

- [TRACK philosophy](./TRACK_PHILOSOPHY.md)
- [Root TRACK notes](../TRACK_NOTES.md)
- [map3d conversation notes](../map3d/CONVERSATION_NOTES.md)

## Distilled conversation takeaways

### Project split

- Keep two linked but distinct systems:
  - a strict control dashboard for managed devices and approved actions
  - a looser capture/documentation system for messy field input
- Link the two systems where useful, but do not force them into one UI or one
  data model too early.

### Discovery-first workflow

- The practical starting point is reverse engineering, not clean asset entry.
- Start from observations, not fully defined assets.
- A useful lifecycle is:
  - `observation -> review/cluster -> entity -> optional control link`
- The system should tolerate uncertainty, duplicates, guesses, and incomplete
  descriptions during the early phases.

### Capture philosophy

- The documentation side should be capture-first and structure-later.
- Valuable field inputs include:
  - photos
  - voice notes
  - documents / PDFs
  - rough room or object hints
- Mobile web is sufficient for an MVP capture workflow:
  - camera: yes
  - audio recording/upload: yes
  - detailed Wi-Fi fingerprint scanning: no

### QR labels as anchors

- QR labels are a strong practical bridge between physical space and
  documentation.
- They can serve several roles at once:
  - active scan targets for staff
  - passive markers visible in photos
  - stable room/object anchors for later AI matching
- Public-facing and back-of-house QR behavior should be treated differently:
  - private identifiers or internal flows in technical spaces
  - public-safe landing pages or neutral labels in visitor-facing spaces

### Control architecture

- Ansible fits well as a backend for operational actions, not as the end-user
  interface.
- Operational actions such as reboot, volume change, restart, config push, and
  diagnostics can reasonably be driven through Ansible during the early phases.
- A good device model separates:
  - a management user for automation
  - a runtime user for the application/session
- The first concrete Ansible subproject is `devicecontrol/`: bootstrap is kept
  manual, while the web UI only runs approved playbooks against enrolled hosts.

### Knowledge scope

- The system should document unmanaged and partially managed things too, not
  only devices under direct remote control.
- Useful entries may include:
  - devices
  - rooms
  - racks
  - cabinets
  - remotes
  - supplies
  - manuals
  - procedures
  - ad hoc observations

### Subproject character

- `TRACK` should be expected to contain subprojects that solve adjacent
  problems in different ways.
- Some subprojects will be hybrid by nature rather than clean single-purpose
  web apps.
- `netinventory` is a good example:
  - central collection and aggregation
  - local inspection scripts
  - probe paths that may require elevated privileges
  - possible long-running monitoring on controlled devices
- This is acceptable as long as the boundaries and operating assumptions remain
  explicit.

### AI role

- AI should be treated as assistive enrichment rather than the primary source of
  truth.
- Good uses include:
  - transcription
  - image description
  - OCR
  - similarity matching
  - clustering suggestions
  - search enrichment
- Human correction and later structuring remain central.

## Usage

When a new design conversation materially changes project philosophy or the
interpretation of the project, add or update notes here and in the relevant
subproject folders.
