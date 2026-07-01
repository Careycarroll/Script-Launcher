# ADR-0003: Launchpad + domain tiles structure for Electron app

- **Date:** 2026-06-28
- **Status:** Accepted
- **Deciders:** Carey Carroll

## Context

The Electron app started as "Script Launcher" — a sidebar of script groups
(Vault, Video, Documents) with a generic widget-based detail panel. This works
well for simple per-script operations rendered from a registry.

Two pressures are pushing the structure to evolve:

1. **PDF Bookmarks** already needed a custom two-stage UI that doesn't fit the
   generic widget renderer. Vault Workbench (#1) will need a graph canvas +
   side panels — a much bigger departure from the generic UI. Video Silence
   Trim (#2) will need a waveform / segment-list preview. Each new "interesting"
   feature is going to outgrow the generic chassis.
2. The current navigation surface (Scripts tab / Terminal tab / ⚙ icon) does
   three different things with three different behaviors. Adding Vault as a
   fourth tab would compound the inconsistency — Vault is not a view toggle,
   it's a different application.

I needed to decide whether to (a) keep adding tabs to Script Launcher and let
each feature compromise to fit, or (b) acknowledge that the Electron app is
becoming an umbrella of distinct tools and restructure accordingly.

## Decision

Restructure the Electron app as a **launchpad of domain tiles**:

- **Launchpad** (route `/`) — grid of tiles, one per domain.
- **Domain tiles** — Documents, Vault, Media. Each tile owns its workspace UI.
  - Simple operations within a tile use the existing generic widget renderer.
  - Bespoke flows (PDF Bookmarks, Vault graph, Video Silence Trim preview)
    live as dedicated components inside their tile.
- **Registry change** — each entry gains a `domain` field. Domain tiles
  consume the registry filtered by domain.
- Theme drawer (⚙) stays globally accessible. Terminal tab retires as a
  global concept and may reappear inside the Media or Documents tile if
  needed.

This treats the Electron app as "Carey's Workbench" with multiple tools under
one roof, rather than "Script Launcher with stuff bolted on."

## Alternatives considered

### Keep "Script Launcher" as-is, add Vault as a fourth top-level tab
Simplest. Rejected because Vault doesn't fit the current tab model (Scripts
swaps the detail panel; Terminal swaps the output region; ⚙ opens a drawer;
Vault would need full-window takeover, a fourth distinct behavior).
Also rejected because each future tool would face the same problem.

### Treat Vault as a "script" in the existing Scripts UI, render via a custom
### registry mode (`mode: "view"`) that routes to a dedicated screen
Considered seriously. Has the appeal of keeping the registry as the single
launch surface. Rejected because it overloads the registry concept — registry
entries imply "run a thing with args and show output," and view-mode entries
break that contract. Also doesn't address the underlying issue that the
generic widget renderer can't host bespoke flows well.

### Spin up Vault Workbench as a separate Electron app
Clean separation of concerns. Rejected because: (a) shared theme drawer
becomes harder to maintain across apps; (b) launching two apps to do two
related things is worse UX than one app with two surfaces; (c) the existing
infrastructure (registry, IPC, bundled Python) genuinely is shared.
Reconsidered later if Vault grows enough to warrant it.

### Build a launchpad but keep tiles as "tools" (Script Launcher | Vault)
rather than as "domains" (Documents | Vault | Media)
Considered. Rejected because the tools-as-tiles model preserves the awkward
internal structure of Script Launcher (a sidebar of groups) inside one of the
tiles, while domains-as-tiles is honest about the work being domain-focused.
The current "Vault | Video | Documents" sidebar groups become the tiles
themselves.

## Consequences

### Positive
- Each domain tile can have a UI shape that matches the domain. Documents
  uses widgets. Vault uses a graph canvas. Media will use a timeline preview.
  No tile compromises to share chrome with the others.
- Clear identity: "Carey's Workbench" hosts tools. Tools earn their own tile
  by being substantial.
- The registry remains the source of truth for operations but its UI role
  shifts — it's an operations catalog, filtered and rendered per domain.
- Future tools slot in cleanly as new tiles.

### Negative
- Real refactor required: existing Scripts UI becomes the Documents tile;
  Terminal tab moves into Media (or a tool-specific surface); routing layer
  needs to be added.
- "Script Launcher" stops being the product name for the Electron app.
  Naming TBD — likely "Workbench" or similar. Repo keeps the
  `Script-Launcher` name for continuity with the TUI/GUI.
- One additional navigation step on app launch (launchpad → tile) vs. the
  current direct-into-Scripts model. Mitigation: remember last-used tile
  and auto-route to it after a delay, with a back-to-launchpad shortcut.

### Neutral
- The TUI and Wails GUI are unaffected (they're frozen test beds, not part
  of this refactor).
- ⚙ theme drawer remains globally available across all tiles.

## Notes

- Blocks: Vault Workbench (#1) depends on this restructure.
- Related issue: #3 (Launchpad + domain tiles restructure).
- The original conversation that led to this decision happened on 2026-06-28
  during the engineering-hygiene work (Lessons 1–6). Without an ADR, the
  reasoning would have lived only in chat context.
