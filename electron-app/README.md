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

---

## Requirements

- **Node.js** 18+
- **npm** 9+
- **ffmpeg** — `brew install ffmpeg` (Lecture Merge)
- **pdftotext** — `brew install poppler` (PDF → Text)
- **Ghostscript** — `brew install ghostscript` (PPTX → PDF)
- **Microsoft PowerPoint** — required for PPTX → PDF conversion

---

## Setup

```bash
cd electron-app
npm install
```

---

## Running

### Development
```bash
npm start
```

Hot reload is enabled — changes to `src/renderer.tsx`, `App.jsx`, and `App.css` apply immediately. Changes to `src/main.ts` or `src/preload.ts` require a restart (`rs` in the terminal running `npm start`).

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
│   ├── main.ts          # Electron main process — IPC handlers, script execution
│   ├── preload.ts       # Context bridge — exposes electronAPI to renderer
│   ├── renderer.tsx     # React entry point
│   ├── App.jsx          # Shared React UI (mirrored from gui/frontend/src/)
│   └── App.css          # Shared styles (mirrored from gui/frontend/src/)
├── registry.json        # Script definitions — edit this to add scripts
├── index.html           # HTML shell
├── forge.config.ts      # Electron Forge packaging config
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
│  window.electronAPI.*           │
└────────────┬────────────────────┘
             │ contextBridge (preload.ts)
┌────────────▼────────────────────┐
│  Main Process (Node.js)         │
│  main.ts — IPC handlers         │
│  Script execution, file pickers │
│  registry.json                  │
└─────────────────────────────────┘
```

**Security model:** `contextIsolation: true`, `nodeIntegration: false`. The renderer has no direct Node.js access — all system calls go through the IPC bridge defined in `preload.ts`.

---

## IPC API

Exposed to the renderer via `window.electronAPI`:

| Method | Description |
|---|---|
| `GetGroups()` | Returns all script groups from registry.json |
| `RunScript(groupIdx, scriptIdx, args)` | Executes a script, returns `{ output, error }` |
| `PickFile()` | Opens native file picker, returns selected path |
| `PickFolder()` | Opens native folder picker, returns selected path |

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

No restart needed in development — registry is read at startup, restart `npm start` to pick up changes.

---

## Backlog

- [ ] xterm.js embedded terminal panel for interactive scripts
- [ ] Theme customization panel (CSS variable editor)
- [ ] node-pty integration for full PTY support
- [ ] Auto-update via Electron Forge publisher
