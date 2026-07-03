# ADR-0005: Vault Workbench architecture — long-lived indexer + react-force-graph

- **Date:** 2026-07-03
- **Status:** Accepted
- **Deciders:** Carey Carroll

## Context

Vault Workbench (#1) is the second domain tile in the launchpad-restructured
Electron app. It needs to parse an Obsidian vault (~1544 notes at time of
writing), extract structure (wikilinks, embeds, tags, orphans, broken links,
hubs, components), and present it as a navigable graph with side panels.

Several architectural questions need answers before code lands:

1. Where does the parsing logic live? Standalone Python script, Node.js
   module in main.ts, or an embedded library inside docpipe.py?
2. How does the UI stay responsive when reindexing a 1500-note vault?
   Long-lived child process with IPC, or spawn per-query?
3. How is the graph rendered? react-force-graph, Cytoscape, D3 from scratch,
   or something else?
4. How are Obsidian-specific quirks handled — iCloud offloading, YAML
   frontmatter variants, wikilink aliases, embed vs. link, section anchors?

The vault is stored in iCloud Drive, which introduces file-offloading
behavior that a naive `os.walk` won't handle correctly.

## Decision

Vault Workbench is built in three phases, each their own PR:

1. **`vault_index.py`** — standalone Python script that walks a vault
   directory and emits a single JSON index (notes, edges, metrics) on stdout.
   Runs as a one-shot process. Testable via CLI.
2. **Long-lived mode** — same script gains a `--serve` flag that keeps it
   alive, reading commands from stdin and writing responses to stdout as
   line-delimited JSON. Simpler than JSON-RPC 2.0; sufficient for the
   query shapes needed (reindex, get_note, get_backlinks, get_similar).
3. **Electron Vault tile** — spawns `vault_index.py --serve` on tile mount,
   sends queries over the pipe, renders the graph with **react-force-graph**
   and side panels.

Parser handles Obsidian-specific quirks explicitly:

- YAML frontmatter via **pyyaml** (added to the bundled venv).
- Wikilink regex: `[[Target]]`, `[[Target|alias]]`, `[[Target#section]]`
  variants; alias and section-anchor stripped for edge purposes.
- Section-only links (`[[#section]]`) filtered out — in-page navigation,
  not edges to other notes.
- Embed syntax (`![[X]]`) parsed separately from wikilinks; further
  distinguished by target extension: `.md` = note embed (edge to a note),
  anything else = asset embed (image/PDF reference, not a note edge).
- Callouts (`> [!Note] Title`) treated as ordinary markdown — wikilinks
  inside a callout are extracted like any other. No special-casing.
- Index files (prefix `_`, e.g. `_Global Context of Business.md`) excluded
  by default per the existing Vault Health convention. `--include-index-files`
  opts in.
- iCloud offloading handled by running `brctl download <vault-path>` before
  the walk, forcing any offloaded files to materialize. `--skip-download`
  opts out.

Full re-index runs on every reindex request; no file-watching or incremental
updates. At 1544 notes, full reindex is fast enough (<1s expected) that
incremental complexity isn't worth building.

## Alternatives considered

### Node.js parser in main.ts

Would eliminate the Python subprocess and simplify the IPC surface. Rejected
because (a) Python is already the docpipe pattern, (b) pyyaml is more mature
than any JS YAML library for edge cases, and (c) main.ts should stay thin —
domain logic belongs in scripts, not in the process supervisor.

### JSON-RPC 2.0 for long-lived mode

Standardized, tooling exists. Rejected because it's overkill for a
single-client, single-server pipe with 4-5 query shapes. Line-delimited JSON
with `{id, method, params}` and `{id, result | error}` is 90% of JSON-RPC's
value in 10% of the code.

### File-watching + incremental reindex

Would keep the graph "live" as the user edits notes in Obsidian. Rejected
for v1 because (a) explicitly out of scope per the issue, (b) requires
watchdog or similar Python library, (c) full reindex at this vault size is
fast enough that watching adds complexity for no perceptible latency
benefit. Reconsidered later if vault grows past ~10k notes.

### Cytoscape.js for the graph

More mature than react-force-graph, richer layout options. Rejected because
react-force-graph is React-idiomatic (`<ForceGraph2D nodes={...} links={...} />`),
sufficient for the visualization needs, and cheaper to integrate. Cytoscape
is a viable fallback if react-force-graph performance disappoints on the
full vault.

### Docpipe operation instead of standalone script

Register vault_index as `OPERATIONS["vault_index"]` and invoke it through
docpipe.py like every other Python entry. Rejected because vault_index is
genuinely a different tool with a different lifecycle (long-lived, IPC-driven)
than docpipe's one-shot operations. Forcing it through docpipe adds
indirection for no benefit. Runs as `python3 vault_index.py <path>` directly.

## Consequences

### Positive

- Standalone Python script is testable via CLI without the Electron app.
- Long-lived process keeps subsequent queries fast (no cold-start).
- pyyaml added to the bundled venv is useful for any future Python code
  that touches YAML — one-time cost, general benefit.
- react-force-graph carries most of the graph complexity as a dependency;
  Vault Workbench code stays focused on data shape and interaction, not
  layout math.

### Negative

- `pyyaml` adds ~500KB to the bundled venv.
- iCloud offloading assumption (`brctl download`) is macOS-specific and
  couples this feature to the OS. Future OS-aware architecture work (#7)
  will need to address platform-specific paths — deferred until then.
- Long-lived process needs lifecycle management in main.ts: spawn on tile
  mount, kill on unmount, respawn on config change (vault path).

### Neutral

- Docpipe registry pattern is not used for this script. First time an
  Electron Python entry hasn't been a docpipe operation. Sets a precedent
  that "standalone Python scripts are allowed" — worth being deliberate
  about not letting this pattern proliferate for one-shot operations that
  belong in docpipe.

## Notes

- Related issues: #1 (Vault Workbench feature), #50 (component field
  refactor — Vault tile will use the `component` field), #51 (terminal
  migration — parallel work).
- Related ADRs: ADR-0003 (launchpad + tiles), ADR-0004 (AI runtime
  strategy — future vault chat/RAG will build on the same index).
- Build order per the issue and this ADR:
  1. `vault_index.py` standalone with CLI (this PR sequence)
  2. Long-lived `--serve` mode (next)
  3. Electron Vault tile skeleton + IPC bridge
  4. Metrics report view
  5. Graph canvas (react-force-graph)
  6. Side panels (note content, backlinks, similar-by-tags)
  7. Filters + queries + exports