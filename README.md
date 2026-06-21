# ⚡ Script Launcher

A multi-interface script launcher for macOS — three frontends, one registry. Add a script once in `registry/registry.go` and it appears everywhere.

---

## Frontends

| Frontend | Stack | Use Case |
|---|---|---|
| **TUI** | Go + Bubble Tea | Terminal sessions, SSH, lightweight |
| **GUI** | Go + Wails + React | Native-feeling app, file pickers, quick access |
| **Electron** | Electron + React + xterm.js | Full embedded terminal, interactive scripts in-app |

---

## Project Structure

```
Script-Launcher/
├── registry/
│   └── registry.go         # Shared script definitions (TUI + GUI)
├── registry.json            # Shared script definitions (Electron)
├── tui/
│   └── main.go             # Bubble Tea terminal UI
├── gui/
│   ├── app.go              # Wails Go backend
│   ├── main.go             # Wails app entry point
│   └── frontend/
│       └── src/
│           ├── App.jsx     # React frontend
│           └── App.css     # Styles (UNC × Tokyo Night palette)
├── electron-app/
│   ├── src/
│   │   ├── main.ts         # Electron main process + IPC handlers
│   │   ├── preload.ts      # IPC bridge (security boundary)
│   │   ├── renderer.tsx    # React entry point
│   │   ├── App.jsx         # Shared React frontend
│   │   └── App.css         # Shared styles
│   ├── registry.json       # Script registry (symlink or copy)
│   └── package.json
├── go.mod
└── go.sum
```

---

## Requirements

### All Frontends
- **pdftotext** — `brew install poppler` (PDF → Text)
- **Ghostscript** — `brew install ghostscript` (PPTX → PDF compression)
- **ffmpeg** — `brew install ffmpeg` (Lecture Merge)
- **Microsoft PowerPoint** — required for PPTX → PDF conversion

### TUI + GUI
- **Go** 1.22+
- **Wails** v2 — `go install github.com/wailsapp/wails/v2/cmd/wails@latest`
- **Node.js** — for the React frontend (managed by Wails)

### Electron
- **Node.js** 18+
- **npm** 9+

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
| `←` / `→` | Cycle through options (e.g. compression) |
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

See [`electron-app/README.md`](electron-app/README.md) for full setup and usage.

---

## Scripts

### Vault

| Script | Description |
|---|---|
| **Manage Vault** | Full vault management TUI — launches in a Terminal window |
| **Add Vault Link** | Insert a wikilink into an Obsidian note's Supporting Content section |
| **Vault Health** | Scan vault for broken wikilinks and orphaned notes |
| **Cleanup Vault Tools** | Time-gated cleanup — only acts on or after December 2027 |

### Video

| Script | Description |
|---|---|
| **Lecture Merge** | Merge 3 Panopto lecture recordings into a single clean video |

### Documents

| Script | Description |
|---|---|
| **PDF → Text** | Convert one or more PDFs to plain text using pdftotext |
| **PPTX → PDF** | Convert .pptx files to PDF via PowerPoint + Ghostscript |

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
Edit `electron-app/registry.json` — add a script object to the appropriate group:

```json
{
  "name": "My Script",
  "description": "Short description shown in the menu",
  "path": "/Users/careycarroll/bin/my_script",
  "help": "Longer description shown on the detail screen.",
  "interactive": false,
  "argDefs": [
    { "label": "Input file", "filePicker": true },
    { "label": "Mode", "default": "fast", "options": ["fast", "slow", "verbose"] }
  ]
}
```

### Arg Field Reference

| Field | Purpose |
|---|---|
| `filePicker` | Opens a file picker dialog |
| `dirPicker` | Opens a folder picker dialog |
| `setWorkDir` | Sets selected path as the script's working directory |
| `multiFile` | Enables a file/folder queue (multiple inputs) |
| `batchArgs` | Passes all queued files as args in one script call |
| `options` | Renders a dropdown / left-right selector |
| `flag` | Prepends a flag before the value (e.g. `-c ebook`) |
| `interactive` | Launches script in a Terminal window |

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

- [ ] Electron — xterm.js embedded terminal panel for interactive scripts
- [ ] Electron — theme customization panel (CSS variable editor)
- [ ] Electron — package as self-contained `.app`
- [ ] qpdf — bookmark creation script
- [ ] Add Vault Link — end-to-end GUI test
