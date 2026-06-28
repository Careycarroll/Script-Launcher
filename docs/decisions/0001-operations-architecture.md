# ADR-0001: Operations architecture for docpipe.py

- **Date:** 2026-06-15 (retroactive)
- **Status:** Accepted
- **Deciders:** Carey Carroll

## Context

The Electron frontend originally invoked Python scripts directly per operation
(separate scripts for PDF-to-text, images-to-PDF, etc.). Adding a new operation
meant: writing a script, wiring it into the Electron main process, adding a
registry entry, and wiring argument flags by hand. Errors crept in around flag
naming, file output paths were inconsistent, and there was no machine-readable
description of what operations existed.

I needed a structure that would let me add operations without touching the
Electron main process, would self-describe to the renderer for UI hints, and
would support both single operations and named pipelines (e.g., PPTX → PDF →
text).

## Decision

Consolidate all document operations into a single `docpipe.py` entry point with:

- An `OPERATIONS` registry of named operations declaring source format,
  destination format, input arity (`one` or `many`), output arity, and options.
- A `PIPELINES` registry mapping pipeline names to ordered lists of operations.
- Namespaced per-operation flags (`--{op}-{option}`) to prevent collisions when
  pipelines compose operations sharing option names.
- `--list` and `--introspect` flags for human-readable and JSON-formatted
  diagnostics, consumable by the Electron renderer.
- Stable output naming via `output_suffix` declarations (`_merged.pdf`,
  `_stripped.pdf`) so re-running overwrites instead of incrementing.

## Alternatives considered

### One Python script per operation
Original approach. Easier to add a new operation in isolation. Rejected because
it scaled poorly: every new operation required changes in three places (Python,
Electron main, registry.json) and there was no central place to introspect what
operations existed.

### Plugin architecture with entry-point discovery
Each operation as its own pip-installable package. Considered briefly. Rejected
as over-engineering for a personal tool with a known operation set. The
registry-of-functions approach gives 90% of the benefit at 5% of the complexity.

### Use an existing tool (Pandoc, etc.) as the dispatcher
Pandoc handles some of these conversions but not all (PDF bookmark manipulation,
image-stream compression). Mixing Pandoc with custom Python would be worse than
just writing the custom Python and owning the whole pipeline.

## Consequences

### Positive
- Adding a new operation = one function + one registry entry. The CLI,
  introspection, and UI plumbing pick it up automatically.
- Single source of truth for what operations exist.
- Pipelines compose explicitly, with intermediate file handling controlled by
  flags (`--keep-intermediate` / `--no-keep-intermediate`).
- The Electron renderer never has to know about specific operations — it
  reads `--introspect` and renders.

### Negative
- `docpipe.py` is now a large single file (~800 lines). Could be split into
  modules later if it grows further.
- Adding a non-document operation (e.g., video processing) doesn't fit cleanly
  in the current `src`/`dst` format taxonomy. May need to evolve when Video
  Silence Trim (#2) lands.

### Neutral
- Removed dependency on poppler and ghostscript for the Electron frontend —
  document operations now run entirely through bundled Python. See ADR-0002.

## Notes

Shipped in v0.4.0. See `CHANGELOG.md`.
