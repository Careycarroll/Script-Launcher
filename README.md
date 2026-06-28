# ⚡ Script Launcher

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![tests](https://github.com/Careycarroll/Script-Launcher/actions/workflows/tests.yml/badge.svg)](https://github.com/Careycarroll/Script-Launcher/actions/workflows/tests.yml)

A multi-interface script launcher for macOS — three frontends, two registries. Add a script once in `registry/registry.go` (TUI + GUI) or `electron-app/registry.json` (Electron) and it appears in that frontend.

---

## Frontends

| Frontend     | Stack                       | Use Case                                                      |
| ------------ | --------------------------- | ------------------------------------------------------------- |
| **TUI**      | Go + Bubble Tea             | Terminal sessions, SSH, lightweight                           |
| **GUI**      | Go + Wails + React          | Native-feeling app, file pickers, quick access                |
| **Electron** | Electron + React + xterm.js | Embedded terminal, bundled Python pipeline, live theme drawer |

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
│   │           └── docpipe.py # Unified operation pipeline
│   ├── registry.json
│   └── package.json
├── go.mod
└── go.sum
```

---

## Requirements

### All Frontends

- **ffmpeg** — `brew install ffmpeg` (Lecture Merge) — bundled in Electron full build
- **Microsoft PowerPoint** — required for PPTX-related operations

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

| Key                    | Action                  |
| ---------------------- | ----------------------- |
| `↑` / `↓` or `j` / `k` | Navigate scripts        |
| `Enter`                | Select / confirm        |
| `f`                    | Open file picker        |
| `d`                    | Open folder picker      |
| `←` / `→`              | Cycle through options   |
| `Backspace`            | Remove last queued file |
| `Esc` / `b`            | Go back                 |
| `q`                    | Quit                    |

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

See [`electron-app/README.md`](electron-app/README.md) for setup, architecture, the `docpipe.py` operation pipeline, and the theme customization drawer.

---

## Scripts

### Vault

| Script           | Frontends            | Description                                               |
| ---------------- | -------------------- | --------------------------------------------------------- |
| **Manage Vault** | TUI / GUI / Electron | Full vault management TUI — launches in a Terminal window |
| **Vault Health** | TUI / GUI / Electron | Scan vault for broken wikilinks and orphaned notes        |

`Add Vault Link` and `Cleanup Vault Tools` are TUI/GUI-only — local-machine workflow, not bundled into Electron.

### Video

| Script            | Description                                                  |
| ----------------- | ------------------------------------------------------------ |
| **Lecture Merge** | Merge 3 Panopto lecture recordings into a single clean video |

### Documents

TUI and GUI use local Homebrew tools (pdftotext, ghostscript). Electron runs everything through bundled `docpipe.py` — a single Python entry point with an operations-based architecture.

| Script                 | Operation / Pipeline                        | Description                                                       |
| ---------------------- | ------------------------------------------- | ----------------------------------------------------------------- |
| **PDF → Text**         | `pdf_to_txt`                                | Extract text from PDFs with column/table layout reconstruction    |
| **Images → PDF**       | `images_to_pdf`                             | Combine images into a single PDF (per-image or fixed page size)   |
| **PPTX → PDF**         | `pptx_to_pdf`                               | Convert PowerPoint to PDF with image downsampling presets         |
| **PPTX → Text**        | `pptx_to_txt` (pipeline)                    | Chained `pptx_to_pdf → pdf_to_txt` in one step                    |
| **PDF Merge**          | `pdf_merge`                                 | Concatenate PDFs with optional per-file bookmarks                 |
| **PDF Strip Metadata** | `pdf_strip`                                 | Remove info dict + XMP for clean sharing                          |
| **PDF Bookmarks**      | `pdf_bookmark_analyze` + `pdf_bookmark_add` | Two-stage detect/edit/apply for navigating large PDFs             |
| **PDF Split**          | `pdf_split`                                 | Split by range, every N pages, or at bookmarks (with audit trail) |

Each operation declares format + arity. Pipelines are explicit named sequences in `docpipe.py`. New operations slot in by registering a function in `OPERATIONS` — the CLI, introspection JSON, and registry plumbing pick them up automatically.

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
  "operation": "pdf_to_txt",
  "help": "Detail screen text.",
  "interactive": false,
  "argDefs": [
    { "label": "Input file", "filePicker": true, "extensions": ["pdf"] },
    {
      "label": "Layout",
      "flag": "--pdf_to_txt-layout",
      "default": "layout",
      "options": ["layout", "plain"]
    }
  ]
}
```

### Arg Field Reference

| Field               | Purpose                                                                      |
| ------------------- | ---------------------------------------------------------------------------- |
| `operation`         | Top-level field for Python entries: operation or pipeline name               |
| `filePicker`        | Opens a file picker dialog                                                   |
| `dirPicker`         | Opens a folder picker dialog                                                 |
| `setWorkDir`        | Sets selected path as the script's working directory (TUI/GUI)               |
| `multiFile`         | Enables a file/folder queue (multiple inputs)                                |
| `batchArgs`         | Passes all queued files as args in one script call                           |
| `options`           | Renders a dropdown / left-right selector                                     |
| `flag`              | Prepends a flag before the value (e.g. `--pdf_to_txt-layout`)                |
| `interactive`       | Launches script in embedded terminal (Electron) or Terminal window (TUI/GUI) |
| `extensions`        | Restricts file picker to listed extensions (Electron)                        |
| `hidden`            | Don't render in UI; flag/value still passed (Electron)                       |
| `type: "checkbox"`  | Boolean widget (Electron)                                                    |
| `type: "number"`    | Numeric widget with optional `min`, `max`, `step` (Electron)                 |
| `type: "outputDir"` | Folder picker labeled for output, maps to `--out-dir` (Electron)             |
| `invertFlag`        | For checkboxes: pass flag only when UNchecked (for `--no-*` flags)           |
| `tooltip`           | Hover tooltip rendered as `?` icon on the label (Electron)                   |

For `store_true`-style hidden flags (e.g. `--echo`), use `"default": true` (boolean) and `"hidden": true`. The renderer will emit the flag alone with no value.

---

## Palette

UNC Carolina Blue `#4B9CD3` and Navy `#13294B` paired with Tokyo Night. The Electron frontend ships a live theme drawer (⚙ icon) with per-variable editing and three built-in presets (UNC Night, Dracula, Nord).

| Token            | Hex       | Usage                          |
| ---------------- | --------- | ------------------------------ |
| `--bg-deep`      | `#0d1117` | Sidebar background             |
| `--bg-surface`   | `#1a2744` | Main panel                     |
| `--unc-blue`     | `#4B9CD3` | Primary buttons, active states |
| `--tokyo-green`  | `#9ece6a` | Success                        |
| `--tokyo-red`    | `#f7768e` | Error                          |
| `--tokyo-orange` | `#ff9e64` | Running / warning              |

---

## Backlog

Active work and proposed features live in [GitHub Issues](https://github.com/Careycarroll/Script-Launcher/issues).

Current focus:

- **v0.5 — Vault Workbench** — launchpad restructure + vault analysis tile
- **v0.6 — Video Silence Trim** — ffmpeg-based silence detection operation
