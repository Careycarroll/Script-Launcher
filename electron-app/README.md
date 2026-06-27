# ⚡ Script Launcher — Electron

The Electron frontend for Script Launcher. Provides a native macOS app with an embedded xterm.js terminal, a self-contained Python pipeline for document operations, and a live theme customization drawer.

---

## Why Electron

Two things the TUI and Wails GUI couldn't do:

1. **Embedded terminal.** Interactive scripts (`manage_vault`, `lecture_merge`) run inside the app window via xterm.js + node-pty, instead of spawning an external Terminal.
2. **Self-contained document pipeline.** Document operations run through a bundled Python venv with pymupdf, pikepdf, and Pillow — no Homebrew dependencies for `pdf_to_txt`, `pptx_to_pdf`, or `images_to_pdf`.

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
- **Microsoft PowerPoint** — required for `pptx_to_pdf` and `pptx_to_txt`

> External dependencies for document scripts (poppler, ghostscript) have been removed. All document operations run through bundled Python.

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
│   ├── App.jsx                  # UI — sidebar, args, terminal tab, theme drawer
│   ├── App.css
│   └── Terminal.jsx             # xterm.js panel
├── resources/
│   ├── bin/
│   │   └── ffmpeg
│   └── python/
│       ├── venv/                # Bundled interpreter + libraries
│       └── scripts/
│           └── docpipe.py       # Unified operation pipeline
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
│  ThemePanel — drawer + presets              │
│  window.electronAPI.*                       │
└────────────────┬────────────────────────────┘
                 │ contextBridge (preload.ts)
┌────────────────▼────────────────────────────┐
│  Main Process (Node.js)                     │
│  main.ts — IPC handlers                     │
│  node-pty — PTY management                  │
│  Runtime dispatch: 'python' or native       │
│  Operation name forwarded as first arg      │
│  resources/bin — PATH-prepended             │
└────────────────┬────────────────────────────┘
                 │ spawn
┌────────────────▼────────────────────────────┐
│  docpipe.py (Python venv)                   │
│  OPERATIONS registry + PIPELINES            │
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
- **⚙** — opens the theme drawer (see below)

Interactive scripts (e.g. `manage_vault`, `lecture_merge`) auto-switch to the Terminal tab.

## PDF Bookmarks

The **Documents → PDF Bookmarks** entry uses a two-stage in-app editor:

1. Pick a PDF and click **Analyze**
2. The detector runs `pdf_bookmark_analyze`, which tries embedded `/Outlines` first, then falls back to font-signature detection
3. Proposed bookmarks populate a textarea with a comment header showing the detection source
4. Edit the list (comments stripped on save), then click **Apply** to write `<stem>_bookmarked.pdf` + audit-trail `<stem>_bookmarks.txt`

The file picker collapses post-analysis so the textarea fills the panel. Use **← Change PDF** in the toolbar to restart with a different file.

---

## Theme

Click the **⚙** icon in the tab bar to open a slide-out drawer for live theme editing.

### Presets

| Preset | Vibe |
|---|---|
| **UNC Night** (default) | Carolina Blue + Tokyo Night |
| **Dracula** | Purple-on-charcoal with hot-pink + cyan accents |
| **Nord** | Cool blue-grey palette |

Clicking a preset applies all 14 variables at once and persists to `localStorage`.

### Per-variable editing

14 CSS variables across three groups (Backgrounds, Accents, Text). Each row has:
- Native color picker (instant preview)
- Hex text input (paste-friendly)
- ↺ Reset button (returns that variable to its `App.css` default)

### Persistence

Overrides are written to `localStorage["theme-overrides"]` as a `{varName: hex}` map and reapplied on app startup before first paint. "Reset all" clears the entire override map.

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
| `PtyCreate(scriptPath, args?)` | Spawns a script in the embedded terminal PTY; args are shell-quoted and appended to the command line |
| `PtyInput(data)` | Sends keystrokes to the active PTY |
| `PtyResize(cols, rows)` | Resizes the active PTY |
| `PtyKill()` | Kills the active PTY |
| `onPtyOutput(cb)` | Receives PTY output stream |
| `onPtyExit(cb)` | Notified when PTY process exits |
| `offPtyOutput()` | Removes all `pty-output` listeners |
| `offPtyExit()` | Removes all `pty-exit` listeners |

---

## docpipe.py

Single Python entry point for all document operations. Operations are named, registered in `OPERATIONS`, and chained via explicit `PIPELINES`. Same-format operations (e.g. `pdf_merge`, `pdf_strip`, `pdf_bookmark_add`) declare an `output_suffix` for stable naming (`_merged.pdf`, `_stripped.pdf`, `_bookmarked.pdf`) — re-running overwrites instead of incrementing.

### Operations registry

Each operation declares:

- A unique `name` (e.g. `pdf_to_txt`, `images_to_pdf`)
- Source and destination formats
- Input arity (`one` or `many`)
- Output arity (`one` or `many`)
- A list of options (each with choices + default)

Adding a new operation = one function + one registry entry. The CLI auto-discovers everything: flags, help text, `--list`, `--introspect`.

### Built-in operations

| Operation | Arity | Notes |
|---|---|---|
| `pdf_to_txt` | 1→1 | Options: `--pdf_to_txt-layout` (`layout` / `plain`) |
| `images_to_pdf` | N→1 | Options: `--images_to_pdf-page_size` (`auto` / `letter` / `a4`). `--out` required. |
| `pptx_to_pdf` | 1→1 | Options: `--pptx_to_pdf-compress` (`none` / `small` / `medium` / `large`). macOS + PowerPoint. |
| `pdf_merge` | N→1 | Concatenate PDFs with optional per-file bookmarks. Preserves first file's metadata. |
| `pdf_strip` | 1→1 | Strip info dict + XMP metadata. Output: `<stem>_stripped.pdf`. |
| `pdf_bookmark_analyze` | 1→stdout | Detect outlines or font-signature titles. Emits JSON for UI consumption. |
| `pdf_bookmark_add` | 1→1 | Write bookmarks from a `page:title` list. Output: `<stem>_bookmarked.pdf`. |

### Named pipelines

Pipelines compose operations explicitly:

```python
PIPELINES = {
  "pptx_to_txt": ["pptx_to_pdf", "pdf_to_txt"],
}
```

Calling `docpipe pptx_to_txt deck.pptx` runs both operations in order; the intermediate `.pdf` is kept (default) or discarded (`--no-keep-intermediate`).

### CLI

```bash
# Single operation
docpipe.py pdf_to_txt input.pdf

# Batch (1→1 operation looped over N inputs)
docpipe.py pdf_to_txt a.pdf b.pdf c.pdf

# Operation options
docpipe.py pdf_to_txt input.pdf --pdf_to_txt-layout plain
docpipe.py pptx_to_pdf deck.pptx --pptx_to_pdf-compress medium

# Named pipeline (defined in PIPELINES)
docpipe.py pptx_to_txt deck.pptx

# Explicit chain (anonymous pipeline)
docpipe.py --chain pptx_to_pdf,pdf_to_txt deck.pptx

# Output redirection
docpipe.py pdf_to_txt --out output.txt input.pdf       # single
docpipe.py pdf_to_txt --out-dir ~/out a.pdf b.pdf      # batch

# Multi-input (N→1)
docpipe.py images_to_pdf img1.png img2.png --out combined.pdf
docpipe.py images_to_pdf ~/scans/ --out scans.pdf

# Diagnostics
docpipe.py --list           # human-readable operations + pipelines
docpipe.py --introspect     # JSON: operations + extensions + options + pipelines
docpipe.py --dry-run ...    # show resolved chain, don't execute
docpipe.py --echo ...       # print received argv as JSON (pre-argparse)
```

### Conventions

- **stdout** = final output path(s), one per line. Parseable by callers.
- **stderr** = progress + errors.
- **Exit code**: `0` success, `1` user error, `2` per-file failure in batch.
- **Default naming**: `input.pdf → input.txt` beside the input.
- **Conflict resolution**: `_1`, `_2`, ... suffix unless `--force`.
- **Intermediates**: kept by default (`--keep-intermediate`); `--no-keep-intermediate` drops them.

### Per-operation option flags

Option flags are namespaced as `--{op_name}-{option_name}`. Examples:

- `--pdf_to_txt-layout`
- `--images_to_pdf-page_size`
- `--pptx_to_pdf-compress`

This guarantees no collisions when a pipeline includes two operations that happen to share an option name.

### Compression presets (`pptx_to_pdf`)

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
  "operation": "pdf_to_txt",
  "help": "Detail screen text.",
  "interactive": false,
  "argDefs": [
    { "label": "Input file", "filePicker": true, "extensions": ["pdf"] }
  ]
}
```

### How `runtime: "python"` + `operation` works

When the renderer runs a Python entry, `main.ts` builds the command line as:

```
<bundledPython> <docpipePath> <operation> <...argDefs flags + values>
```

The `operation` field is forwarded as the first positional arg to `docpipe.py`. The renderer never has to know which operation it's invoking — that's a property of the registry entry.

For named pipelines, set `operation` to the pipeline name (e.g. `"operation": "pptx_to_txt"`).

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
| `operation` | string | Top-level: operation or pipeline name passed to docpipe.py |
| `label` | string | Visible label above the widget |
| `flag` | string | CLI flag (e.g. `--pdf_to_txt-layout`); value appended after |
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

### Hidden boolean flag pattern

For `store_true`-style flags (e.g. `--echo`, `--force`, `--dry-run`), set `"default": true` (boolean, not string) and `"hidden": true`. The renderer emits the flag alone with no value:

```json
{ "flag": "--echo", "default": true, "hidden": true }
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
| docpipe.py | `resources/python/scripts/` | Unified operation pipeline |

The app prepends `resources/bin/` to `PATH` at startup — bundled tools are always found before system-installed versions.

---

## Backlog

- [ ] PDF Merge operation (N→1, pikepdf concat)
- [ ] PDF Split operation (1→N, by pages / ranges / bookmarks)
- [ ] PDF Metadata Strip operation
- [ ] PDF Bookmarks operation (heading-detect + manual list modes)
- [ ] Video Silence Trim operation (ffmpeg silencedetect + select/aselect)
- [ ] Wikilink Graph Export — standalone `vault_graph.py`
- [ ] Builder UI — drop a file, suggest operations + pipelines from introspection
- [ ] Lite / Full / AI build targets (`npm run make:lite|full|ai`)
- [ ] AI bundle: local whisper.cpp for audio/video transcription
- [ ] OS-aware architecture (`platform()` checks, config file for user paths)
- [ ] `txt_to_md` operation (deferred — low priority)
- [ ] `pdf_to_md` operation (deferred — would use `pymupdf4llm`)
- [ ] Auto-update via Electron Forge publisher
