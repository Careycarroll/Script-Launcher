<div align="center">
  <img src="../docs/assets/heelworks-icon.png" width="96" alt="Heelworks icon" />
  <h1>Heelworks — Electron</h1>
  <p><em>Primary Heelworks frontend for macOS</em></p>
</div>

The Electron app is the primary Heelworks frontend. It provides a launchpad UI for Documents, Vault, Media, and Developer tools; runs interactive scripts in an embedded terminal; and uses bundled Python scripts for document and workflow automation.

---

## Stack

| Layer        | Technology                             |
| ------------ | -------------------------------------- |
| Shell        | Electron Forge + Vite                  |
| UI           | React                                  |
| Routing      | React Router                           |
| Terminal     | xterm.js + node-pty                    |
| Registry     | `registry.json`                        |
| Python tools | `resources/python/scripts/`            |
| Testing      | Vitest + React Testing Library, pytest |

---

## Requirements

- macOS
- Node.js 22 (`.nvmrc`)
- npm
- `uv` for Python environment setup
- Microsoft PowerPoint for PPTX workflows
- Local/bundled `ffmpeg` for media workflows

---

## Setup

```bash
cd electron-app
nvm use
npm install
```

### Python environment

The app expects a local Python venv at:

```text
resources/python/venv/
```

Create or refresh it with `uv`:

```bash
cd electron-app
uv venv resources/python/venv --python 3.13
uv pip install -r resources/python/requirements.txt --python resources/python/venv/bin/python3
```

If you only need the core document pipeline, confirm it can introspect:

```bash
resources/python/venv/bin/python3 resources/python/scripts/docpipe.py --introspect
```

### Bundled binaries

Local binaries belong in:

```text
resources/bin/
```

That directory is gitignored. The app prepends it to `PATH` at runtime so bundled tools are found before system tools.

---

## Run

Development:

```bash
npm start
```

Package:

```bash
npm run make
```

---

## App Model

The UI is organized around a launchpad and domain tiles:

| Domain    | Main files                                               | Purpose                                      |
| --------- | -------------------------------------------------------- | -------------------------------------------- |
| Documents | `tiles/DocumentsTile.jsx`, `features/BookmarkEditor.jsx` | PDF, PPTX, image, and TTS tools              |
| Vault     | `tiles/VaultTile.jsx`, `tiles/VaultWorkbench.jsx`        | Vault Health and Workbench flows             |
| Media     | `tiles/MediaTile.jsx`, `tiles/MediaWorkbench.jsx`        | Lecture/Panopto/generic downloader workflows |
| Developer | `tiles/DeveloperTile.jsx`                                | Widget and registry test entries             |

Shared UI and plumbing:

- `Launchpad.jsx` — home screen
- `RegistryTile.jsx` — registry-backed script runner
- `WidgetRenderer.jsx` — registry widget rendering
- `Terminal.jsx` — embedded terminal panel
- `ThemePanel.jsx` — live theme drawer
- `main.ts` — Electron main process, IPC, spawning, PTY, streaming handlers
- `preload.ts` — safe renderer API bridge

---

## Tools

### Document operations through `docpipe.py`

```bash
resources/python/venv/bin/python3 resources/python/scripts/docpipe.py --list
resources/python/venv/bin/python3 resources/python/scripts/docpipe.py --introspect
```

Current operations:

| Operation              | Description                         |
| ---------------------- | ----------------------------------- |
| `pdf_to_txt`           | Extract text from PDF               |
| `images_to_pdf`        | Combine images into one PDF         |
| `pptx_to_pdf`          | Convert PowerPoint to PDF on macOS  |
| `pptx_to_txt`          | Pipeline: PPTX → PDF → text         |
| `pdf_merge`            | Merge PDFs                          |
| `pdf_strip`            | Strip PDF metadata                  |
| `pdf_bookmark_analyze` | Detect candidate bookmarks          |
| `pdf_bookmark_add`     | Apply bookmarks from a list         |
| `pdf_split`            | Split by range, count, or bookmarks |

### Text → Audio

`resources/python/scripts/tts_piper.py` powers the Electron **Text → Audio** tool. The repo includes Piper voice models under:

```text
resources/models/piper/
```

Current voices in the registry:

- Ryan
- HFC Female
- Bryce

### Vault and Media scripts

Additional Python scripts live in `resources/python/scripts/`:

- `vault_index.py`
- `panopto_download.py`
- `ytdlp_download.py`
- `tts_piper.py`

---

## Registry

Edit `registry.json` and restart `npm start`.

A standard Python-backed entry looks like this:

```json
{
  "name": "PDF → Text",
  "domain": "documents",
  "path": "python/scripts/docpipe.py",
  "runtime": "python",
  "operation": "pdf_to_txt",
  "interactive": false,
  "argDefs": [
    {
      "label": "PDF files",
      "filePicker": true,
      "multiFile": true,
      "extensions": ["pdf"]
    },
    {
      "label": "Layout",
      "flag": "--pdf_to_txt-layout",
      "default": "layout",
      "options": ["layout", "plain"]
    }
  ]
}
```

Important fields:

| Field               | Purpose                                                   |
| ------------------- | --------------------------------------------------------- |
| `domain`            | Groups tools into Documents, Vault, Media, Developer      |
| `runtime: "python"` | Runs through bundled Python                               |
| `operation`         | First positional argument passed to `docpipe.py`          |
| `interactive`       | Uses embedded terminal behavior for interactive scripts   |
| `component`         | Uses a bespoke React component instead of generic widgets |
| `argDefs`           | Describes UI widgets and CLI arguments                    |

Common widget fields:

- `filePicker`
- `dirPicker`
- `multiFile`
- `extensions`
- `flag`
- `default`
- `options`
- `type: "checkbox"`
- `type: "number"`
- `type: "outputDir"`
- `type: "textarea"`
- `tooltip`
- `showWhen`
- `hidden`
- `invertFlag`

---

## IPC Surface

The renderer uses `window.electronAPI` from `preload.ts`. Current categories include:

- Registry/script execution: `GetGroups`, `RunScript`
- Pickers: `PickFile`, `PickFolder`
- PTY terminal: `PtyShell`, `PtyCreate`, `PtyInput`, `PtyResize`, `PtyKill`
- Bookmark workflow: `AnalyzeBookmarks`
- Vault service: `VaultStart`, `VaultQuery`, `VaultStop`
- Streaming jobs: `StreamStart`, `StreamInput`, `StreamStop`, stream listeners
- Files/external links: `SaveFile`, `ListDir`, `OpenExternal`

---

## Testing

Renderer tests:

```bash
cd electron-app
npm test
```

Python tests:

```bash
cd electron-app
resources/python/venv/bin/python3 -m pytest tests/
```

Discovery status as of the last audit:

- Vitest: 85 tests passing
- pytest: 15 passing, 2 deselected
- GitHub Actions: `tests` and `renderer-tests` passing

---

## Bundled / Local Resources

| Resource                  | Path                             | Git status         |
| ------------------------- | -------------------------------- | ------------------ |
| Python venv               | `resources/python/venv/`         | Local, not tracked |
| Python scripts            | `resources/python/scripts/`      | Tracked            |
| ffmpeg and other binaries | `resources/bin/`                 | Local, ignored     |
| Piper voice models        | `resources/models/piper/`        | Tracked            |
| App icon                  | `resources/icons/heelworks.icns` | Tracked            |

Note: Piper `.onnx` models are large. If repository size becomes a problem, consider Git LFS or a setup-time download step.

---

## Maintenance Notes

- Electron is the primary maintained frontend.
- Go TUI and Wails remain useful as legacy/local launchers.
- Prefer `uv pip` for Python environment setup; the bundled venv may not include `pip` as a module.
- Keep `registry.json` and `docpipe.py --introspect` aligned when adding document operations.
