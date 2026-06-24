# ⚡ Script Launcher — Electron

The Electron frontend for Script Launcher. Provides a native macOS app with an embedded xterm.js terminal and a self-contained Python pipeline for document conversion.

---

## Why Electron

Two things the TUI and Wails GUI couldn't do:

1. **Embedded terminal.** Interactive scripts (`manage_vault`, `lecture_merge`) run inside the app window via xterm.js + node-pty, instead of spawning an external Terminal.
2. **Self-contained document pipeline.** Document conversions run through a bundled Python venv with pymupdf, pikepdf, and Pillow — no Homebrew dependencies for `pdf → text`, `pptx → pdf`, or `images → pdf`.

---

## Stack

| Layer | Technology |
|---|---|
| UI | React + App.jsx / App.css |
| Terminal embedding | xterm.js + node-pty |
| Script execution | Node.js `child_process` / `spawn` |
| Registry | `registry.json` |
| Build / Package | Electron Forge + Vite |
| Bundled Python runtime | Python 3.13.5 standalone |
| Python libraries | pymupdf, pikepdf, Pillow |
| Bundled binary | ffmpeg (static, darwin-arm64) |

---

## Requirements

- **Node.js** 18+
- **npm** 9+
- **ffmpeg** static binary in `resources/bin/` — see Setup below
- **Microsoft PowerPoint** — required for PPTX → PDF and PPTX → Text

> External dependencies for document scripts (poppler, ghostscript) have been removed. All document conversion now runs through bundled Python.

---

## Setup

```bash
cd electron-app
npm install
```

### Download bundled ffmpeg (required, not in git)

```bash
mkdir -p resources/bin
curl -L "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip" -o /tmp/ffmpeg.zip
unzip /tmp/ffmpeg.zip -d /tmp/ffmpeg-static
cp /tmp/ffmpeg-static/ffmpeg resources/bin/ffmpeg
chmod +x resources/bin/ffmpeg
rm -rf /tmp/ffmpeg.zip /tmp/ffmpeg-static
```

### Set up bundled Python

```bash
uv venv resources/python/venv \
  --python /Users/careycarroll/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none/bin/python3

uv pip install pymupdf pikepdf pillow \
  --python "resources/python/venv/bin/python3"
```

---

## Running

### Development
```bash
npm start
```

Hot reload is enabled for `App.jsx`, `App.css`, and `renderer.tsx`. Changes to `main.ts` or `preload.ts` require a restart.

### Production Build
```bash
npm run make
```

Output: `electron-app/out/Script Launcher-darwin-arm64/Script Launcher.app`

---

## Project Structure

```
electron-app/
├── src/
│   ├── main.ts                  # Electron main process — IPC, PTY, spawn
│   ├── preload.ts               # Context bridge
│   ├── renderer.tsx
│   ├── App.jsx                  # UI — sidebar, args, terminal tab
│   ├── App.css
│   └── Terminal.jsx             # xterm.js panel
├── resources/
│   ├── bin/
│   │   └── ffmpeg
│   └── python/
│       ├── venv/                # Bundled interpreter + libraries
│       └── scripts/
│           └── docpipe.py       # Unified conversion pipeline
├── registry.json
├── index.html
├── forge.config.ts
├── vite.*.config.ts
└── package.json
```

---

## Architecture

```
┌─────────────────────────────────────────────┐
│  Renderer (React)                           │
│  App.jsx — sidebar, widgets, run/clear      │
│  Terminal.jsx — xterm.js                    │
│  window.electronAPI.*                       │
└────────────────┬────────────────────────────┘
                 │ contextBridge (preload.ts)
┌────────────────▼────────────────────────────┐
│  Main Process (Node.js)                     │
│  main.ts — IPC handlers                     │
│  node-pty — PTY management                  │
│  Runtime dispatch: 'python' or native       │
│  resources/bin — PATH-prepended             │
└────────────────┬────────────────────────────┘
                 │ spawn
┌────────────────▼────────────────────────────┐
│  docpipe.py (Python venv)                   │
│  Stage graph, BFS routing                   │
│  pymupdf  — text extraction, PDF assembly   │
│  pikepdf  — PDF object graph, image streams │
│  Pillow   — pixel manipulation              │
└─────────────────────────────────────────────┘
```

**Security:** `contextIsolation: true`, `nodeIntegration: false`. All system calls go through the IPC bridge in `preload.ts`.

**Architecture principle for Python:** right tool per layer. pymupdf for text and assembly, pikepdf for PDF object graph and image stream surgery, Pillow for pixel work. No single library tries to do everything.

---

## Tabs

- **Scripts** — sidebar + detail panel with widgets, file pickers, run buttons
- **Terminal** — full xterm.js terminal with live shell, always mounted

Interactive scripts (e.g. `manage_vault`, `lecture_merge`) auto-switch to the Terminal tab.

---

## IPC API

Exposed to the renderer via `window.electronAPI`:

| Method | Description |
|---|---|
| `GetGroups()` | Returns all script groups from registry.json |
| `RunScript(groupIdx, scriptIdx, args)` | Executes a script, returns `{ output, error }` |
| `PickFile(extensions?)` | Native file picker with optional extension filter |
| `PickFolder()` | Native folder picker |
| `PtyShell()` | Spawns default shell in the embedded terminal |
| `PtyCreate(scriptPath)` | Spawns a script in the embedded terminal PTY |
| `PtyInput(data)` | Sends keystrokes to the active PTY |
| `PtyResize(cols, rows)` | Resizes the active PTY |
| `PtyKill()` | Kills the active PTY |
| `onPtyOutput(cb)` | Receives PTY output stream |
| `onPtyExit(cb)` | Notified when PTY process exits |

---

## docpipe.py

Single Python entry point for all document conversions. Stage graph + BFS routing means new conversion edges are mechanical to add.

### Stage graph

```
pdf ───→ txt
images → pdf
pptx ──→ pdf
```

Chained paths are auto-routed. `pptx → txt` resolves to `pptx → pdf → txt` with no additional stage code.

### Conventions

- **stdout** = final output path(s), one per line. Parseable by callers.
- **stderr** = progress + errors.
- **Exit code**: `0` success, `1` user error, `2` per-file failure in batch.
- **Default naming**: `input.pdf → input.txt` beside the input.
- **Conflict resolution**: `_1`, `_2`, ... suffix unless `--force`.
- **Intermediates**: kept by default (`--keep-intermediate`); `--no-keep-intermediate` drops them.

### CLI

```bash
# Single conversion
docpipe.py --from pdf --to txt input.pdf

# Batch
docpipe.py --from pdf --to txt a.pdf b.pdf c.pdf

# Stage options
docpipe.py --from pdf --to txt --pdf-layout plain input.pdf
docpipe.py --from pptx --to pdf --pptx-compress medium deck.pptx

# Chained
docpipe.py --from pptx --to txt deck.pptx

# Output redirection
docpipe.py --from pdf --to txt --out output.txt input.pdf       # single
docpipe.py --from pdf --to txt --out-dir ~/out a.pdf b.pdf      # batch

# Multi-input (N → 1)
docpipe.py --from images --to pdf img1.png img2.png --out combined.pdf
docpipe.py --from images --to pdf ~/scans/ --out scans.pdf

# Diagnostics
docpipe.py --introspect       # JSON: graph + extensions + per-stage options
docpipe.py --dry-run ...      # Show the resolved chain, don't execute
docpipe.py --echo ...         # Print received argv as JSON (pre-argparse)
```

### Stages

| Stage | Options | Notes |
|---|---|---|
| `pdf → txt` | `--pdf-layout` (`layout` / `plain`) | Layout mode uses block-binning + x-padding to preserve columns |
| `images → pdf` | `--images-page-size` (`auto` / `letter` / `a4`) | N inputs → 1 PDF; `--out` required |
| `pptx → pdf` | `--pptx-compress` (`none` / `small` / `medium` / `large`) | AppleScript + PowerPoint; pikepdf-based image downsampling |

### Compression presets (`pptx → pdf`)

| Preset | DPI | Ghostscript equivalent | Typical reduction |
|---|---|---|---|
| `none` | — | — | PowerPoint raw export |
| `small` | 72 | `/screen` | ~65–70% smaller |
| `medium` | 150 (default) | `/ebook` | ~40% smaller |
| `large` | 300 | `/printer` | ~5–10% smaller |

Algorithm: walk every embedded image with pikepdf, compute effective DPI from CTM-derived display rect, downsample image+SMask in lockstep, re-encode (DCT for image, Flate for mask). Preserves alpha, dedupes by xref. No Ghostscript dependency.

---

## Registry

Edit `registry.json` and restart `npm start`.

### Minimal entry

```json
{
  "name": "My Script",
  "description": "Short description",
  "path": "python/scripts/docpipe.py",
  "runtime": "python",
  "help": "Detail screen text.",
  "interactive": false,
  "argDefs": [
    { "label": "Input file", "filePicker": true, "extensions": ["pdf"] }
  ]
}
```

### Widget types

The renderer dispatches on `def.type`. Falls back to existing dropdown/text behavior when `type` is absent.

| `type` | UI | Notes |
|---|---|---|
| _(omitted)_ + `options` | Dropdown | Existing behavior |
| _(omitted)_ + no options | Text input | Existing behavior |
| `checkbox` | Checkbox row with `checkboxLabel` text | Pairs with `invertFlag` for `--no-*` flags |
| `number` | Numeric input | Supports `min`, `max`, `step`. Empty input omits the flag. |
| `outputDir` | Text input + folder picker | Maps to `--out-dir` typically |

### Schema reference

| Field | Type | Purpose |
|---|---|---|
| `label` | string | Visible label above the widget |
| `flag` | string | CLI flag (e.g. `--pdf-layout`); value appended after |
| `default` | string / number / boolean | Default value |
| `options` | string[] | Dropdown choices |
| `filePicker` | bool | Show file picker button |
| `dirPicker` | bool | Show folder picker button |
| `multiFile` | bool | Render as queue, multi-input mode |
| `extensions` | string[] | Restrict pickers to these extensions |
| `hidden` | bool | Don't render but pass flag/value at runtime |
| `type` | string | Widget dispatch (see above) |
| `invertFlag` | bool | Checkbox: pass flag only when UNchecked |
| `min` / `max` / `step` | number | Number widget constraints |
| `checkboxLabel` | string | Text next to checkbox |
| `placeholder` | string | Input placeholder text |
| `tooltip` | string | Hover tooltip on `?` icon next to label |

### Hidden flag pattern

To bake `--from`/`--to` into a registry entry without showing them in the UI:

```json
{ "flag": "--from", "default": "pptx", "hidden": true },
{ "flag": "--to",   "default": "txt",  "hidden": true },
```

### Test entries

The `Developer` group exposes one entry per widget type, each calling `docpipe.py --echo` so the rendered output shows exactly what argv was passed. Useful when adding new widgets or debugging flag wiring.

---

## Bundled Resources

| Resource | Path | Purpose |
|---|---|---|
| ffmpeg | `resources/bin/ffmpeg` | Video processing (Lecture Merge) |
| Python 3.13.5 | `resources/python/venv/` | Document scripts |
| pymupdf | `resources/python/venv/lib/` | Text extraction, PDF assembly |
| pikepdf | `resources/python/venv/lib/` | PDF object graph, image streams |
| Pillow | `resources/python/venv/lib/` | Pixel manipulation |
| docpipe.py | `resources/python/scripts/` | Unified conversion pipeline |

The app prepends `resources/bin/` to `PATH` at startup — bundled tools are always found before system-installed versions.

---

## Backlog

- [ ] Group hiding (`"hidden": true` at group level) — hide Developer group from production view
- [ ] Builder UI — drop a file, surface suggested conversion chains from the introspection graph
- [ ] Lite build — ephemeral dependency downloads with consent dialog + cleanup
- [ ] Full build — all binaries bundled, single distributable
- [ ] Two build targets: `npm run make:lite` and `npm run make:full`
- [ ] Theme customization panel (CSS variable editor, persisted to localStorage)
- [ ] OS-aware architecture (`platform()` checks, config file for user paths)
- [ ] `txt → md` stage (deferred — low priority)
- [ ] `pdf → md` stage (deferred — low priority, would use `pymupdf4llm`)
- [ ] Auto-update via Electron Forge publisher
