# ⚡ Script Launcher — Electron

The Electron frontend for Script Launcher. Provides a native macOS app experience with an embedded xterm.js terminal for interactive scripts.

---

## Why Electron

The TUI and Wails GUI both require external Terminal windows for interactive scripts (`manage_vault`, `lecture_merge`). Electron embeds a full PTY terminal via xterm.js — interactive scripts run natively inside the app window.

---

## Stack

| Layer | Technology |
|---|---|
| UI | React + existing App.jsx / App.css |
| Terminal embedding | xterm.js + node-pty |
| Script execution | Node.js `child_process` / `spawn` |
| Registry | `registry.json` |
| Build / Package | Electron Forge + Vite |
| Bundled runtime | Python 3.13.5 (standalone) + pymupdf |
| Bundled binary | ffmpeg (static, darwin-arm64) |

---

## Requirements

- **Node.js** 18+
- **npm** 9+
- **ffmpeg** static binary in `resources/bin/` — see Setup below
- **Microsoft PowerPoint** — required for PPTX → PDF conversion

> **Note:** `pdftotext` and `ghostscript` are being migrated to bundled pymupdf. Until complete, `brew install poppler ghostscript` is required for PDF → Text and PPTX → PDF compression.

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

### Set up bundled Python (required for PDF processing)

```bash
uv venv resources/python/venv \
  --python /Users/careycarroll/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none/bin/python3
uv pip install pymupdf --python resources/python/venv/bin/python3
```

---

## Running

### Development
```bash
npm start
```

Hot reload is enabled — changes to `src/renderer.tsx`, `App.jsx`, and `App.css` apply immediately. Changes to `src/main.ts` or `src/preload.ts` require a restart.

### Production Build
```bash
npm run make
```

Output: `electron-app/out/Script Launcher-darwin-arm64/Script Launcher.app`

Move to `/Applications` or double-click to launch.

---

## Project Structure

```
electron-app/
├── src/
│   ├── main.ts              # Electron main process — IPC handlers, PTY, script execution
│   ├── preload.ts           # Context bridge — exposes electronAPI to renderer
│   ├── renderer.tsx         # React entry point
│   ├── App.jsx              # Shared React UI
│   ├── App.css              # Shared styles (UNC × Tokyo Night palette)
│   └── Terminal.jsx         # xterm.js terminal component
├── resources/
│   ├── bin/
│   │   └── ffmpeg           # Static ffmpeg binary (not in git — see Setup)
│   └── python/
│       └── venv/            # Bundled Python 3.13.5 + pymupdf
├── registry.json            # Script definitions
├── index.html               # HTML shell
├── forge.config.ts          # Electron Forge packaging config
├── vite.main.config.ts      # Vite config for main process
├── vite.preload.config.ts   # Vite config for preload
├── vite.renderer.config.ts  # Vite config for renderer (React)
└── package.json
```

---

## Architecture

```
┌─────────────────────────────────┐
│  Renderer (React)               │
│  App.jsx — UI, state, events    │
│  Terminal.jsx — xterm.js        │
│  window.electronAPI.*           │
└────────────┬────────────────────┘
             │ contextBridge (preload.ts)
┌────────────▼────────────────────┐
│  Main Process (Node.js)         │
│  main.ts — IPC handlers         │
│  node-pty — PTY management      │
│  Script execution, file pickers │
│  registry.json                  │
│  resources/bin/ — bundled tools │
└─────────────────────────────────┘
```

**Security model:** `contextIsolation: true`, `nodeIntegration: false`. The renderer has no direct Node.js access — all system calls go through the IPC bridge defined in `preload.ts`.

---

## Terminal Tab

The app has two tabs — **Scripts** and **Terminal**.

- **Scripts tab** — sidebar + detail panel, file pickers, run buttons
- **Terminal tab** — full xterm.js terminal with live shell, always mounted

When an interactive script runs (e.g. `manage_vault`, `lecture_merge`), the app automatically switches to the Terminal tab and the script runs inside the embedded PTY.

---

## IPC API

Exposed to the renderer via `window.electronAPI`:

| Method | Description |
|---|---|
| `GetGroups()` | Returns all script groups from registry.json |
| `RunScript(groupIdx, scriptIdx, args)` | Executes a script, returns `{ output, error }` |
| `PickFile()` | Opens native file picker, returns selected path |
| `PickFolder()` | Opens native folder picker, returns selected path |
| `PtyShell()` | Spawns default shell in the embedded terminal |
| `PtyCreate(scriptPath)` | Spawns a script in the embedded terminal PTY |
| `PtyInput(data)` | Sends keystrokes to the active PTY |
| `PtyResize(cols, rows)` | Resizes the active PTY |
| `PtyKill()` | Kills the active PTY |
| `onPtyOutput(cb)` | Receives PTY output stream |
| `onPtyExit(cb)` | Notified when PTY process exits |

---

## Adding a New Script

Edit `registry.json` — add a script object to the appropriate group:

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

Restart `npm start` to pick up registry changes.

---

## Bundled Resources

| Resource | Path | Purpose |
|---|---|---|
| ffmpeg | `resources/bin/ffmpeg` | Video processing (Lecture Merge) |
| Python 3.13.5 | `resources/python/venv/` | PDF processing scripts |
| pymupdf | `resources/python/venv/lib/` | PDF text extraction + compression |

The app prepends `resources/bin/` to `PATH` at startup — bundled tools are always found before system-installed versions.

---

## Backlog

- [ ] Rewrite `pdf2txt` using bundled pymupdf (removes pdftotext dependency)
- [ ] Rewrite `pptx2pdf` compression using pymupdf (removes ghostscript dependency)
- [ ] Lite build — ephemeral dependency downloads with consent dialog + cleanup
- [ ] Full build — all binaries bundled, single-file distribution
- [ ] Two build targets: `npm run make:lite` and `npm run make:full`
- [ ] Theme customization panel (CSS variable editor, persisted to localStorage)
- [ ] OS-aware architecture (platform() checks, config file for user paths)
- [ ] PPTX → Text chaining (single script, full pipeline)
- [ ] Auto-update via Electron Forge publisher
