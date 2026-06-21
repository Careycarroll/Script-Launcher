# ⚡ Script Launcher

A dual-interface script launcher for macOS — a Bubble Tea TUI for terminal use and a Wails + React GUI for a native app experience. Both frontends share a single script registry, so adding a new script is a one-file change.

---

## Project Structure

```
Script-Launcher/
├── registry/
│   └── registry.go     # Shared script definitions — edit this to add scripts
├── tui/
│   └── main.go         # Bubble Tea terminal UI
├── gui/
│   ├── app.go          # Wails Go backend
│   ├── main.go         # Wails app entry point
│   └── frontend/
│       └── src/
│           ├── App.jsx # React frontend
│           └── App.css # Styles (UNC × Tokyo Night palette)
├── go.mod
└── go.sum
```

---

## Requirements

- **Go** 1.22+
- **Wails** v2 — `go install github.com/wailsapp/wails/v2/cmd/wails@latest`
- **Node.js** — for the React frontend (managed by Wails)
- **pdftotext** — `brew install poppler` (for PDF → Text)
- **Ghostscript** — `brew install ghostscript` (for PPTX → PDF compression)
- **ffmpeg** — `brew install ffmpeg` (for Lecture Merge)
- **Microsoft PowerPoint** — required for PPTX → PDF conversion

---

## Running the TUI

```bash
go run ./tui/
```

Or build a standalone binary:

```bash
go build -o scripttui ./tui/
./scripttui
```

### TUI Navigation

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

## Running the GUI

### Development (hot reload)
```bash
cd gui && wails dev
```

### Production build
```bash
cd gui && wails build
```

Output: `gui/build/bin/gui.app` — move to `/Applications` or double-click to launch.

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

Lecture Merge auto-classifies three `.mp4` files by audio presence and bitrate, normalizes audio to EBU R128 (-16 LUFS) using two-pass loudnorm, optionally overlays the screen recording as a picture-in-picture at a selectable scale and position, and outputs a named session file.

**Staging folder:** `~/Documents/Vault Management/Video Staging/`  
**Output folder:** `~/Documents/Vault Management/Video Staging/output/`  
**Archive folder:** `~/Documents/Vault Management/Video Staging/archive/`

Place exactly 3 `.mp4` files in the staging folder before running. The script identifies:
- **Audio source** — file with a real audio stream
- **Wide angle** — silent file with bitrate ≥ 500 kbps
- **Screen recording** — silent file with bitrate < 500 kbps

### Documents

| Script | Description |
|---|---|
| **PDF → Text** | Convert one or more PDFs to plain text using pdftotext |
| **PPTX → PDF** | Convert .pptx files to PDF via PowerPoint + Ghostscript |

---

## Adding a New Script

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

### Arg Field Reference

| Field | Purpose |
|---|---|
| `FilePicker` | Opens a file picker dialog |
| `DirPicker` | Opens a folder picker dialog |
| `SetWorkDir` | Sets selected path as the script's working directory |
| `MultiFile` | Enables a file/folder queue (multiple inputs) |
| `BatchArgs` | Passes all queued files as args in one script call |
| `Options` | Renders a dropdown / left-right selector |
| `Flag` | Prepends a flag before the value (e.g. `-c ebook`) |
| `Interactive` | Launches script in a Terminal window (TUI: takes over terminal) |

**After editing the registry:**
- TUI — changes apply immediately on next `go run ./tui/`
- GUI — restart `wails dev` (registry is outside the watch directory)

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

- [ ] Add Vault Link — end-to-end GUI test
- [ ] qpdf bookmark script — create/edit PDF bookmarks from heading structure
- [ ] Electron rewrite — embedded xterm.js for interactive scripts, self-contained binary
