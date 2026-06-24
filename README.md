# ⚡ Script Launcher

A multi-interface script launcher for macOS — three frontends, two registries. Add a script once in `registry/registry.go` (TUI + GUI) or `electron-app/registry.json` (Electron) and it appears in that frontend.

---

## Frontends

| Frontend | Stack | Use Case |
|---|---|---|
| **TUI** | Go + Bubble Tea | Terminal sessions, SSH, lightweight |
| **GUI** | Go + Wails + React | Native-feeling app, file pickers, quick access |
| **Electron** | Electron + React + xterm.js | Embedded terminal, bundled Python pipeline |

TUI and GUI share `registry/registry.go` and call out to local scripts in `~/bin`. Electron has its own `registry.json` and bundles a Python venv for document processing — fully self-contained, no Homebrew dependencies for the document scripts.

---

## Project Structure

```
Script-Launcher/
├── registry/
│   └── registry.go            # TUI + GUI shared registry
├── tui/
│   └── main.go
├── gui/
│   ├── app.go
│   ├── main.go
│   └── frontend/...
├── electron-app/
│   ├── src/
│   │   ├── main.ts            # Electron main process
│   │   ├── preload.ts
│   │   ├── renderer.tsx
│   │   ├── App.jsx
│   │   ├── App.css
│   │   └── Terminal.jsx
│   ├── resources/
│   │   ├── bin/
│   │   │   └── ffmpeg         # Static binary (not in git)
│   │   └── python/
│   │       ├── venv/          # Python 3.13.5 + pymupdf + pikepdf + Pillow
│   │       └── scripts/
│   │           └── docpipe.py # Unified conversion pipeline
│   ├── registry.json
│   └── package.json
├── go.mod
└── go.sum
```

---

## Requirements

### All Frontends
- **ffmpeg** — `brew install ffmpeg` (Lecture Merge) — bundled in Electron full build
- **Microsoft PowerPoint** — required for PPTX-related conversions

### TUI + GUI
- **pdftotext** — `brew install poppler` (PDF → Text)
- **Ghostscript** — `brew install ghostscript` (PPTX → PDF compression)
- **Go** 1.22+
- **Wails** v2 — `go install github.com/wailsapp/wails/v2/cmd/wails@latest`
- **Node.js** (managed by Wails)

### Electron
- **Node.js** 18+
- **npm** 9+
- See [`electron-app/README.md`](electron-app/README.md) for full setup
- No poppler or ghostscript needed — document scripts run through bundled Python

---

## TUI

```bash
go run ./tui/
```

Build standalone binary:
```bash
go build -o scripttui ./tui/
./scripttui
```

### Navigation

| Key | Action |
|---|---|
| `↑` / `↓` or `j` / `k` | Navigate scripts |
| `Enter` | Select / confirm |
| `f` | Open file picker |
| `d` | Open folder picker |
| `←` / `→` | Cycle through options |
| `Backspace` | Remove last queued file |
| `Esc` / `b` | Go back |
| `q` | Quit |

---

## GUI (Wails)

```bash
cd gui && wails dev        # Development with hot reload
cd gui && wails build      # Production .app bundle
```

Output: `gui/build/bin/gui.app`

---

## Electron

```bash
cd electron-app && npm start    # Development
cd electron-app && npm run make # Package as .app
```

See [`electron-app/README.md`](electron-app/README.md) for setup, architecture, and the `docpipe.py` conversion pipeline.

---

## Scripts

### Vault

| Script | Frontends | Description |
|---|---|---|
| **Manage Vault** | TUI / GUI / Electron | Full vault management TUI — launches in a Terminal window |
| **Vault Health** | TUI / GUI / Electron | Scan vault for broken wikilinks and orphaned notes |

`Add Vault Link` and `Cleanup Vault Tools` are TUI/GUI-only — local-machine workflow, not bundled into Electron.

### Video

| Script | Description |
|---|---|
| **Lecture Merge** | Merge 3 Panopto lecture recordings into a single clean video |

### Documents

TUI and GUI use local Homebrew tools (pdftotext, ghostscript). Electron runs everything through bundled `docpipe.py` — a single Python entry point with a stage-graph architecture.

| Script | Description |
|---|---|
| **PDF → Text** | Extract text from PDFs with column/table layout reconstruction |
| **Images → PDF** | Combine images into a single PDF (per-image or fixed page size) |
| **PPTX → PDF** | Convert PowerPoint to PDF with image downsampling presets |
| **PPTX → Text** | Chained PPTX → PDF → Text in one step (Electron only) |

Conversion graph in `docpipe.py`:
- `pdf → txt`
- `images → pdf`
- `pptx → pdf`

Chained paths are auto-routed via BFS — `pptx → txt` resolves to `pptx → pdf → txt` with no extra stage code.

---

## Adding a New Script

### TUI + GUI
Edit `registry/registry.go` — add a `Script{}` block to an existing group or create a new one:

```go
{
    Name:        "My Script",
    Description: "Short description shown in the menu",
    Path:        "/Users/careycarroll/bin/my_script",
    Help:        "Longer description shown on the detail screen.",
    ArgDefs: []Arg{
        {Label: "Input file", FilePicker: true},
        {Label: "Mode", Default: "fast", Options: []string{"fast", "slow", "verbose"}},
    },
},
```

### Electron
Edit `electron-app/registry.json`. Full widget reference in [`electron-app/README.md`](electron-app/README.md). Example:

```json
{
  "name": "My Script",
  "description": "Short description",
  "path": "python/scripts/docpipe.py",
  "runtime": "python",
  "help": "Detail screen text.",
  "interactive": false,
  "argDefs": [
    { "label": "Input file", "filePicker": true, "extensions": ["pdf"] },
    { "label": "Mode", "default": "fast", "options": ["fast", "slow"] }
  ]
}
```

### Arg Field Reference

| Field | Purpose |
|---|---|
| `filePicker` | Opens a file picker dialog |
| `dirPicker` | Opens a folder picker dialog |
| `setWorkDir` | Sets selected path as the script's working directory (TUI/GUI) |
| `multiFile` | Enables a file/folder queue (multiple inputs) |
| `batchArgs` | Passes all queued files as args in one script call |
| `options` | Renders a dropdown / left-right selector |
| `flag` | Prepends a flag before the value (e.g. `-c ebook`) |
| `interactive` | Launches script in embedded terminal (Electron) or Terminal window (TUI/GUI) |
| `extensions` | Restricts file picker to listed extensions (Electron) |
| `hidden` | Don't render in UI; flag/value still passed (Electron) |
| `type: "checkbox"` | Boolean widget (Electron) |
| `type: "number"` | Numeric widget with optional `min`, `max`, `step` (Electron) |
| `type: "outputDir"` | Folder picker labeled for output, maps to `--out-dir` (Electron) |
| `invertFlag` | For checkboxes: pass flag only when UNchecked (for `--no-*` flags) |
| `tooltip` | Hover tooltip rendered as `?` icon on the label (Electron) |

---

## Palette

UNC Carolina Blue `#4B9CD3` and Navy `#13294B` paired with Tokyo Night.

| Token | Hex | Usage |
|---|---|---|
| `--bg-deep` | `#0d1117` | Sidebar background |
| `--bg-surface` | `#1a2744` | Main panel |
| `--unc-blue` | `#4B9CD3` | Primary buttons, active states |
| `--tokyo-green` | `#9ece6a` | Success |
| `--tokyo-red` | `#f7768e` | Error |
| `--tokyo-orange` | `#ff9e64` | Running / warning |

---

## Backlog

- [ ] Electron — group hiding (`"hidden": true` at the registry group level) for Developer test group
- [ ] Electron — builder UI: drop a file, see suggested conversion chains from the introspection graph
- [ ] Electron — Lite build with ephemeral dependency downloads + consent dialog
- [ ] Electron — Full build with all binaries bundled
- [ ] Electron — two build targets: `npm run make:lite` and `npm run make:full`
- [ ] Electron — theme customization panel (CSS variable editor)
- [ ] Electron — OS-aware architecture (`platform()` checks, config file for user paths)
- [ ] Electron — `txt → md` stage (deferred — low priority)
- [ ] Electron — `pdf → md` stage (deferred — low priority, would use `pymupdf4llm`)
- [ ] qpdf — bookmark creation script
- [ ] manage_vault — restore key hints below menu options
