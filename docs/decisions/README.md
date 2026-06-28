# Architecture Decision Records

Significant decisions affecting the project's structure are documented here as
short markdown files. Each captures the context, the decision, the alternatives
considered, and the consequences.

## Format

Loosely follows [MADR](https://adr.github.io/madr/). See `0000-template.md`.

## Index

- [ADR-0001 — Operations architecture for docpipe.py](0001-operations-architecture.md)
- [ADR-0002 — Bundle Python runtime instead of using system dependencies](0002-bundled-python-runtime.md)
- [ADR-0003 — Launchpad + domain tiles structure for Electron app](0003-launchpad-domain-tiles.md)

## When to write a new ADR

- Significant change to the project's architecture
- A decision that has clear alternatives and tradeoffs worth recording
- Something future-you (or a collaborator) would want context on

Skip ADRs for: code style, individual bug fixes, refactors that don't change
the system's shape.
