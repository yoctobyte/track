# TRACK Philosophy

## Core idea

`TRACK` is an archival reverse-engineering system for real-world technical
environments, seen from the perspective of a technical administrator.

It is meant to help document, understand, organize, and eventually act on the
technical reality of a place.

That can include:

- rooms
- cabinets
- racks
- devices
- displays
- cables
- labels
- manuals
- network topology
- notes from staff
- procedures
- obscure operational context

## What kind of system this is

TRACK is not primarily:

- an asset tracker
- a wiki
- a CMDB
- a remote-control dashboard
- a network scanner

It may borrow from all of those, but the intended shape is closer to:

**a capture-first operational memory and documentation system**

The system should preserve raw observations first, and only then gradually turn
them into structure, relationships, maps, and possible control.

## Capture first

Reality is messy.

So the first priority is making it easy to capture evidence:

- take a photo
- upload a document
- record a voice note
- attach metadata if available
- scan an identifier or marker if present

The system should still be useful on day one, before everything is neatly
classified.

## Archival before inference

Each input should first become a durable archival observation.

Only later should the system infer things like:

- what it likely depicts
- how it relates to other observations
- where it belongs
- what changed over time
- how it fits into a larger technical structure

Inference should enrich the archive, not replace it.

## Reverse-engineering as a practice

The project is about reverse-engineering a technical environment as it actually
exists, not as documentation claims it exists.

That means:

- we gather evidence from the field
- we tie pieces together over time
- we discover structure rather than assuming it is already known

This is especially important in environments where:

- ownership is unclear
- devices have inconsistent naming
- wiring is messy
- vendor boundaries are blurry
- procedures live in people’s heads
- the same place changes over time

## Spatial and temporal unification

The long-term vision is not just a database of notes and photos.

The aim is to tie observations together in:

- **space**
- **time**

For `map3d`, this means an approximate 3D virtual representation of real
places, even if imperfect.

For TRACK as a whole, it means:

- knowing where things are
- understanding how things relate physically and operationally
- documenting how they change over time

Imperfect spatial reconstruction is still valuable if it improves orientation,
memory, and future documentation.

## Modular system, not one monolith

TRACK should grow as a system of related tools or kits, not as one giant
undifferentiated application.

Likely examples:

- capture
- mapping
- vision
- audio
- linking
- control
- network discovery

The shared model matters more than forcing everything into one UI too early.

## Control is part of the picture, not the whole picture

Remote actions matter, but only as part of a larger knowledge system.

Examples:

- managing media players
- network scanning
- Ansible-driven control
- remote procedures

These belong in TRACK, but they should connect back to documented entities,
locations, observations, and history.

## Practical design standard

The design center is:

**What is the simplest workflow that makes someone actually use this every day?**

If a workflow is too rigid to use during real fieldwork, it is wrong, even if
it is technically elegant.

If a rough but direct workflow captures reality and can be improved later, it
is probably right.
